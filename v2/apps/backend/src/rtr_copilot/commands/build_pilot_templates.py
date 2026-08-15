"""Build deterministic TIP-024 Document OS payloads from canonical templates."""

from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from pathlib import Path

from sqlalchemy import text

from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.documents.renderers import canonical_json
from rtr_copilot.documents.service import DocumentOSService
from rtr_copilot.pilot.template_adapter import adapt_templates, write_template_staging
from rtr_copilot.repositories.audit import AuditRepository

INTERNAL_TEMPLATE_ROLE_KEYS = ("staff", "leader", "curator", "admin")
INTERNAL_TEMPLATE_ACTIONS = ("view", "render")


async def _grant_internal_access(
    version_id: uuid.UUID,
    curator_id: uuid.UUID,
) -> int:
    """Make an approved pilot template usable by authenticated company roles.

    Template source packages remain private-context resources.  A role-bound
    ACL is therefore required in addition to the ``internal`` classification;
    without it, lifecycle reports can count an approved template while staff
    correctly see an empty registry.  Deterministic ACL identifiers make this
    bootstrap safe to repeat.
    """

    inserted_count = 0
    async with UnitOfWork().transaction() as session:
        roles = (await session.execute(text("""
            SELECT role_id,key FROM roles
            WHERE key=ANY(CAST(:role_keys AS text[])) AND status='active'
        """), {"role_keys": list(INTERNAL_TEMPLATE_ROLE_KEYS)})).mappings().all()
        if len(roles) != len(INTERNAL_TEMPLATE_ROLE_KEYS):
            raise ValueError("pilot_template_role_registry_incomplete")
        for role in roles:
            for action in INTERNAL_TEMPLATE_ACTIONS:
                acl_id = uuid.uuid5(
                    uuid.NAMESPACE_URL,
                    (
                        f"rtr:tip024:template:{version_id}:"
                        f"role:{role['key']}:{action}"
                    ),
                )
                inserted = await session.scalar(text("""
                    INSERT INTO acl_entries(
                      acl_id,resource_id,principal_type,principal_id,action,
                      effect,conditions,granted_by,reason
                    ) VALUES (
                      :acl_id,:version_id,'role',:role_id,:action,'allow',
                      '{}'::jsonb,:curator_id,
                      'TIP-024 approved internal pilot template'
                    ) ON CONFLICT (acl_id) DO NOTHING
                    RETURNING 1
                """), {
                    "acl_id": acl_id,
                    "version_id": version_id,
                    "role_id": role["role_id"],
                    "action": action,
                    "curator_id": curator_id,
                })
                inserted_count += int(inserted or 0)
        if inserted_count:
            await AuditRepository().append(
                session,
                actor_kind="user",
                actor_user_id=curator_id,
                action="template.internal_access.grant",
                result="success",
                reason_code="approved_internal_pilot_roles",
                request_id=f"tip024-template:{version_id}:internal-access",
                resource_id=version_id,
                resource_type="template_version",
                details={
                    "role_keys": list(INTERNAL_TEMPLATE_ROLE_KEYS),
                    "actions": list(INTERNAL_TEMPLATE_ACTIONS),
                    "grant_count": inserted_count,
                },
            )
    return inserted_count


async def _activate(result: object, curator_id: uuid.UUID) -> list[dict[str, str]]:
    settings = get_settings()
    if settings.app_env == "production":
        raise RuntimeError("pilot_activation_local_only")
    subject = Subject(
        user_id=str(curator_id), issuer="tip024-local", sub=curator_id.hex,
        email=f"{curator_id.hex}@rtrobotics.com", canonical_domain="rtrobotics.com",
        display_name="TIP-024 local curator", roles={Role.CURATOR},
    )
    service = DocumentOSService()
    uow = UnitOfWork()
    outcomes: list[dict[str, str]] = []
    for item in result.templates:  # type: ignore[attr-defined]
        schema_json = canonical_json(
            item.payload.field_schema.model_dump(mode="json"),
        ).decode("utf-8")
        async with uow.factory() as session:
            existing = (await session.execute(text("""
                SELECT tv.version_id,tv.status,tv.source_sha256,tv.field_schema
                FROM templates t JOIN template_versions tv
                  ON tv.template_id=t.template_id
                WHERE t.stable_key=:stable_key
                ORDER BY tv.version_ordinal DESC LIMIT 1
            """), {"stable_key": item.payload.stable_key})).mappings().one_or_none()
        detail = None
        if existing is not None and (
            str(existing["source_sha256"]) == item.adapted_sha256
            and canonical_json(existing["field_schema"]).decode("utf-8") == schema_json
        ):
            version_id = existing["version_id"]
            state = str(existing["status"])
        else:
            detail = await service.import_template(
                subject, item.payload,
                request_id=f"tip024-template:{item.template_id}:import",
            )
            version_id = detail.version_id
            state = detail.status
        if state == "draft":
            await service.lifecycle(
                subject, version_id, "submit",
                request_id=f"tip024-template:{item.template_id}:submit",
            )
            state = "in_review"
        if state == "in_review":
            await service.lifecycle(
                subject, version_id, "approve",
                request_id=f"tip024-template:{item.template_id}:approve",
            )
            state = "approved"
        grant_count = await _grant_internal_access(
            uuid.UUID(str(version_id)), curator_id,
        )
        outcomes.append({
            "template_id": item.template_id,
            "version_id": str(version_id),
            "state": state,
            "result": "imported" if detail is not None else "idempotent",
            "acl_grants": str(grant_count),
        })
    return outcomes


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--template-root", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--curator-id", type=uuid.UUID)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--approve", action="store_true")
    args = parser.parse_args()
    if args.apply and (not args.approve or args.curator_id is None):
        parser.error("--apply requires --approve and --curator-id")
    result = adapt_templates(args.template_root)
    write_template_staging(result, args.out)
    activation = (
        asyncio.run(_activate(result, args.curator_id)) if args.apply else []
    )
    print(json.dumps({
        "registry_sha256": result.registry_sha256,
        "template_count": len(result.templates),
        "templates": [
            {
                "template_id": item.template_id,
                "source_sha256": item.source_sha256,
                "adapted_sha256": item.adapted_sha256,
                "fingerprint": item.fingerprint,
            }
            for item in result.templates
        ],
        "activation": activation,
        "production_boundary": "local_dev_only",
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
