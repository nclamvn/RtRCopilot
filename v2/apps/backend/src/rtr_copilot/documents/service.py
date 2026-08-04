import base64
import binascii
import hashlib
import hmac
import io
import json
import re
import uuid
from collections.abc import AsyncIterator
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import text

from rtr_copilot.auth.audit import StructuredAuditSink
from rtr_copilot.auth.models import PolicyContext, Role, Subject
from rtr_copilot.auth.policy import PolicyEngine
from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.documents.models import (
    ApprovalEvent,
    BindingDefinition,
    BindRequest,
    BindResult,
    BoundField,
    DecisionRequest,
    GeneratedComparison,
    GeneratedHistory,
    GeneratedHistoryItem,
    GeneratedVersionDetail,
    IssuanceResult,
    RenderRequest,
    RenderStatus,
    TemplateHistory,
    TemplateImport,
    TemplateListItem,
    TemplatePage,
    TemplateSchema,
    TemplateVersionDetail,
    TemplateVersionSummary,
)
from rtr_copilot.documents.renderers import MIME_BY_FORMAT, canonical_json, render
from rtr_copilot.documents.validation import validate_schema, validate_template
from rtr_copilot.ingestion.api import _effective_principal_ids
from rtr_copilot.ingestion.service import IngestionService
from rtr_copilot.observability.worker import log_job_request_id
from rtr_copilot.rag.dlp import ProviderPolicy
from rtr_copilot.repositories.audit import AuditRepository
from rtr_copilot.repositories.identity_postgres import PostgresSubjectRepository
from rtr_copilot.repositories.resources import ResourceRecord, ResourceRepository
from rtr_copilot.storage.s3 import S3ObjectStorage

policy = PolicyEngine(StructuredAuditSink())
RENDERER_VERSION = "rtr-doc-os-1"
DOCUMENT_QUEUE = "rtr:jobs"
LOCKED_PLACEHOLDER = re.compile(r"\{([a-z][a-z0-9_.]{0,127})\}")


def hash_json(value: Any) -> str:
    return hashlib.sha256(canonical_json(value)).hexdigest()


def encode_cursor(name: str, template_id: uuid.UUID, secret: str) -> str:
    payload = canonical_json({"name": name, "template_id": str(template_id)})
    signature = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
    return base64.urlsafe_b64encode(payload + signature).decode().rstrip("=")


def decode_cursor(cursor: str, secret: str) -> tuple[str, uuid.UUID]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        raw = base64.urlsafe_b64decode(padded)
        payload, signature = raw[:-32], raw[-32:]
        expected = hmac.new(secret.encode(), payload, hashlib.sha256).digest()
        if not hmac.compare_digest(signature, expected):
            raise ValueError("invalid_cursor")
        value = json.loads(payload)
        return str(value["name"]), uuid.UUID(str(value["template_id"]))
    except (ValueError, KeyError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("invalid_cursor") from error


def manifest_views(
    manifest: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    parameters: dict[str, Any] = {}
    locked: dict[str, dict[str, Any]] = {}
    for raw in manifest.get("fields", []):
        if not isinstance(raw, dict) or not isinstance(raw.get("field_path"), str):
            continue
        path = raw["field_path"]
        if raw.get("source") == "user":
            parameters[path] = raw.get("canonical_value")
        elif raw.get("source") == "locked_fact":
            locked[path] = {
                "value": raw.get("canonical_value"),
                "record_version_id": raw.get("record_version_id"),
                "record_checksum": raw.get("record_checksum"),
                "evidence_checksum": raw.get("evidence_checksum"),
            }
    return parameters, locked


def changed_keys(left: dict[str, Any], right: dict[str, Any]) -> list[str]:
    return sorted(
        key for key in set(left) | set(right)
        if canonical_json(left.get(key)) != canonical_json(right.get(key))
    )


def _scalar_at(payload: Any, path: str) -> str | int | float | bool:
    current = payload
    for part in path.split("."):
        if not isinstance(current, dict) or part not in current:
            raise ValueError("fact_value_invalid")
        current = current[part]
    if isinstance(current, bool | int | float | str):
        return current
    raise ValueError("fact_value_invalid")


def locked_fact_value(binding: BindingDefinition, payload: Any) -> Any:
    """Extract a bounded display scalar without executing template logic."""
    if binding.value_literal is not None:
        source = canonical_json(payload).decode("utf-8")
        if binding.value_literal not in source:
            raise ValueError("fact_literal_drift")
        return binding.value_literal
    if binding.value_template is not None:
        found = LOCKED_PLACEHOLDER.findall(binding.value_template)
        scrubbed = LOCKED_PLACEHOLDER.sub("", binding.value_template)
        if not found or "{" in scrubbed or "}" in scrubbed:
            raise ValueError("fact_value_invalid")
        values = {path: _scalar_at(payload, path) for path in found}
        result = binding.value_template
        for path, value in values.items():
            result = result.replace("{" + path + "}", str(value))
        if len(result) > 2_000:
            raise ValueError("fact_value_invalid")
        return result
    if isinstance(payload, bool | int | float | str):
        return payload
    if isinstance(payload, dict) and isinstance(
        payload.get("value"), bool | int | float | str,
    ):
        return payload["value"]
    raise ValueError("fact_value_invalid")


def safe_error(error: Exception) -> str:
    allowed = {
        "template_invalid", "binding_invalid", "fact_unavailable", "fact_stale",
        "fact_unverified", "fact_caveated", "fact_policy_denied", "render_failed",
        "template_not_approved", "shape_text_overflow", "unresolved_placeholder",
        "formula_error",
    }
    return str(error) if str(error) in allowed else "render_failed"


class DocumentOSService:
    def __init__(self, uow: UnitOfWork | None = None) -> None:
        self.uow = uow or UnitOfWork()
        self.settings = get_settings()
        self.storage = S3ObjectStorage(self.settings)

    async def _audit_import_rejection(
        self,
        subject: Subject,
        *,
        request_id: str,
        reason: str,
    ) -> None:
        try:
            async with self.uow.transaction() as session:
                await AuditRepository().append(
                    session, actor_kind="user",
                    actor_user_id=uuid.UUID(subject.user_id),
                    action="template.import", result="failure",
                    reason_code=reason, request_id=request_id,
                    resource_id=None, resource_type="template_version",
                    details={},
                )
        except Exception:
            # Rejection must remain fail-closed even when the audit dependency is down.
            return

    async def _template_row(
        self,
        subject: Subject,
        version_id: uuid.UUID,
        *,
        action: str,
        request_id: str,
    ) -> dict[str, Any] | None:
        async with self.uow.factory() as session:
            row = (await session.execute(text("""
                SELECT t.template_id,t.stable_key,t.display_name,t.category,
                  t.classification,t.document_class,t.owner_subject_id,t.lifecycle,
                  tv.version_id,tv.version_ordinal,tv.format,tv.source_object_id,
                  tv.source_sha256,tv.field_schema,tv.renderer_kind,
                  tv.renderer_version,tv.status,o.object_key,o.byte_size
                FROM template_versions tv
                JOIN templates t ON t.template_id=tv.template_id
                JOIN object_blobs o ON o.object_id=tv.source_object_id
                WHERE tv.version_id=:version_id
            """), {"version_id": version_id})).mappings().one_or_none()
            if row is None:
                return None
            principals = await _effective_principal_ids(session, subject)
            effective = await ResourceRepository().effective_policy_attributes(
                session, version_id, action=action, principal_ids=principals,
            )
        decision = (
            policy.decide(
                subject, action, effective[0], PolicyContext(request_id=request_id),
            )
            if effective is not None else None
        )
        admin_curate = (
            action == "curate"
            and Role.ADMIN in subject.roles
            and effective is not None
            and not effective[0].explicit_deny
        )
        if decision is None or (not decision.allow and not admin_curate):
            return None
        return dict(row)

    async def import_template(
        self,
        subject: Subject,
        payload: TemplateImport,
        *,
        request_id: str,
    ) -> TemplateVersionDetail:
        if not ({Role.CURATOR, Role.ADMIN} & subject.roles):
            raise PermissionError("curator_required")
        try:
            validate_schema(payload.field_schema)
        except ValueError as error:
            await self._audit_import_rejection(
                subject, request_id=request_id, reason="schema_rejected",
            )
            raise ValueError("template_invalid") from error
        try:
            source = base64.b64decode(payload.source_base64, validate=True)
        except (binascii.Error, ValueError) as error:
            await self._audit_import_rejection(
                subject, request_id=request_id, reason="base64_rejected",
            )
            raise ValueError("template_invalid") from error
        try:
            validate_template(source, payload.format)
        except Exception as error:
            await self._audit_import_rejection(
                subject, request_id=request_id, reason="package_rejected",
            )
            raise ValueError("template_invalid") from error
        digest = hashlib.sha256(source).hexdigest()
        owner_id = uuid.UUID(subject.user_id)
        async with self.uow.factory() as session:
            existing_template = (await session.execute(text("""
                SELECT template_id,owner_subject_id,classification,document_class,
                  COALESCE((SELECT max(version_ordinal) FROM template_versions
                    WHERE template_id=t.template_id),0) max_ordinal
                FROM templates t WHERE stable_key=:stable_key
            """), {"stable_key": payload.stable_key})).mappings().one_or_none()
        if existing_template is not None and (
            (
                existing_template["owner_subject_id"] != owner_id
                and Role.ADMIN not in subject.roles
            )
            or existing_template["classification"] != payload.classification
            or existing_template["document_class"] != payload.document_class
        ):
            raise PermissionError("template_version_denied")
        template_id = (
            existing_template["template_id"] if existing_template else uuid.uuid4()
        )
        version_ordinal = (
            int(existing_template["max_ordinal"]) + 1 if existing_template else 1
        )
        version_id = uuid.uuid4()
        object_id = uuid.uuid4()
        key = f"templates/{template_id}/{version_id}/{object_id}"
        stored = await self.storage.upload_stream(
            key=key,
            stream=io.BytesIO(source),
            mime_type=MIME_BY_FORMAT[payload.format],
            declared_sha256=digest,
            upload_state="available",
        )
        try:
            async with self.uow.transaction() as session:
                resources = ResourceRepository()
                new_resources = [
                    ResourceRecord(
                        resource_id=object_id, resource_type="object",
                        owner_subject_id=owner_id, classification=payload.classification,
                        source_zone="private_context", lifecycle_state="active",
                    ),
                    ResourceRecord(
                        resource_id=version_id, resource_type="template_version",
                        owner_subject_id=owner_id, classification=payload.classification,
                        source_zone="private_context", lifecycle_state="draft",
                    ),
                ]
                if existing_template is None:
                    new_resources.append(ResourceRecord(
                        resource_id=template_id, resource_type="template",
                        owner_subject_id=owner_id, classification=payload.classification,
                        source_zone="private_context", lifecycle_state="draft",
                    ))
                for resource in new_resources:
                    await resources.create(session, resource)
                await session.execute(text("""
                    INSERT INTO object_blobs(
                      object_id,bucket,object_key,sha256,byte_size,mime_type,
                      etag,storage_state,created_by,verified_at
                    ) VALUES (
                      :object_id,:bucket,:object_key,:sha256,:byte_size,:mime,
                      :etag,'available',:owner,now()
                    )
                """), {
                    "object_id": object_id, "bucket": stored.bucket,
                    "object_key": stored.key, "sha256": stored.sha256,
                    "byte_size": stored.byte_size, "mime": MIME_BY_FORMAT[payload.format],
                    "etag": stored.etag, "owner": owner_id,
                })
                if existing_template is None:
                    await session.execute(text("""
                        INSERT INTO templates(
                          template_id,stable_key,display_name,description,category,
                          owner_subject_id,classification,document_class,lifecycle
                        ) VALUES (
                          :template_id,:stable_key,:display_name,:description,:category,
                          :owner,:classification,:document_class,'draft'
                        )
                    """), {
                        **payload.model_dump(
                            exclude={"schema", "source_base64", "format"},
                        ),
                        "template_id": template_id, "owner": owner_id,
                    })
                renderer_kind = f"{payload.format}_declarative"
                await session.execute(text("""
                    INSERT INTO template_versions(
                      version_id,template_id,version_ordinal,format,source_object_id,
                      source_sha256,field_schema,renderer_kind,renderer_version,
                      status,created_by
                    ) VALUES (
                      :version_id,:template_id,:version_ordinal,:format,:object_id,:sha256,
                      CAST(:schema AS jsonb),:renderer_kind,:renderer_version,
                      'draft',:owner
                    )
                """), {
                    "version_id": version_id, "template_id": template_id,
                    "version_ordinal": version_ordinal,
                    "format": payload.format, "object_id": object_id,
                    "sha256": digest,
                    "schema": payload.field_schema.model_dump_json(),
                    "renderer_kind": renderer_kind,
                    "renderer_version": RENDERER_VERSION, "owner": owner_id,
                })
                for binding in payload.field_schema.bindings:
                    await session.execute(text("""
                        INSERT INTO template_bindings(
                          binding_id,template_version_id,field_path,field_type,
                          source,required,rules,record_key,provenance_contract
                        ) VALUES (
                          :id,:version_id,:path,:type,:source,:required,
                          CAST(:rules AS jsonb),:record_key,CAST(:contract AS jsonb)
                        )
                    """), {
                        "id": uuid.uuid4(), "version_id": version_id,
                        "path": binding.field_path, "type": binding.field_type,
                        "source": binding.source, "required": binding.required,
                        "rules": binding.rules.model_dump_json(),
                        "record_key": binding.record_key,
                        "contract": json.dumps({
                            "accepted_provenance": binding.accepted_provenance,
                            "require_fresh": binding.require_fresh,
                        }),
                    })
                await AuditRepository().append(
                    session, actor_kind="user", actor_user_id=owner_id,
                    action="template.import", result="success",
                    reason_code="validated_and_fingerprinted", request_id=request_id,
                    resource_id=version_id, resource_type="template_version",
                    details={"sha256": digest, "format": payload.format},
                )
        except BaseException:
            await self.storage.delete(key)
            await self._audit_import_rejection(
                subject, request_id=request_id, reason="import_transaction_failed",
            )
            raise
        return TemplateVersionDetail.model_validate({
            "template_id": template_id, "version_id": version_id,
            "source_sha256": digest, "renderer_kind": renderer_kind,
            "renderer_version": RENDERER_VERSION, "status": "draft",
            "schema": payload.field_schema,
        })

    async def lifecycle(
        self,
        subject: Subject,
        version_id: uuid.UUID,
        operation: str,
        *,
        request_id: str,
    ) -> None:
        row = await self._template_row(
            subject, version_id, action="curate", request_id=request_id,
        )
        if row is None:
            raise LookupError("not_found")
        transitions = {
            "submit": ("draft", "in_review"),
            "approve": ("in_review", "approved"),
            "retire": ("approved", "retired"),
        }
        if operation not in transitions:
            raise ValueError("invalid_transition")
        before, after = transitions[operation]
        if operation == "approve" and not ({Role.CURATOR, Role.ADMIN} & subject.roles):
            raise PermissionError("curator_required")
        async with self.uow.transaction() as session:
            result = await session.execute(text("""
                UPDATE template_versions SET status=:after,
                  approved_by=CASE WHEN :after='approved' THEN :actor ELSE approved_by END,
                  approved_at=CASE WHEN :after='approved' THEN now() ELSE approved_at END,
                  retired_at=CASE WHEN :after='retired' THEN now() ELSE retired_at END
                WHERE version_id=:version_id AND status=:before
            """), {
                "after": after, "before": before, "actor": uuid.UUID(subject.user_id),
                "version_id": version_id,
            })
            if getattr(result, "rowcount", 0) != 1:
                raise ValueError("stale_transition")
            await session.execute(text("""
                UPDATE template_versions SET status='retired',retired_at=now()
                WHERE template_id=:template_id AND status='approved'
                  AND :after='approved' AND version_id<>:version_id
            """), {
                "after": after, "template_id": row["template_id"],
                "version_id": version_id,
            })
            await session.execute(text("""
                UPDATE resources SET lifecycle_state='superseded',updated_at=now()
                WHERE resource_id IN (
                  SELECT version_id FROM template_versions
                  WHERE template_id=:template_id AND status='retired'
                )
            """), {"template_id": row["template_id"]})
            await session.execute(text("""
                UPDATE templates SET lifecycle=:after,
                  current_version_id=CASE WHEN :after='approved' THEN :version_id
                    ELSE current_version_id END,updated_at=now()
                WHERE template_id=:template_id
                  AND (current_version_id IS NULL OR :after IN ('approved','retired'))
            """), {
                "after": after, "version_id": version_id,
                "template_id": row["template_id"],
            })
            await session.execute(text("""
                UPDATE resources SET lifecycle_state=:state,updated_at=now()
                WHERE resource_id=:version_id
            """), {
                "state": "superseded" if after == "retired" else (
                    "active" if after == "approved" else "draft"
                ),
                "template_id": row["template_id"], "version_id": version_id,
            })
            await session.execute(text("""
                UPDATE resources SET lifecycle_state=:state,updated_at=now()
                WHERE resource_id=:template_id
                  AND (
                    :after IN ('approved','retired')
                    OR NOT EXISTS (
                      SELECT 1 FROM templates
                      WHERE template_id=:template_id AND current_version_id IS NOT NULL
                    )
                  )
            """), {
                "state": "superseded" if after == "retired" else (
                    "active" if after == "approved" else "draft"
                ),
                "after": after, "template_id": row["template_id"],
            })
            await AuditRepository().append(
                session, actor_kind="user",
                actor_user_id=uuid.UUID(subject.user_id),
                action=f"template.{operation}", result="success",
                reason_code=f"template_{after}", request_id=request_id,
                resource_id=version_id, resource_type="template_version",
                details={},
            )

    async def list_templates(
        self,
        subject: Subject,
        *,
        request_id: str,
        limit: int = 25,
        cursor: str | None = None,
    ) -> TemplatePage:
        items: list[TemplateListItem] = []
        cursor_name: str | None = None
        cursor_id: uuid.UUID | None = None
        if cursor:
            cursor_name, cursor_id = decode_cursor(
                cursor, self.settings.sot_signing_secret.get_secret_value(),
            )
        async with self.uow.factory() as session:
            principals = await _effective_principal_ids(session, subject)
            rows = (await session.execute(text("""
                SELECT t.template_id,t.stable_key,t.display_name,t.category,
                  t.classification,t.document_class,t.owner_subject_id,
                  tv.version_id,tv.version_ordinal,tv.format,tv.status,s.display_name owner_name
                FROM templates t JOIN template_versions tv
                  ON tv.version_id=t.current_version_id
                LEFT JOIN subjects s ON s.user_id=t.owner_subject_id
                WHERE t.lifecycle='approved' AND tv.status='approved'
                  AND (
                    CAST(:cursor_name AS text) IS NULL
                    OR (lower(t.display_name),t.template_id) >
                       (CAST(:cursor_name AS text),CAST(:cursor_id AS uuid))
                  )
                ORDER BY lower(t.display_name),t.template_id LIMIT 500
            """), {
                "cursor_name": cursor_name, "cursor_id": cursor_id,
            })).mappings().all()
            for row in rows:
                effective = await ResourceRepository().effective_policy_attributes(
                    session, row["version_id"], action="view", principal_ids=principals,
                )
                if not effective or not policy.decide(
                    subject, "view", effective[0], PolicyContext(request_id=request_id),
                ).allow:
                    continue
                items.append(TemplateListItem(
                    template_id=row["template_id"], version_id=row["version_id"],
                    stable_key=row["stable_key"], display_name=row["display_name"],
                    category=row["category"], classification=row["classification"],
                    document_class=row["document_class"], format=row["format"],
                    version_ordinal=row["version_ordinal"], status=row["status"],
                    owner_display_name=row["owner_name"],
                ))
                if len(items) >= limit:
                    break
        next_cursor = None
        if len(items) == limit:
            last = items[-1]
            next_cursor = encode_cursor(
                last.display_name.lower(), last.template_id,
                self.settings.sot_signing_secret.get_secret_value(),
            )
        return TemplatePage(items=items, next_cursor=next_cursor)

    async def detail(
        self,
        subject: Subject,
        version_id: uuid.UUID,
        *,
        request_id: str,
    ) -> TemplateVersionDetail:
        row = await self._template_row(
            subject, version_id, action="view", request_id=request_id,
        )
        if row is None:
            raise LookupError("not_found")
        return TemplateVersionDetail.model_validate({
            "template_id": row["template_id"], "version_id": row["version_id"],
            "source_sha256": str(row["source_sha256"]),
            "renderer_kind": row["renderer_kind"],
            "renderer_version": row["renderer_version"], "status": row["status"],
            "schema": TemplateSchema.model_validate(row["field_schema"]),
        })

    async def template_history(
        self,
        subject: Subject,
        template_id: uuid.UUID,
        *,
        request_id: str,
    ) -> TemplateHistory:
        versions: list[TemplateVersionSummary] = []
        async with self.uow.factory() as session:
            principals = await _effective_principal_ids(session, subject)
            rows = (await session.execute(text("""
                SELECT version_id,version_ordinal,format,source_sha256,
                  renderer_version,status,created_at,approved_at
                FROM template_versions WHERE template_id=:template_id
                ORDER BY version_ordinal DESC
            """), {"template_id": template_id})).mappings().all()
            for row in rows:
                effective = await ResourceRepository().effective_policy_attributes(
                    session, row["version_id"], action="view", principal_ids=principals,
                )
                if effective and policy.decide(
                    subject, "view", effective[0], PolicyContext(request_id=request_id),
                ).allow:
                    versions.append(TemplateVersionSummary(
                        version_id=row["version_id"],
                        version_ordinal=row["version_ordinal"],
                        format=row["format"],
                        source_sha256=str(row["source_sha256"]),
                        renderer_version=row["renderer_version"],
                        status=row["status"],
                        created_at=row["created_at"],
                        approved_at=row["approved_at"],
                    ))
        if not versions:
            raise LookupError("not_found")
        return TemplateHistory(template_id=template_id, versions=versions)

    def _coerce_user(self, binding: BindingDefinition, value: Any) -> Any:
        rules = binding.rules
        if value is None:
            return None
        if binding.field_type in {"string", "multiline", "enum"}:
            if not isinstance(value, str):
                raise ValueError("binding_invalid")
            if value.startswith(("=", "+", "-", "@")):
                value = "'" + value
            if rules.min_length is not None and len(value) < rules.min_length:
                raise ValueError("binding_invalid")
            if rules.max_length is not None and len(value) > rules.max_length:
                raise ValueError("binding_invalid")
            if binding.field_type == "enum" and value not in rules.enum:
                raise ValueError("binding_invalid")
            return value
        if binding.field_type == "integer":
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError("binding_invalid")
            if (
                rules.minimum is None or rules.maximum is None
                or Decimal(value) < rules.minimum or Decimal(value) > rules.maximum
            ):
                raise ValueError("binding_invalid")
            return value
        if binding.field_type == "decimal":
            try:
                decimal_value = Decimal(str(value))
            except InvalidOperation as error:
                raise ValueError("binding_invalid") from error
            if (
                not decimal_value.is_finite()
                or rules.minimum is None or rules.maximum is None
                or decimal_value < rules.minimum or decimal_value > rules.maximum
            ):
                raise ValueError("binding_invalid")
            return str(decimal_value)
        if binding.field_type == "boolean":
            if not isinstance(value, bool):
                raise ValueError("binding_invalid")
            return value
        if binding.field_type == "date":
            if not isinstance(value, str):
                raise ValueError("binding_invalid")
            try:
                return date.fromisoformat(value).isoformat()
            except ValueError as error:
                raise ValueError("binding_invalid") from error
        if binding.field_type in {"list", "table"}:
            if not isinstance(value, list):
                raise ValueError("binding_invalid")
            bound = rules.max_items if binding.field_type == "list" else rules.max_rows
            if bound is None or len(value) > bound:
                raise ValueError("binding_invalid")
            return value
        raise ValueError("binding_invalid")

    async def bind(
        self,
        subject: Subject,
        version_id: uuid.UUID,
        request: BindRequest,
        *,
        request_id: str,
    ) -> BindResult:
        row = await self._template_row(
            subject, version_id, action="render", request_id=request_id,
        )
        if row is None or row["status"] != "approved":
            raise LookupError("not_found")
        schema = TemplateSchema.model_validate(row["field_schema"])
        known = {item.field_path for item in schema.bindings if item.source == "user"}
        if set(request.parameters) - known:
            raise ValueError("binding_invalid")
        extracted: dict[str, str] = {}
        spans: dict[str, tuple[int, int]] = {}
        if request.extraction_text:
            for field_path in known:
                marker = f"{field_path}:"
                start = request.extraction_text.find(marker)
                if start < 0:
                    continue
                value_start = start + len(marker)
                value_end = request.extraction_text.find("\n", value_start)
                if value_end < 0:
                    value_end = len(request.extraction_text)
                candidate = request.extraction_text[value_start:value_end].strip()
                if candidate:
                    extracted[field_path] = candidate
                    spans[field_path] = (value_start, value_end)
        effective_parameters = {**extracted, **request.parameters}
        fields: list[BoundField] = []
        missing: list[str] = []
        blocked: list[dict[str, str]] = []
        revision: int | None = None
        for binding in schema.bindings:
            if binding.source == "user":
                value = self._coerce_user(
                    binding, effective_parameters.get(binding.field_path),
                )
                if binding.required and value in (None, ""):
                    missing.append(binding.field_path)
                fields.append(BoundField(
                    field_path=binding.field_path, source="user", value=value,
                    confidence=1.0 if value not in (None, "") else None,
                    source_span=(
                        spans.get(binding.field_path)
                        if binding.field_path not in request.parameters else None
                    ),
                ))
                continue
            if binding.source == "derived":
                inputs = [effective_parameters.get(key) for key in binding.derived_fields]
                if any(value in (None, "") for value in inputs):
                    if binding.required:
                        missing.append(binding.field_path)
                    value = None
                elif binding.derived_operation == "concat":
                    value = " ".join(str(item) for item in inputs)
                elif binding.derived_operation in {
                    "date_day", "date_month", "date_year",
                }:
                    try:
                        parsed = date.fromisoformat(str(inputs[0]))
                    except ValueError as error:
                        raise ValueError("binding_invalid") from error
                    value = {
                        "date_day": parsed.day,
                        "date_month": parsed.month,
                        "date_year": parsed.year,
                    }[binding.derived_operation]
                else:
                    raise ValueError("binding_invalid")
                fields.append(BoundField(
                    field_path=binding.field_path, source="derived", value=value,
                ))
                continue
            assert binding.record_key
            async with self.uow.factory() as session:
                record_id = await session.scalar(text("""
                    SELECT record_id FROM records
                    WHERE record_key=:key AND lifecycle='active'
                """), {"key": binding.record_key})
                if record_id is None:
                    blocked.append({"field": binding.field_path, "code": "fact_unavailable"})
                    continue
                principals = await _effective_principal_ids(session, subject)
                effective = await ResourceRepository().effective_policy_attributes(
                    session, record_id, action="view", principal_ids=principals,
                )
                if not effective or not policy.decide(
                    subject, "view", effective[0], PolicyContext(request_id=request_id),
                ).allow:
                    blocked.append({"field": binding.field_path, "code": "fact_policy_denied"})
                    continue
                fact = (await session.execute(text("""
                    SELECT rv.version_id,rv.value_payload,rv.provenance_level,
                      rv.verification_state,rv.fact_state,rv.freshness_state,
                      rv.effective_from,rv.effective_to,rv.content_sha256,
                      rv.package_revision,e.evidence_key,e.evidence_sha256,
                      e.source_blob_sha256,e.locator,
                      COALESCE(s.display_name,s.email,s.user_id::text) AS owner_name
                    FROM records r JOIN record_versions rv
                      ON rv.version_id=r.current_version_id
                    JOIN subjects s ON s.user_id=r.owner_subject_id
                    JOIN sot_packages p ON p.package_id=rv.package_id
                    LEFT JOIN LATERAL (
                      SELECT evidence_key,evidence_sha256,source_blob_sha256,locator
                      FROM evidence_spans WHERE record_version_id=rv.version_id
                        AND lifecycle='active' ORDER BY evidence_key LIMIT 1
                    ) e ON true
                    WHERE r.record_id=:record_id AND rv.lifecycle='active'
                      AND p.lifecycle='active'
                """), {"record_id": record_id})).mappings().one_or_none()
            if fact is None:
                blocked.append({"field": binding.field_path, "code": "fact_unavailable"})
                continue
            now = datetime.now(UTC)
            official = row["document_class"] in {"official", "legal"}
            caveated = (
                fact["value_payload"].get("confidence_signal", {}).get(
                    "needs_double_check",
                ) is True
                if isinstance(fact["value_payload"], dict) else False
            )
            if official and caveated:
                blocked.append({"field": binding.field_path, "code": "fact_caveated"})
                continue
            if official and (
                fact["verification_state"] not in {"verified", "approved"}
                or fact["fact_state"] not in {"verified", "approved"}
                or fact["provenance_level"] not in binding.accepted_provenance
            ):
                blocked.append({"field": binding.field_path, "code": "fact_unverified"})
                continue
            if (
                binding.require_fresh and fact["freshness_state"] != "current"
            ) or fact["effective_from"] > now or (
                fact["effective_to"] is not None and fact["effective_to"] <= now
            ):
                blocked.append({"field": binding.field_path, "code": "fact_stale"})
                continue
            revision = max(revision or 0, int(fact["package_revision"]))
            try:
                display_value = locked_fact_value(binding, fact["value_payload"])
            except ValueError:
                blocked.append({"field": binding.field_path, "code": "fact_unavailable"})
                continue
            if caveated:
                display_value = (
                    f"{display_value} [CAVEAT: needs_double_check · "
                    f"owner: {fact['owner_name'] or 'unassigned'}]"
                )
            fields.append(BoundField(
                field_path=binding.field_path, source="locked_fact",
                value=display_value, record_key=binding.record_key,
                record_version_id=fact["version_id"],
                record_checksum=str(fact["content_sha256"]),
                evidence_key=fact["evidence_key"],
                evidence_checksum=(
                    str(fact["evidence_sha256"]) if fact["evidence_sha256"] else None
                ),
                locator=fact["locator"] or {},
                provenance_level=fact["provenance_level"],
                verification_state=fact["verification_state"],
                freshness_state=fact["freshness_state"],
            ))
        return BindResult(
            valid=not missing and not blocked,
            fields=fields, missing=missing, blocked=blocked, sot_revision=revision,
        )

    async def create_render(
        self,
        subject: Subject,
        version_id: uuid.UUID,
        request: RenderRequest,
        *,
        request_id: str,
    ) -> RenderStatus:
        binding = await self.bind(
            subject, version_id, BindRequest(parameters=request.parameters),
            request_id=request_id,
        )
        if not binding.valid:
            code = binding.blocked[0]["code"] if binding.blocked else "binding_invalid"
            raise ValueError(code)
        canonical_hash = hash_json({
            "template_version_id": str(version_id),
            "parameters": request.parameters,
            "fields": [field.model_dump(mode="json") for field in binding.fields],
        })
        actor = uuid.UUID(subject.user_id)
        job_id = uuid.uuid4()
        created = False
        async with self.uow.transaction() as session:
            existing = (await session.execute(text("""
                SELECT render_job_id,state,progress FROM render_jobs
                WHERE requester_id=:actor AND (
                  idempotency_key=:key OR
                  (template_version_id=:version_id AND canonical_input_hash=:input_hash)
                ) ORDER BY created_at LIMIT 1
            """), {
                "actor": actor, "key": request.idempotency_key,
                "version_id": version_id, "input_hash": canonical_hash,
            })).mappings().one_or_none()
            if existing:
                return await self.status(subject, existing["render_job_id"], request_id=request_id)
            await session.execute(text("""
                INSERT INTO render_jobs(
                  render_job_id,requester_id,idempotency_key,canonical_input_hash,
                  template_version_id,sot_revision,state,progress,request_id
                ) VALUES (
                  :job_id,:actor,:key,:input_hash,:version_id,:revision,
                  'pending',0,:request_id
                )
            """), {
                "job_id": job_id, "actor": actor, "key": request.idempotency_key,
                "input_hash": canonical_hash, "version_id": version_id,
                "revision": binding.sot_revision, "request_id": request_id,
            })
            await session.execute(text("""
                INSERT INTO document_publication_outbox(
                  outbox_id,render_job_id,state,payload
                ) VALUES (
                  :outbox_id,:job_id,'pending',
                  jsonb_build_object('template_version_id',CAST(:version_id AS text))
                )
            """), {
                "outbox_id": uuid.uuid4(), "job_id": job_id,
                "version_id": str(version_id),
            })
            for field in binding.fields:
                await session.execute(text("""
                    INSERT INTO render_job_bindings(
                      render_binding_id,render_job_id,field_path,source,
                      canonical_value,record_key,record_version_id,record_checksum,
                      evidence_key,evidence_checksum,source_checksum,locator,
                      provenance_level,verification_state,freshness_state
                    ) VALUES (
                      :id,:job,:field,:source,CAST(:value AS jsonb),:record_key,
                      :record_version,:record_checksum,:evidence_key,
                      :evidence_checksum,:source_checksum,CAST(:locator AS jsonb),
                      :provenance,:verification,:freshness
                    )
                """), {
                    "id": uuid.uuid4(), "job": job_id, "field": field.field_path,
                    "source": field.source,
                    "value": json.dumps(field.value, ensure_ascii=False),
                    "record_key": field.record_key,
                    "record_version": field.record_version_id,
                    "record_checksum": field.record_checksum,
                    "evidence_key": field.evidence_key,
                    "evidence_checksum": field.evidence_checksum,
                    "source_checksum": None,
                    "locator": json.dumps(field.locator),
                    "provenance": field.provenance_level,
                    "verification": field.verification_state,
                    "freshness": field.freshness_state,
                })
            created = True
        if created:
            client = Redis.from_url(self.settings.redis_url, decode_responses=True)
            try:
                await client.lpush(DOCUMENT_QUEUE, json.dumps({
                    "name": "document.render", "job_id": str(job_id),
                    "request_id": request_id,
                }))
            finally:
                await client.aclose()
        return RenderStatus(render_job_id=job_id, state="pending", progress=0)

    async def status(
        self,
        subject: Subject,
        job_id: uuid.UUID,
        *,
        request_id: str,
    ) -> RenderStatus:
        async with self.uow.factory() as session:
            row = (await session.execute(text("""
                SELECT j.render_job_id,j.requester_id,j.state,j.progress,j.error_code,
                  g.generated_file_id,g.version_id,g.checksum
                FROM render_jobs j LEFT JOIN generated_files g
                  ON g.render_job_id=j.render_job_id
                WHERE j.render_job_id=:job_id
            """), {"job_id": job_id})).mappings().one_or_none()
        if row is None or str(row["requester_id"]) != subject.user_id:
            raise LookupError("not_found")
        return RenderStatus(
            render_job_id=row["render_job_id"], state=row["state"],
            progress=row["progress"], generated_file_id=row["generated_file_id"],
            version_id=row["version_id"], checksum=(
                str(row["checksum"]) if row["checksum"] else None
            ), error_code=row["error_code"],
        )

    async def generated_detail(
        self,
        subject: Subject,
        generated_id: uuid.UUID,
        *,
        request_id: str,
    ) -> GeneratedVersionDetail:
        async with self.uow.factory() as session:
            row = (await session.execute(text("""
                SELECT g.*,j.requester_id,j.template_version_id
                FROM generated_files g JOIN render_jobs j USING(render_job_id)
                WHERE g.generated_file_id=:generated_id
            """), {"generated_id": generated_id})).mappings().one_or_none()
            if row is None:
                raise LookupError("not_found")
            principals = await _effective_principal_ids(session, subject)
            effective = await ResourceRepository().effective_policy_attributes(
                session, row["version_id"], action="view", principal_ids=principals,
            )
            if not effective or not policy.decide(
                subject, "view", effective[0], PolicyContext(request_id=request_id),
            ).allow:
                raise LookupError("not_found")
            decisions = (await session.execute(text("""
                SELECT a.*,s.display_name reviewer_display_name
                FROM approvals a LEFT JOIN subjects s
                  ON s.user_id=a.reviewer_subject_id
                WHERE a.generated_file_id=:generated_id
                ORDER BY a.decided_at,a.approval_id
            """), {"generated_id": generated_id})).mappings().all()
            issuance = (await session.execute(text("""
                SELECT issuance_id,issue_number,issued_checksum,issued_at,
                  revoked_at
                FROM document_issuances
                WHERE generated_file_id=:generated_id
            """), {"generated_id": generated_id})).mappings().one_or_none()
        approval_events = [
            ApprovalEvent(
                approval_id=item["approval_id"], stage=item["stage"],
                reviewer_subject_id=item["reviewer_subject_id"],
                reviewer_display_name=item["reviewer_display_name"],
                decision=item["decision"], checksum=str(item["checksum"]),
                reason=item["reason"], decided_at=item["decided_at"],
            )
            for item in decisions
        ]
        issuance_result = None
        if issuance is not None:
            issuance_result = IssuanceResult(
                issuance_id=issuance["issuance_id"],
                issue_number=issuance["issue_number"],
                state="revoked" if issuance["revoked_at"] else "issued",
                checksum=str(issuance["issued_checksum"]),
                at=issuance["revoked_at"] or issuance["issued_at"],
            )
        return GeneratedVersionDetail(
            generated_file_id=row["generated_file_id"],
            render_job_id=row["render_job_id"],
            template_version_id=row["template_version_id"],
            version_id=row["version_id"], output_format=row["output_format"],
            checksum=str(row["checksum"]), lifecycle=row["lifecycle"],
            render_manifest=row["render_manifest"], created_at=row["created_at"],
            approvals=approval_events, issuance=issuance_result,
        )

    async def generated_history(
        self,
        subject: Subject,
        template_id: uuid.UUID,
        *,
        request_id: str,
    ) -> GeneratedHistory:
        visible: list[dict[str, Any]] = []
        async with self.uow.factory() as session:
            principals = await _effective_principal_ids(session, subject)
            rows = (await session.execute(text("""
                SELECT g.generated_file_id,g.version_id,g.lifecycle,g.checksum,
                  g.created_at,g.render_manifest,j.template_version_id
                FROM generated_files g
                JOIN render_jobs j USING(render_job_id)
                JOIN template_versions tv
                  ON tv.version_id=j.template_version_id
                WHERE tv.template_id=:template_id
                ORDER BY g.created_at,g.generated_file_id
                LIMIT 200
            """), {"template_id": template_id})).mappings().all()
            for raw_row in rows:
                effective = await ResourceRepository().effective_policy_attributes(
                    session, raw_row["version_id"], action="view",
                    principal_ids=principals,
                )
                if effective and policy.decide(
                    subject, "view", effective[0],
                    PolicyContext(request_id=request_id),
                ).allow:
                    visible.append(dict(raw_row))
        if not visible:
            raise LookupError("not_found")
        items: list[GeneratedHistoryItem] = []
        previous: dict[str, Any] | None = None
        previous_parameters: dict[str, Any] = {}
        previous_locked: dict[str, dict[str, Any]] = {}
        for row in visible:
            parameters, locked = manifest_views(row["render_manifest"])
            items.append(GeneratedHistoryItem(
                generated_file_id=row["generated_file_id"],
                template_version_id=row["template_version_id"],
                version_id=row["version_id"], lifecycle=row["lifecycle"],
                checksum=str(row["checksum"]), created_at=row["created_at"],
                parameters=parameters, locked_snapshots=locked,
                comparison=GeneratedComparison(
                    previous_generated_file_id=(
                        previous["generated_file_id"] if previous else None
                    ),
                    changed_parameters=(
                        changed_keys(previous_parameters, parameters)
                        if previous else []
                    ),
                    changed_locked_facts=(
                        changed_keys(previous_locked, locked) if previous else []
                    ),
                    template_changed=bool(
                        previous
                        and previous["template_version_id"]
                        != row["template_version_id"]
                    ),
                    checksum_changed=bool(
                        previous and previous["checksum"] != row["checksum"]
                    ),
                    lifecycle_changed=bool(
                        previous and previous["lifecycle"] != row["lifecycle"]
                    ),
                ),
            ))
            previous = row
            previous_parameters = parameters
            previous_locked = locked
        return GeneratedHistory(template_id=template_id, items=list(reversed(items)))

    async def render_action(
        self,
        subject: Subject,
        job_id: uuid.UUID,
        action: str,
        *,
        request_id: str,
    ) -> RenderStatus:
        if action not in {"cancel", "retry"}:
            raise ValueError("invalid_request")
        actor = uuid.UUID(subject.user_id)
        target = "cancelled" if action == "cancel" else "pending"
        allowed = ("pending",) if action == "cancel" else ("failed", "cancelled")
        async with self.uow.transaction() as session:
            version_id = await session.scalar(text("""
                SELECT template_version_id FROM render_jobs
                WHERE render_job_id=:job_id AND requester_id=:actor
            """), {"job_id": job_id, "actor": actor})
            result = await session.execute(text("""
                UPDATE render_jobs SET state=:target,progress=0,error_code=NULL,
                  started_at=NULL,finished_at=NULL
                WHERE render_job_id=:job_id AND requester_id=:actor
                  AND state=ANY(:allowed)
            """), {
                "target": target, "job_id": job_id, "actor": actor,
                "allowed": list(allowed),
            })
            if getattr(result, "rowcount", 0) != 1:
                raise ValueError("stale_transition")
            await session.execute(text("""
                UPDATE document_publication_outbox
                SET state=:outbox_state,error_code=NULL,updated_at=now()
                WHERE render_job_id=:job_id AND state<>'finalized'
            """), {
                "outbox_state": "cancelled" if action == "cancel" else "pending",
                "job_id": job_id,
            })
            await AuditRepository().append(
                session, actor_kind="user", actor_user_id=actor,
                action=f"document.render.{action}", result="success",
                reason_code=f"render_{target}", request_id=request_id,
                resource_id=version_id, resource_type="template_version",
                details={"render_job_id": str(job_id)},
            )
        if action == "retry":
            client = Redis.from_url(self.settings.redis_url, decode_responses=True)
            try:
                await client.lpush(DOCUMENT_QUEUE, json.dumps({
                    "name": "document.render", "job_id": str(job_id),
                    "request_id": request_id,
                }))
            finally:
                await client.aclose()
        return await self.status(subject, job_id, request_id=request_id)

    async def process_render(self, job_id: uuid.UUID) -> None:
        async with self.uow.factory() as session:
            job = (await session.execute(text("""
                SELECT j.*,tv.format,tv.source_sha256,tv.source_object_id,
                  tv.renderer_version,tv.status template_status,
                  t.document_class,t.classification,t.lifecycle template_lifecycle,
                  o.object_key,o.byte_size
                FROM render_jobs j JOIN template_versions tv
                  ON tv.version_id=j.template_version_id
                JOIN templates t ON t.template_id=tv.template_id
                JOIN object_blobs o ON o.object_id=tv.source_object_id
                WHERE j.render_job_id=:job_id
            """), {"job_id": job_id})).mappings().one_or_none()
            fields = (await session.execute(text("""
                SELECT field_path,source,canonical_value,record_version_id,
                  record_checksum,evidence_checksum,locator
                FROM render_job_bindings WHERE render_job_id=:job_id
                ORDER BY field_path
            """), {"job_id": job_id})).mappings().all()
        if job is None or job["state"] == "completed":
            return
        # AC-09: log the originating request-id the api persisted on the job row
        # while the worker processes it (proves the ingress→api→worker chain).
        log_job_request_id("render", str(job["request_id"]), job_id=str(job_id))
        created: dict[str, Any] | None = None
        cleanup_keys: list[str] = []
        try:
            async with self.uow.transaction() as session:
                changed = await session.execute(text("""
                    UPDATE render_jobs SET state='rendering',progress=35,started_at=now()
                    WHERE render_job_id=:job_id AND state='pending'
                """), {"job_id": job_id})
                if getattr(changed, "rowcount", 0) != 1:
                    return
                preparing = await session.execute(text("""
                    UPDATE document_publication_outbox
                    SET state='preparing',attempts=attempts+1,updated_at=now()
                    WHERE render_job_id=:job_id AND state IN ('pending','failed')
                """), {"job_id": job_id})
                if getattr(preparing, "rowcount", 0) != 1:
                    raise ValueError("render_failed")
            template = io.BytesIO()
            await self.storage.download_to(str(job["object_key"]), template)
            values = {str(item["field_path"]): item["canonical_value"] for item in fields}
            requester = await PostgresSubjectRepository(
                self.uow.factory, request_id=str(job["request_id"]),
            ).get_by_user_id(job["requester_id"])
            if requester is None:
                raise ValueError("template_not_approved")
            await self._publication_guard(job, fields, requester)
            if not ProviderPolicy().inspect_context(
                canonical_json(values).decode(),
                {str(job["classification"])},
            ).allow:
                raise ValueError("binding_invalid")
            output = render(str(job["format"]), template.read(), values)
            checksum = hashlib.sha256(output).hexdigest()
            parent = ResourceRecord(
                resource_id=job["template_version_id"],
                resource_type="template_version",
                owner_subject_id=job["requester_id"],
                classification=job["classification"],
                source_zone="private_context",
                lifecycle_state="active",
            )

            async def chunks() -> AsyncIterator[bytes]:
                yield output

            ingestion = IngestionService()
            upload_id, validation_job = await ingestion.receive(
                chunks(), content_length=len(output), parent=parent,
                logical_name=f"generated-{job_id}",
                original_filename=f"generated-{job_id}.{job['format']}",
                declared_mime=MIME_BY_FORMAT[str(job["format"])],
                declared_sha256=checksum, requested_by=job["requester_id"],
                request_id=str(job["request_id"]),
                defer_publication=True,
            )
            await ingestion.process_job(validation_job, worker_id=f"document-{job_id}")
            async with self.uow.factory() as session:
                created = dict((await session.execute(text("""
                    SELECT document_id,version_id,object_id,state FROM upload_sessions
                    WHERE upload_id=:upload_id
                """), {"upload_id": upload_id})).mappings().one())
                render_job = await session.scalar(text("""
                    SELECT job_id FROM ingestion_jobs
                    WHERE version_id=:version_id AND job_type='render'
                """), {"version_id": created["version_id"]})
            if created["state"] != "accepted" or not render_job:
                raise ValueError("render_failed")
            await ingestion.process_job(render_job, worker_id=f"document-{job_id}")
            # The render and Files pipelines can take seconds. Recheck policy,
            # template state and exact fact snapshots after all staged artifacts
            # exist, immediately before the one observable publication commit.
            await self._publication_guard(job, fields, requester)
            manifest = {
                "schema_version": 1, "template_version_id": str(job["template_version_id"]),
                "template_sha256": str(job["source_sha256"]),
                "renderer_version": str(job["renderer_version"]),
                "canonical_input_hash": str(job["canonical_input_hash"]),
                "sot_revision": job["sot_revision"],
                "fields": [
                    {
                        "field_path": str(item["field_path"]),
                        "source": str(item["source"]),
                        "canonical_value": item["canonical_value"],
                        "record_version_id": (
                            str(item["record_version_id"])
                            if item["record_version_id"] else None
                        ),
                        "record_checksum": (
                            str(item["record_checksum"]) if item["record_checksum"] else None
                        ),
                        "evidence_checksum": (
                            str(item["evidence_checksum"]) if item["evidence_checksum"] else None
                        ),
                        "locator": item["locator"],
                    }
                    for item in fields
                ],
            }
            generated_id = uuid.uuid4()
            async with self.uow.transaction() as session:
                await session.execute(text("""
                    INSERT INTO generated_files(
                      generated_file_id,render_job_id,document_id,version_id,object_id,
                      output_format,ordinal,checksum,render_manifest,lifecycle
                    ) VALUES (
                      :generated,:job,:document,:version,:object,:format,1,:checksum,
                      CAST(:manifest AS jsonb),'draft'
                    )
                """), {
                    "generated": generated_id, "job": job_id,
                    "document": created["document_id"], "version": created["version_id"],
                    "object": created["object_id"], "format": job["format"],
                    "checksum": checksum, "manifest": json.dumps(manifest),
                })
                await session.execute(text("""
                    UPDATE render_jobs SET state='completed',progress=100,finished_at=now()
                    WHERE render_job_id=:job_id
                """), {"job_id": job_id})
                related_ids = [
                    created["document_id"], created["version_id"], created["object_id"],
                    *list((await session.execute(text("""
                        SELECT rendition_id FROM renditions
                        WHERE version_id=:version_id
                    """), {"version_id": created["version_id"]})).scalars()),
                    *list((await session.execute(text("""
                        SELECT object_id FROM renditions
                        WHERE version_id=:version_id
                        UNION
                        SELECT manifest_object_id FROM renditions
                        WHERE version_id=:version_id AND manifest_object_id IS NOT NULL
                    """), {"version_id": created["version_id"]})).scalars()),
                ]
                await session.execute(text("""
                    UPDATE resources SET lifecycle_state='active',updated_at=now()
                    WHERE resource_id=ANY(:ids) AND lifecycle_state='quarantined'
                """), {"ids": related_ids})
                await session.execute(text("""
                    UPDATE object_blobs SET storage_state='available',verified_at=now()
                    WHERE object_id=ANY(:ids) AND storage_state='staged'
                """), {"ids": related_ids})
                published = await session.execute(text("""
                    UPDATE document_publication_outbox
                    SET state='finalized',payload=payload || jsonb_build_object(
                      'generated_file_id',CAST(:generated AS text),
                      'version_id',CAST(:version AS text),
                      'checksum',CAST(:checksum AS text)
                    ),updated_at=now(),finalized_at=now(),error_code=NULL
                    WHERE render_job_id=:job_id AND state='preparing'
                """), {
                    "generated": str(generated_id),
                    "version": str(created["version_id"]),
                    "checksum": checksum, "job_id": job_id,
                })
                if getattr(published, "rowcount", 0) != 1:
                    raise ValueError("render_failed")
                await AuditRepository().append(
                    session, actor_kind="user",
                    actor_user_id=job["requester_id"],
                    action="document.render", result="success",
                    reason_code="generated_file_published",
                    request_id=str(job["request_id"]),
                    resource_id=created["version_id"],
                    resource_type="document_version",
                    details={"checksum": checksum, "render_job_id": str(job_id)},
                )
        except Exception as error:
            async with self.uow.transaction() as session:
                if created is not None:
                    rendition_ids = list((await session.execute(text("""
                        SELECT rendition_id FROM renditions WHERE version_id=:version_id
                    """), {"version_id": created["version_id"]})).scalars())
                    await session.execute(text("""
                        UPDATE resources SET lifecycle_state='deleted',updated_at=now()
                        WHERE resource_id=ANY(:ids)
                    """), {"ids": [
                        created["document_id"], created["version_id"],
                        created["object_id"], *rendition_ids,
                    ]})
                    cleanup_keys = list((await session.execute(text("""
                        SELECT object_key FROM object_blobs
                        WHERE object_id IN (
                          SELECT object_id FROM document_versions
                          WHERE version_id=:version_id
                          UNION
                          SELECT object_id FROM renditions
                          WHERE version_id=:version_id
                          UNION
                          SELECT manifest_object_id FROM renditions
                          WHERE version_id=:version_id AND manifest_object_id IS NOT NULL
                        )
                    """), {"version_id": created["version_id"]})).scalars())
                await session.execute(text("""
                    UPDATE render_jobs SET state='failed',progress=100,error_code=:code,
                      finished_at=now() WHERE render_job_id=:job_id
                      AND state<>'completed'
                """), {"job_id": job_id, "code": safe_error(error)})
                await session.execute(text("""
                    UPDATE document_publication_outbox
                    SET state='failed',error_code=:code,updated_at=now()
                    WHERE render_job_id=:job_id AND state<>'finalized'
                """), {"job_id": job_id, "code": safe_error(error)})
                await AuditRepository().append(
                    session, actor_kind="service", actor_user_id=None,
                    action="document.render", result="failure",
                    reason_code=safe_error(error), request_id=str(
                        job["request_id"] if job else job_id
                    ),
                    resource_id=job["template_version_id"] if job else None,
                    resource_type="template_version",
                    details={"render_job_id": str(job_id)},
                )
            for object_key in cleanup_keys:
                await self.storage.delete(object_key)

    async def _publication_guard(
        self,
        job: Any,
        fields: Any,
        requester: Subject,
    ) -> None:
        async with self.uow.factory() as session:
            state = (await session.execute(text("""
                SELECT tv.status,t.lifecycle
                FROM template_versions tv
                JOIN templates t ON t.template_id=tv.template_id
                WHERE tv.version_id=:version_id
            """), {"version_id": job["template_version_id"]})).mappings().one_or_none()
            if (
                state is None
                or state["status"] != "approved"
                or state["lifecycle"] != "approved"
            ):
                raise ValueError("template_not_approved")
            principals = await _effective_principal_ids(session, requester)
            effective = await ResourceRepository().effective_policy_attributes(
                session, job["template_version_id"],
                action="render", principal_ids=principals,
            )
            if effective is None or not policy.decide(
                requester, "render", effective[0],
                PolicyContext(request_id=str(job["request_id"])),
            ).allow:
                raise ValueError("fact_policy_denied")
            for field in fields:
                if field["record_version_id"] is None:
                    continue
                current = (await session.execute(text("""
                    SELECT rv.content_sha256,rv.freshness_state
                    FROM records r JOIN record_versions rv
                      ON rv.version_id=r.current_version_id
                    WHERE rv.version_id=:version_id AND rv.lifecycle='active'
                """), {"version_id": field["record_version_id"]})).mappings().one_or_none()
                if (
                    current is None
                    or str(current["content_sha256"]) != str(field["record_checksum"])
                    or current["freshness_state"] != "current"
                ):
                    raise ValueError("fact_stale")

    async def submit(
        self, subject: Subject, generated_id: uuid.UUID, *, request_id: str,
    ) -> None:
        async with self.uow.transaction() as session:
            version_id = await session.scalar(text("""
                UPDATE generated_files g SET lifecycle='in_review'
                FROM render_jobs j WHERE g.generated_file_id=:id
                  AND g.render_job_id=j.render_job_id
                  AND j.requester_id=:actor AND g.lifecycle='draft'
                RETURNING g.version_id
            """), {"id": generated_id, "actor": uuid.UUID(subject.user_id)})
            if version_id is None:
                raise LookupError("not_found")
            await AuditRepository().append(
                session, actor_kind="user",
                actor_user_id=uuid.UUID(subject.user_id),
                action="document.submit", result="success",
                reason_code="review_requested", request_id=request_id,
                resource_id=version_id, resource_type="document_version",
                details={"generated_file_id": str(generated_id)},
            )

    async def decide(
        self,
        subject: Subject,
        generated_id: uuid.UUID,
        decision: str,
        payload: DecisionRequest,
        *,
        request_id: str,
    ) -> None:
        if Role.LEADER not in subject.roles:
            raise PermissionError("reviewer_required")
        actor = uuid.UUID(subject.user_id)
        async with self.uow.transaction() as session:
            row = (await session.execute(text("""
                SELECT g.checksum,g.lifecycle,g.version_id,j.requester_id,t.document_class
                FROM generated_files g JOIN render_jobs j USING(render_job_id)
                JOIN template_versions tv ON tv.version_id=j.template_version_id
                JOIN templates t ON t.template_id=tv.template_id
                WHERE g.generated_file_id=:id FOR UPDATE
            """), {"id": generated_id})).mappings().one_or_none()
            if (
                row is None or row["lifecycle"] != "in_review"
                or (
                    row["document_class"] in {"official", "legal"}
                    and row["requester_id"] == actor
                )
            ):
                raise PermissionError("separation_or_state_denied")
            principals = await _effective_principal_ids(session, subject)
            effective = await ResourceRepository().effective_policy_attributes(
                session, row["version_id"], action="approve", principal_ids=principals,
            )
            if not effective or not policy.decide(
                subject, "approve", effective[0],
                PolicyContext(request_id=request_id),
            ).allow:
                raise PermissionError("reviewer_policy_denied")
            attestation = hash_json({
                "generated_file_id": str(generated_id), "checksum": str(row["checksum"]),
                "reviewer": str(actor), "decision": decision, "reason": payload.reason,
            })
            await session.execute(text("""
                INSERT INTO approvals(
                  approval_id,generated_file_id,stage,reviewer_subject_id,
                  decision,checksum,attestation_hash,reason
                ) VALUES (:approval,:id,'approval',:actor,:decision,:checksum,
                  :attestation,:reason)
            """), {
                "approval": uuid.uuid4(), "id": generated_id, "actor": actor,
                "decision": decision, "checksum": row["checksum"],
                "attestation": attestation, "reason": payload.reason,
            })
            await session.execute(text("""
                UPDATE generated_files SET lifecycle=:state
                WHERE generated_file_id=:id AND checksum=:checksum
            """), {
                "state": "approved" if decision == "approved" else "rejected",
                "id": generated_id, "checksum": row["checksum"],
            })
            await AuditRepository().append(
                session, actor_kind="user", actor_user_id=actor,
                action=f"document.{decision}", result="success",
                reason_code=f"review_{decision}", request_id=request_id,
                resource_id=row["version_id"], resource_type="document_version",
                details={
                    "attestation_hash": attestation,
                    "generated_file_id": str(generated_id),
                },
            )

    async def issue(
        self, subject: Subject, generated_id: uuid.UUID, *, request_id: str,
    ) -> dict[str, Any]:
        if Role.LEADER not in subject.roles:
            raise PermissionError("issuer_required")
        actor = uuid.UUID(subject.user_id)
        async with self.uow.transaction() as session:
            row = (await session.execute(text("""
                SELECT g.checksum,g.lifecycle,g.version_id FROM generated_files g
                JOIN approvals a ON a.generated_file_id=g.generated_file_id
                  AND a.decision='approved' AND a.checksum=g.checksum
                WHERE g.generated_file_id=:id FOR UPDATE
            """), {"id": generated_id})).mappings().one_or_none()
            if row is None or row["lifecycle"] != "approved":
                raise ValueError("approval_required")
            principals = await _effective_principal_ids(session, subject)
            effective = await ResourceRepository().effective_policy_attributes(
                session, row["version_id"], action="approve", principal_ids=principals,
            )
            if not effective or not policy.decide(
                subject, "approve", effective[0],
                PolicyContext(request_id=request_id),
            ).allow:
                raise PermissionError("issuer_policy_denied")
            issue_token = hashlib.sha256(
                f"{generated_id}:{row['checksum']}".encode(),
            ).hexdigest()[:12].upper()
            issue_number = f"RTR-{datetime.now(UTC).year}-{issue_token}"
            issuance_id = uuid.uuid4()
            await session.execute(text("""
                INSERT INTO document_issuances(
                  issuance_id,generated_file_id,issue_number,issuer_subject_id,
                  issued_checksum
                ) VALUES (:issuance,:id,:number,:actor,:checksum)
            """), {
                "issuance": issuance_id, "id": generated_id,
                "number": issue_number, "actor": actor, "checksum": row["checksum"],
            })
            await session.execute(text("""
                UPDATE generated_files SET lifecycle='issued'
                WHERE generated_file_id=:id AND checksum=:checksum
            """), {"id": generated_id, "checksum": row["checksum"]})
            await AuditRepository().append(
                session, actor_kind="user", actor_user_id=actor,
                action="document.issue", result="success",
                reason_code="checksum_issued", request_id=request_id,
                resource_id=row["version_id"], resource_type="document_version",
                details={
                    "issue_number": issue_number,
                    "checksum": str(row["checksum"]),
                    "generated_file_id": str(generated_id),
                },
            )
        return {
            "issuance_id": issuance_id, "issue_number": issue_number,
            "state": "issued", "checksum": str(row["checksum"]),
            "at": datetime.now(UTC),
        }

    async def revoke(
        self,
        subject: Subject,
        generated_id: uuid.UUID,
        payload: DecisionRequest,
        *,
        request_id: str,
    ) -> dict[str, Any]:
        if Role.LEADER not in subject.roles:
            raise PermissionError("issuer_required")
        actor = uuid.UUID(subject.user_id)
        async with self.uow.transaction() as session:
            current = (await session.execute(text("""
                SELECT g.version_id FROM generated_files g
                JOIN document_issuances i USING(generated_file_id)
                WHERE g.generated_file_id=:id AND i.revoked_at IS NULL
            """), {"id": generated_id})).mappings().one_or_none()
            if current is None:
                raise ValueError("not_issued_or_revoked")
            principals = await _effective_principal_ids(session, subject)
            effective = await ResourceRepository().effective_policy_attributes(
                session, current["version_id"], action="approve", principal_ids=principals,
            )
            if not effective or not policy.decide(
                subject, "approve", effective[0],
                PolicyContext(request_id=request_id),
            ).allow:
                raise PermissionError("issuer_policy_denied")
            row = (await session.execute(text("""
                UPDATE document_issuances SET revoked_by=:actor,revoked_at=now(),
                  revocation_reason=:reason
                WHERE generated_file_id=:id AND revoked_at IS NULL
                RETURNING issuance_id,issue_number,issued_checksum,revoked_at
            """), {
                "actor": actor, "reason": payload.reason, "id": generated_id,
            })).mappings().one_or_none()
            if row is None:
                raise ValueError("not_issued_or_revoked")
            await session.execute(text("""
                UPDATE generated_files SET lifecycle='revoked'
                WHERE generated_file_id=:id
            """), {"id": generated_id})
            await AuditRepository().append(
                session, actor_kind="user", actor_user_id=actor,
                action="document.revoke", result="success",
                reason_code="issuance_revoked", request_id=request_id,
                resource_id=current["version_id"], resource_type="document_version",
                details={
                    "issue_number": str(row["issue_number"]),
                    "generated_file_id": str(generated_id),
                },
            )
        return {
            "issuance_id": row["issuance_id"], "issue_number": row["issue_number"],
            "state": "revoked", "checksum": str(row["issued_checksum"]),
            "at": row["revoked_at"],
        }
