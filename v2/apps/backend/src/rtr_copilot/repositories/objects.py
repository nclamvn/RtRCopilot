import hashlib
import re
import uuid
from dataclasses import dataclass
from pathlib import PurePath
from typing import BinaryIO, cast

from sqlalchemy import text

from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.repositories.audit import AuditRepository
from rtr_copilot.repositories.resources import ResourceRecord, ResourceRepository
from rtr_copilot.storage.s3 import S3ObjectStorage, StoredObject


def normalize_filename(value: str) -> str:
    name = PurePath(value.replace("\\", "/")).name
    normalized = re.sub(r"[\x00-\x1f\x7f]+", "", name).strip()
    return normalized[:255] or "unnamed"


@dataclass(frozen=True)
class StagedObject:
    object_id: uuid.UUID
    stored: StoredObject


@dataclass(frozen=True)
class VersionResult:
    version_id: uuid.UUID
    version_no: int
    document_id: uuid.UUID
    object_id: uuid.UUID


@dataclass(frozen=True)
class DownloadCapability:
    resource_id: uuid.UUID
    action: str
    allow: bool
    decision_id: str


class ObjectRepository:
    def __init__(self, storage: S3ObjectStorage, uow: UnitOfWork | None = None) -> None:
        self.storage = storage
        self.uow = uow or UnitOfWork()

    async def create_document(
        self,
        *,
        owner_id: uuid.UUID,
        logical_name: str,
        classification: str = "internal",
        source_zone: str = "private_context",
    ) -> uuid.UUID:
        resource = ResourceRecord(
            resource_type="document",
            owner_subject_id=owner_id,
            classification=classification,  # type: ignore[arg-type]
            source_zone=source_zone,  # type: ignore[arg-type]
            lifecycle_state="active",
        )
        async with self.uow.transaction() as session:
            await ResourceRepository().create(session, resource)
            await session.execute(text("""
                INSERT INTO documents(document_id, logical_name)
                VALUES (:document_id, :logical_name)
            """), {
                "document_id": resource.resource_id,
                "logical_name": logical_name,
            })
        return resource.resource_id

    async def stage_upload(
        self,
        *,
        stream: BinaryIO,
        mime_type: str,
        created_by: uuid.UUID,
        request_id: str,
        declared_sha256: str | None = None,
        classification: str = "internal",
        source_zone: str = "private_context",
    ) -> StagedObject:
        object_id = uuid.uuid4()
        key = f"staging/{object_id}"
        try:
            async with self.uow.transaction() as session:
                stored = await self.storage.upload_stream(
                    key=key,
                    stream=stream,
                    mime_type=mime_type,
                    declared_sha256=declared_sha256,
                )
                await ResourceRepository().create(
                    session,
                    ResourceRecord(
                        resource_id=object_id,
                        resource_type="object",
                        owner_subject_id=created_by,
                        classification=classification,  # type: ignore[arg-type]
                        source_zone=source_zone,  # type: ignore[arg-type]
                        lifecycle_state="draft",
                    ),
                )
                await session.execute(text("""
                    INSERT INTO object_blobs (
                      object_id, bucket, object_key, sha256, byte_size, mime_type,
                      etag, storage_state, created_by
                    ) VALUES (
                      :object_id, :bucket, :object_key, :sha256, :byte_size,
                      :mime_type, :etag, 'staged', :created_by
                    )
                """), {
                    "object_id": object_id,
                    "bucket": stored.bucket,
                    "object_key": stored.key,
                    "sha256": stored.sha256,
                    "byte_size": stored.byte_size,
                    "mime_type": mime_type,
                    "etag": stored.etag,
                    "created_by": created_by,
                })
                await AuditRepository().append(
                    session,
                    actor_kind="user",
                    actor_user_id=created_by,
                    action="object.upload",
                    result="success",
                    reason_code="object_staged",
                    request_id=request_id,
                    resource_id=object_id,
                    resource_type="object",
                    details={"byte_size": stored.byte_size, "sha256": stored.sha256},
                )
        except Exception:
            async with self.uow.transaction() as session:
                await AuditRepository().append(
                    session,
                    actor_kind="user",
                    actor_user_id=created_by,
                    action="object.upload",
                    result="failure",
                    reason_code="storage_upload_failed",
                    request_id=request_id,
                )
            raise
        return StagedObject(object_id=object_id, stored=stored)

    async def activate_version(
        self,
        *,
        document_id: uuid.UUID,
        staged: StagedObject,
        original_filename: str,
        created_by: uuid.UUID,
        request_id: str,
    ) -> VersionResult:
        await self.storage.verify(
            key=staged.stored.key,
            expected_sha256=staged.stored.sha256,
            expected_size=staged.stored.byte_size,
            recompute=True,
        )
        async with self.uow.transaction() as session:
            await session.execute(
                text("SELECT pg_advisory_xact_lock(hashtext(CAST(:id AS text)))"),
                {"id": str(document_id)},
            )
            blob = (await session.execute(text("""
                SELECT sha256, byte_size, mime_type, storage_state
                FROM object_blobs WHERE object_id = :object_id FOR UPDATE
            """), {"object_id": staged.object_id})).mappings().one()
            if (
                blob["storage_state"] != "staged"
                or str(blob["sha256"]) != staged.stored.sha256
                or int(blob["byte_size"]) != staged.stored.byte_size
            ):
                raise ValueError("staged_object_invalid")
            current = (await session.execute(text("""
                SELECT current_version_id FROM documents
                WHERE document_id = :document_id FOR UPDATE
            """), {"document_id": document_id})).scalar_one()
            version_no = int(await session.scalar(text("""
                SELECT COALESCE(MAX(version_no), 0) + 1
                FROM document_versions WHERE document_id = :document_id
            """), {"document_id": document_id}))
            version_id = uuid.uuid4()
            document_resource = (await session.execute(text("""
                SELECT classification, source_zone, owner_subject_id
                FROM resources WHERE resource_id = :document_id
            """), {"document_id": document_id})).mappings().one()
            await ResourceRepository().create(
                session,
                ResourceRecord(
                    resource_id=version_id,
                    resource_type="document_version",
                    owner_subject_id=document_resource["owner_subject_id"],
                    classification=document_resource["classification"],
                    source_zone=document_resource["source_zone"],
                    lifecycle_state="active",
                ),
            )
            await session.execute(text("""
                INSERT INTO document_versions (
                  version_id, document_id, version_no, object_id,
                  original_filename, mime_type, sha256, byte_size, created_by,
                  supersedes_version_id
                ) VALUES (
                  :version_id, :document_id, :version_no, :object_id,
                  :original_filename, :mime_type, :sha256, :byte_size,
                  :created_by, :supersedes
                )
            """), {
                "version_id": version_id,
                "document_id": document_id,
                "version_no": version_no,
                "object_id": staged.object_id,
                "original_filename": normalize_filename(original_filename),
                "mime_type": blob["mime_type"],
                "sha256": staged.stored.sha256,
                "byte_size": staged.stored.byte_size,
                "created_by": created_by,
                "supersedes": current,
            })
            if current:
                await session.execute(text("""
                    UPDATE resources SET lifecycle_state = 'superseded',
                      updated_at = now() WHERE resource_id = :current
                """), {"current": current})
            parameters = {
                "version_id": version_id,
                "document_id": document_id,
                "object_id": staged.object_id,
            }
            await session.execute(text("""
                UPDATE documents SET current_version_id = :version_id,
                  updated_at = now() WHERE document_id = :document_id
            """), parameters)
            await session.execute(text("""
                UPDATE object_blobs SET storage_state = 'available',
                  verified_at = now() WHERE object_id = :object_id
            """), parameters)
            await session.execute(text("""
                UPDATE resources SET lifecycle_state = 'active', updated_at = now()
                  WHERE resource_id = :object_id
            """), parameters)
            await AuditRepository().append(
                session,
                actor_kind="user",
                actor_user_id=created_by,
                action="document.version.activate",
                result="success",
                reason_code="version_activated",
                request_id=request_id,
                resource_id=version_id,
                resource_type="document_version",
                details={
                    "document_id": str(document_id),
                    "version_no": version_no,
                    "sha256": staged.stored.sha256,
                },
            )
        return VersionResult(
            version_id=version_id,
            version_no=version_no,
            document_id=document_id,
            object_id=staged.object_id,
        )

    async def presign_download(
        self,
        *,
        object_key: str,
        capability: DownloadCapability,
        expires_seconds: int = 300,
    ) -> str:
        if not capability.allow or capability.action != "download":
            raise PermissionError("download_capability_required")
        return cast(str, await __import__("asyncio").to_thread(
            self.storage.client.generate_presigned_url,
            "get_object",
            Params={"Bucket": self.storage.bucket, "Key": object_key},
            ExpiresIn=expires_seconds,
        ))

    async def reconcile(self) -> dict[str, list[str]]:
        inventory = await self.storage.inventory()
        async with self.uow.factory() as session:
            rows = (await session.execute(text("""
                SELECT object_key, storage_state FROM object_blobs
            """))).mappings()
            database = {str(row["object_key"]): str(row["storage_state"]) for row in rows}
        storage_keys = {str(item["key"]) for item in inventory}
        expected_keys = {
            key for key, state in database.items() if state == "available"
        }
        return {
            "storage_orphans": sorted(storage_keys - database.keys()),
            # A staged upload may not have reached object storage yet, while
            # missing/deleted are explicit terminal metadata states. Only an
            # AVAILABLE object absent from the bucket violates the contract.
            "database_missing": sorted(expected_keys - storage_keys),
            "staged": sorted(key for key, state in database.items() if state == "staged"),
        }

    async def reconcile_mark_missing(
        self,
        *,
        request_id: str,
        explicit: bool,
    ) -> dict[str, int | str]:
        """Quarantine AVAILABLE database objects absent from object storage.

        This is intentionally a maintenance-only, fail-closed repair. It does
        not delete metadata, immutable answer history or citations. The state
        transition hides unavailable content from retrieval/download while
        preserving enough lineage for a later, audited object recovery.
        """
        if not explicit:
            raise PermissionError("explicit_mark_missing_flag_required")
        inventory = await self.storage.inventory()
        storage_keys = {str(item["key"]) for item in inventory}
        async with self.uow.factory() as session, session.begin():
            await session.execute(text("SELECT pg_advisory_xact_lock(827005)"))
            maintenance = await session.scalar(text(
                "SELECT enabled FROM maintenance_state WHERE singleton",
            ))
            if not maintenance:
                raise PermissionError("maintenance_mode_required")
            rows = (await session.execute(text("""
                SELECT object_id,object_key FROM object_blobs
                WHERE storage_state='available'
                ORDER BY object_id FOR UPDATE
            """))).mappings().all()
            missing = [
                row for row in rows if str(row["object_key"]) not in storage_keys
            ]
            missing_ids = [row["object_id"] for row in missing]
            key_digest = hashlib.sha256(
                "\n".join(sorted(str(row["object_key"]) for row in missing)).encode()
            ).hexdigest()
            if missing_ids:
                await session.execute(text("""
                    UPDATE object_blobs
                    SET storage_state='missing',verified_at=now()
                    WHERE object_id=ANY(:ids) AND storage_state='available'
                """), {"ids": missing_ids})
                await session.execute(text("""
                    UPDATE resources SET lifecycle_state='quarantined',updated_at=now()
                    WHERE resource_id=ANY(:ids)
                """), {"ids": missing_ids})
                rendition_ids = list((await session.execute(text("""
                    UPDATE renditions
                    SET status='failed',error_code='object_missing',updated_at=now()
                    WHERE object_id=ANY(:ids) OR manifest_object_id=ANY(:ids)
                    RETURNING rendition_id
                """), {"ids": missing_ids})).scalars())
                version_ids = list((await session.execute(text("""
                    SELECT version_id FROM document_versions
                    WHERE object_id=ANY(:ids)
                """), {"ids": missing_ids})).scalars())
                affected_resource_ids = [*rendition_ids, *version_ids]
                if affected_resource_ids:
                    await session.execute(text("""
                        UPDATE resources
                        SET lifecycle_state='quarantined',updated_at=now()
                        WHERE resource_id=ANY(:ids)
                    """), {"ids": affected_resource_ids})
                document_ids = list((await session.execute(text("""
                    SELECT document_id FROM documents
                    WHERE current_version_id=ANY(:version_ids)
                """), {"version_ids": version_ids})).scalars()) if version_ids else []
                if document_ids:
                    await session.execute(text("""
                        UPDATE resources
                        SET lifecycle_state='quarantined',updated_at=now()
                        WHERE resource_id=ANY(:ids)
                    """), {"ids": document_ids})
                await AuditRepository().append(
                    session,
                    actor_kind="service",
                    actor_user_id=None,
                    action="object.reconcile.mark_missing",
                    result="success",
                    reason_code="available_object_absent_from_storage",
                    request_id=request_id,
                    details={
                        "object_count": len(missing_ids),
                        "object_key_set_sha256": key_digest,
                        "rendition_count": len(rendition_ids),
                        "document_version_count": len(version_ids),
                        "document_count": len(document_ids),
                    },
                )
            return {
                "object_count": len(missing_ids),
                "object_key_set_sha256": key_digest,
                "rendition_count": len(rendition_ids) if missing_ids else 0,
                "document_version_count": len(version_ids) if missing_ids else 0,
                "document_count": len(document_ids) if missing_ids else 0,
            }

    async def reconcile_delete(
        self,
        key: str,
        *,
        actor_id: uuid.UUID,
        request_id: str,
        explicit: bool,
    ) -> None:
        if not explicit:
            raise PermissionError("explicit_repair_flag_required")
        intent_id = uuid.uuid4()
        key_hash = __import__("hashlib").sha256(key.encode()).hexdigest()
        async with self.uow.transaction() as session:
            await session.execute(text("""
                INSERT INTO object_reconciliation_intents(
                  intent_id, object_key, operation, state, requested_by, request_id
                ) VALUES (
                  :intent_id, :object_key, 'delete', 'pending', :actor_id, :request_id
                )
            """), {
                "intent_id": intent_id,
                "object_key": key,
                "actor_id": actor_id,
                "request_id": request_id,
            })
            await AuditRepository().append(
                session,
                actor_kind="user",
                actor_user_id=actor_id,
                action="object.reconcile.delete.intent",
                result="success",
                reason_code="delete_intent_committed",
                request_id=request_id,
                details={"intent_id": str(intent_id), "object_key_hash": key_hash},
            )
        try:
            async with self.uow.transaction() as session:
                await self.storage.delete(key)
                await session.execute(text("""
                    UPDATE object_reconciliation_intents
                    SET state='completed', completed_at=now()
                    WHERE intent_id=:intent_id AND state='pending'
                """), {"intent_id": intent_id})
                await AuditRepository().append(
                    session,
                    actor_kind="user",
                    actor_user_id=actor_id,
                    action="object.reconcile.delete.complete",
                    result="success",
                    reason_code="orphan_deleted",
                    request_id=request_id,
                    details={"intent_id": str(intent_id), "object_key_hash": key_hash},
                )
        except Exception:
            async with self.uow.transaction() as session:
                await session.execute(text("""
                    UPDATE object_reconciliation_intents
                    SET state='failed', error_code='external_delete_failed',
                      completed_at=now()
                    WHERE intent_id=:intent_id AND state='pending'
                """), {"intent_id": intent_id})
                await AuditRepository().append(
                    session,
                    actor_kind="user",
                    actor_user_id=actor_id,
                    action="object.reconcile.delete.complete",
                    result="failure",
                    reason_code="external_delete_failed",
                    request_id=request_id,
                    details={"intent_id": str(intent_id), "object_key_hash": key_hash},
                )
            raise
