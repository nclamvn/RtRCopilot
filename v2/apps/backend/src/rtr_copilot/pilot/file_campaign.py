"""Manifest-bound local file campaign using the existing ingestion pipeline."""

from __future__ import annotations

import asyncio
import hashlib
import json
import uuid
from collections.abc import AsyncIterator
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

from pydantic import Field, model_validator
from sqlalchemy import text

from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.governance.models import StrictModel
from rtr_copilot.ingestion.service import IngestionService
from rtr_copilot.repositories.audit import AuditRepository
from rtr_copilot.repositories.resources import ResourceRecord, ResourceRepository

PilotMime = Literal[
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "image/png",
    "image/jpeg",
    "image/webp",
]
MIME_FAMILY: dict[str, str] = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet": "xlsx",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation": "pptx",
    "image/png": "image",
    "image/jpeg": "image",
    "image/webp": "image",
}
REQUIRED_FAMILIES = {"pdf", "docx", "xlsx", "pptx", "image"}


class PilotFileEntry(StrictModel):
    manifest_key: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{2,127}$")
    path: str = Field(min_length=1, max_length=1_000)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    mime_type: PilotMime
    classification: Literal[
        "public_internal", "internal", "restricted", "highly_restricted",
    ]
    source_zone: Literal["private_context"] = "private_context"
    owner_subject_id: uuid.UUID

    @model_validator(mode="after")
    def relative_path_only(self) -> PilotFileEntry:
        path = PurePosixPath(self.path)
        if path.is_absolute() or ".." in path.parts or "." in path.parts:
            raise ValueError("pilot_file_path_invalid")
        return self


class PilotFileManifest(StrictModel):
    schema_version: Literal[1] = 1
    campaign: Literal["TIP-024"] = "TIP-024"
    root_label: Literal["KnowledgeBase"] = "KnowledgeBase"
    entries: list[PilotFileEntry] = Field(min_length=30, max_length=30)

    @model_validator(mode="after")
    def unique_and_representative(self) -> PilotFileManifest:
        keys = [entry.manifest_key for entry in self.entries]
        paths = [entry.path for entry in self.entries]
        if len(keys) != len(set(keys)) or len(paths) != len(set(paths)):
            raise ValueError("pilot_file_manifest_duplicate")
        families = {MIME_FAMILY[entry.mime_type] for entry in self.entries}
        if not REQUIRED_FAMILIES.issubset(families):
            raise ValueError("pilot_file_families_incomplete")
        return self


@dataclass(frozen=True)
class PlannedFile:
    entry: PilotFileEntry
    resolved_path: Path
    byte_size: int


def load_file_manifest(path: Path) -> PilotFileManifest:
    try:
        import yaml  # type: ignore[import-untyped]
    except ImportError as error:  # pragma: no cover
        raise RuntimeError("yaml_dependency_unavailable") from error
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    return PilotFileManifest.model_validate(payload)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def plan_files(manifest: PilotFileManifest, knowledge_root: Path) -> list[PlannedFile]:
    root = knowledge_root.resolve(strict=True)
    if not root.is_dir():
        raise ValueError("pilot_file_root_invalid")
    settings = get_settings()
    planned: list[PlannedFile] = []
    for entry in manifest.entries:
        candidate = root.joinpath(*PurePosixPath(entry.path).parts)
        if candidate.is_symlink():
            raise ValueError(f"pilot_file_symlink:{entry.manifest_key}")
        resolved = candidate.resolve(strict=True)
        try:
            resolved.relative_to(root)
        except ValueError as error:
            raise ValueError(f"pilot_file_path_escape:{entry.manifest_key}") from error
        if not resolved.is_file():
            raise ValueError(f"pilot_file_not_regular:{entry.manifest_key}")
        byte_size = resolved.stat().st_size
        if byte_size < 1_024 or byte_size > settings.ingestion_max_upload_bytes:
            raise ValueError(f"pilot_file_size_invalid:{entry.manifest_key}")
        if _sha256(resolved) != entry.sha256:
            raise ValueError(f"pilot_file_checksum_drift:{entry.manifest_key}")
        planned.append(PlannedFile(entry, resolved, byte_size))
    return planned


def manifest_fingerprint(manifest: PilotFileManifest) -> str:
    payload = json.dumps(
        manifest.model_dump(mode="json"), ensure_ascii=False,
        separators=(",", ":"), sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


async def _file_stream(path: Path) -> AsyncIterator[bytes]:
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            yield chunk


class PilotFileCampaign:
    def __init__(self, uow: UnitOfWork | None = None) -> None:
        self.uow = uow or UnitOfWork()
        self.service = IngestionService(uow=self.uow)

    @staticmethod
    def _source_id(classification: str, owner_id: uuid.UUID) -> uuid.UUID:
        return uuid.uuid5(
            uuid.NAMESPACE_URL,
            f"rtr:tip024:file-source:{classification}:{owner_id}",
        )

    async def _ensure_source(self, entry: PilotFileEntry) -> ResourceRecord:
        source_id = self._source_id(entry.classification, entry.owner_subject_id)
        async with self.uow.transaction() as session:
            subject_exists = await session.scalar(text(
                "SELECT 1 FROM subjects WHERE user_id=:owner",
            ), {"owner": entry.owner_subject_id})
            if subject_exists is None:
                raise ValueError("pilot_file_owner_unknown")
            resource = await ResourceRepository().get(session, source_id)
            if resource is None:
                resource = ResourceRecord(
                    resource_id=source_id,
                    resource_type="source",
                    owner_subject_id=entry.owner_subject_id,
                    classification=entry.classification,
                    source_zone="private_context",
                    lifecycle_state="active",
                )
                await ResourceRepository().create(session, resource)
                await session.execute(text("""
                    INSERT INTO sources(source_id,kind,name,metadata)
                    VALUES (:source_id,'internal',:name,CAST(:metadata AS jsonb))
                """), {
                    "source_id": source_id,
                    "name": f"TIP-024 Pilot Corpus · {entry.classification}",
                    "metadata": json.dumps({
                        "campaign": "TIP-024",
                        "production_boundary": "local_dev_only",
                    }),
                })
                await AuditRepository().append(
                    session,
                    actor_kind="user",
                    actor_user_id=entry.owner_subject_id,
                    action="pilot.file_source.create",
                    result="success",
                    reason_code="tip024_local_source_registered",
                    request_id=f"tip024-source:{source_id}",
                    resource_id=source_id,
                    resource_type="source",
                    details={"classification": entry.classification},
                )
            elif (
                resource.owner_subject_id != entry.owner_subject_id
                or resource.classification != entry.classification
                or resource.source_zone != "private_context"
                or resource.lifecycle_state != "active"
            ):
                raise ValueError("pilot_file_source_drift")
        return resource

    async def _existing_ready(
        self,
        source_id: uuid.UUID,
        item: PlannedFile,
    ) -> uuid.UUID | None:
        async with self.uow.factory() as session:
            version_id = await session.scalar(text("""
                SELECT dv.version_id
                FROM documents d JOIN document_versions dv
                  ON dv.document_id=d.document_id
                JOIN resources r ON r.resource_id=dv.version_id
                WHERE d.source_id=:source_id AND d.logical_name=:logical_name
                  AND dv.sha256=:sha256 AND dv.viewer_state='ready'
                  AND r.lifecycle_state='active'
                ORDER BY dv.created_at DESC LIMIT 1
            """), {
                "source_id": source_id,
                "logical_name": f"tip024.{item.entry.manifest_key}",
                "sha256": item.entry.sha256,
            })
        return uuid.UUID(str(version_id)) if version_id is not None else None

    async def _resume_upload(
        self,
        request_id: str,
    ) -> tuple[uuid.UUID, uuid.UUID] | None:
        async with self.uow.factory() as session:
            row = (await session.execute(text("""
                SELECT upload_id,validation_job_id,state FROM upload_sessions
                WHERE request_id=:request_id ORDER BY created_at DESC LIMIT 1
            """), {"request_id": request_id})).one_or_none()
        if row is None or row[2] not in {"quarantined", "accepted"}:
            return None
        return row[0], row[1]

    async def _drain(self, upload_id: uuid.UUID) -> uuid.UUID:
        # A normal local stack may have the worker running concurrently. Give
        # leased work and bounded retry backoff enough time to settle instead
        # of treating a healthy worker race as an incomplete campaign.
        for attempt in range(240):
            async with self.uow.factory() as session:
                upload = (await session.execute(text("""
                    SELECT state,error_code,version_id FROM upload_sessions
                    WHERE upload_id=:upload_id
                """), {"upload_id": upload_id})).mappings().one()
                jobs = (await session.execute(text("""
                    SELECT job_id,status,error_code,next_attempt_at
                    FROM ingestion_jobs
                    WHERE upload_id=:upload_id
                       OR version_id=:version_id
                    ORDER BY CASE job_type WHEN 'validate' THEN 0 ELSE 1 END,created_at
                """), {
                    "upload_id": upload_id,
                    "version_id": upload["version_id"],
                })).mappings().all()
            if upload["state"] in {"rejected", "failed"}:
                raise RuntimeError(
                    f"pilot_file_ingestion_failed:{upload['error_code'] or 'unknown'}",
                )
            failed = next(
                (job for job in jobs if job["status"] in {"failed", "quarantined"}),
                None,
            )
            if failed is not None:
                raise RuntimeError(
                    f"pilot_file_job_failed:{failed['error_code'] or 'unknown'}",
                )
            pending = next(
                (job for job in jobs if job["status"] not in {"succeeded", "cancelled"}),
                None,
            )
            if pending is not None:
                processed = await self.service.process_job(
                    pending["job_id"], worker_id=f"tip024-local-{attempt}",
                )
                if not processed:
                    await asyncio.sleep(0.5)
                continue
            if upload["version_id"] is not None:
                async with self.uow.factory() as session:
                    ready = await session.scalar(text("""
                        SELECT viewer_state FROM document_versions
                        WHERE version_id=:version_id
                    """), {"version_id": upload["version_id"]})
                if ready == "ready":
                    return uuid.UUID(str(upload["version_id"]))
            if attempt == 239:
                break
            await asyncio.sleep(0.25)
        raise RuntimeError("pilot_file_ingestion_incomplete")

    async def apply(self, planned: list[PlannedFile]) -> list[dict[str, object]]:
        if get_settings().app_env == "production":
            raise RuntimeError("pilot_activation_local_only")
        outcomes: list[dict[str, object]] = []
        for item in planned:
            parent = await self._ensure_source(item.entry)
            ready = await self._existing_ready(parent.resource_id, item)
            if ready is not None:
                outcomes.append({
                    "manifest_key": item.entry.manifest_key,
                    "version_id": str(ready),
                    "state": "ready",
                    "result": "idempotent",
                })
                continue
            request_id = f"tip024-file:{item.entry.manifest_key}:{item.entry.sha256[:12]}"
            resumed = await self._resume_upload(request_id)
            if resumed is None:
                upload_id, _ = await self.service.receive(
                    _file_stream(item.resolved_path),
                    content_length=item.byte_size,
                    parent=parent,
                    logical_name=f"tip024.{item.entry.manifest_key}",
                    original_filename=item.resolved_path.name,
                    declared_mime=item.entry.mime_type,
                    declared_sha256=item.entry.sha256,
                    requested_by=item.entry.owner_subject_id,
                    request_id=request_id,
                )
            else:
                upload_id, _ = resumed
            version_id = await self._drain(upload_id)
            outcomes.append({
                "manifest_key": item.entry.manifest_key,
                "version_id": str(version_id),
                "state": "ready",
                "result": "ingested",
            })
        return outcomes


__all__ = [
    "PilotFileCampaign", "PilotFileEntry", "PilotFileManifest", "PlannedFile",
    "load_file_manifest", "manifest_fingerprint", "plan_files",
]
