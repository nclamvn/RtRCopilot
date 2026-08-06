"""Promote checksum-bound company files into the enterprise Ask corpus.

The file ingestion plane intentionally defaults to private, per-file retrieval.
This module adds a second, explicit gate: only a fully verified manifest may
mark its source as searchable by the company-wide Ask experience. Content is
not copied and ACL enforcement remains on the original resource lineage.
"""

from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import text

from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.pilot.file_campaign import (
    PilotFileManifest,
    PlannedFile,
    load_file_manifest,
    manifest_fingerprint,
    plan_files,
)
from rtr_copilot.repositories.audit import AuditRepository

ASK_SCOPE = "enterprise_approved"
ROLE_ALLOWLIST: dict[str, tuple[str, ...]] = {
    "public_internal": ("staff", "leader", "curator", "admin"),
    "internal": ("staff", "leader", "curator", "admin"),
    # Restricted material remains outside ordinary staff scope.
    "restricted": ("leader", "curator"),
    "highly_restricted": (),
}


@dataclass(frozen=True)
class CompanyCorpusActivation:
    manifest_fingerprint: str
    verified_files: int
    searchable_files: int
    source_count: int
    granted_acl_count: int
    excluded_highly_restricted: int

    def to_dict(self) -> dict[str, object]:
        return {
            "manifest_fingerprint": self.manifest_fingerprint,
            "verified_files": self.verified_files,
            "searchable_files": self.searchable_files,
            "source_count": self.source_count,
            "granted_acl_count": self.granted_acl_count,
            "excluded_highly_restricted": self.excluded_highly_restricted,
        }


class CompanyCorpusActivator:
    def __init__(self, uow: UnitOfWork | None = None) -> None:
        self.uow = uow or UnitOfWork()

    async def activate(
        self,
        manifest: PilotFileManifest,
        *,
        knowledge_root: Path,
        approved_by: uuid.UUID,
        request_id: str,
    ) -> CompanyCorpusActivation:
        """Verify every member, then atomically enable approved sources."""

        if get_settings().app_env == "production":
            raise RuntimeError("company_corpus_activation_local_only")
        planned = plan_files(manifest, knowledge_root)
        fingerprint = manifest_fingerprint(manifest)
        return await self.activate_planned(
            planned,
            fingerprint=fingerprint,
            logical_prefix="tip024",
            approved_by=approved_by,
            request_id=request_id,
        )

    async def activate_planned(
        self,
        planned: list[PlannedFile],
        *,
        fingerprint: str,
        logical_prefix: str,
        approved_by: uuid.UUID,
        request_id: str,
    ) -> CompanyCorpusActivation:
        """Activate a validated campaign without weakening the common gate."""

        if get_settings().app_env == "production":
            raise RuntimeError("company_corpus_activation_local_only")
        expected = {item.entry.manifest_key: item for item in planned}
        source_ids: set[uuid.UUID] = set()
        searchable = 0
        excluded = 0
        grants = 0

        async with self.uow.transaction() as session:
            approver_exists = await session.scalar(text("""
                SELECT 1 FROM subjects WHERE user_id=:approved_by AND status='active'
            """), {"approved_by": approved_by})
            if approver_exists is None:
                raise ValueError("company_corpus_approver_unknown")

            rows = (await session.execute(text("""
                SELECT d.logical_name,d.source_id,dv.version_id,dv.sha256,
                  dv.viewer_state,r.classification,r.source_zone,r.lifecycle_state,
                  count(fc.file_chunk_id)::int AS chunk_count
                FROM documents d
                JOIN document_versions dv ON dv.version_id=d.current_version_id
                JOIN resources r ON r.resource_id=dv.version_id
                LEFT JOIN file_chunks fc ON fc.document_version_id=dv.version_id
                  AND fc.lifecycle='active'
                WHERE d.logical_name=ANY(CAST(:logical_names AS text[]))
                GROUP BY d.logical_name,d.source_id,dv.version_id,dv.sha256,
                  dv.viewer_state,r.classification,r.source_zone,r.lifecycle_state
            """), {
                "logical_names": [f"{logical_prefix}.{key}" for key in expected],
            })).mappings().all()
            by_key = {
                str(row["logical_name"]).removeprefix(f"{logical_prefix}."): dict(row)
                for row in rows
            }
            errors: list[str] = []
            for key, item in expected.items():
                row = by_key.get(key)
                if row is None:
                    errors.append(f"missing:{key}")
                    continue
                entry = item.entry
                if str(row["sha256"]) != entry.sha256:
                    errors.append(f"checksum:{key}")
                if row["viewer_state"] != "ready" or row["lifecycle_state"] != "active":
                    errors.append(f"inactive:{key}")
                if row["classification"] != entry.classification:
                    errors.append(f"classification:{key}")
                if row["source_zone"] != entry.source_zone:
                    errors.append(f"zone:{key}")
                if row["source_id"] is None:
                    errors.append(f"source:{key}")
                elif not entry.mime_type.startswith("image/") and int(
                    row["chunk_count"] or 0
                ) == 0:
                    errors.append(f"unindexed:{key}")
            if errors:
                raise ValueError("company_corpus_manifest_invalid:" + ",".join(errors))

            classifications_by_source: dict[uuid.UUID, str] = {}
            for key, item in expected.items():
                source_id = uuid.UUID(str(by_key[key]["source_id"]))
                source_ids.add(source_id)
                classifications_by_source[source_id] = item.entry.classification
                if item.entry.classification == "highly_restricted":
                    excluded += 1
                else:
                    searchable += 1

            for source_id in sorted(source_ids, key=str):
                classification = classifications_by_source[source_id]
                await session.execute(text("""
                    UPDATE sources
                    SET metadata = coalesce(metadata,'{}'::jsonb) || CAST(:approval AS jsonb)
                    WHERE source_id=:source_id
                """), {
                    "source_id": source_id,
                    "approval": json.dumps({
                        "enterprise_ask": {
                            "state": ASK_SCOPE,
                            "manifest_fingerprint": fingerprint,
                            "approved_by": str(approved_by),
                            "contract": "company-file-manifest-v1",
                        },
                    }),
                })
                role_keys = ROLE_ALLOWLIST[classification]
                role_rows = (await session.execute(text("""
                    SELECT role_id,key FROM roles
                    WHERE key=ANY(CAST(:role_keys AS text[])) AND status='active'
                """), {"role_keys": list(role_keys)})).mappings().all()
                if len(role_rows) != len(role_keys):
                    raise ValueError("company_corpus_role_registry_incomplete")
                for role in role_rows:
                    acl_id = uuid.uuid5(
                        uuid.NAMESPACE_URL,
                        f"rtr:enterprise-ask:{source_id}:role:{role['key']}:view",
                    )
                    inserted = await session.scalar(text("""
                        INSERT INTO acl_entries(
                          acl_id,resource_id,principal_type,principal_id,action,
                          effect,conditions,granted_by,reason
                        ) VALUES (
                          :acl_id,:source_id,'role',:role_id,'view','allow',
                          '{}'::jsonb,:approved_by,:reason
                        ) ON CONFLICT (acl_id) DO NOTHING
                        RETURNING 1
                    """), {
                        "acl_id": acl_id,
                        "source_id": source_id,
                        "role_id": role["role_id"],
                        "approved_by": approved_by,
                        "reason": f"Enterprise Ask manifest {fingerprint[:16]}",
                    })
                    grants += int(inserted or 0)
                await AuditRepository().append(
                    session,
                    actor_kind="user",
                    actor_user_id=approved_by,
                    action="enterprise.company_corpus.activate",
                    result="success",
                    reason_code="checksum_bound_manifest_approved",
                    request_id=request_id,
                    resource_id=source_id,
                    resource_type="source",
                    details={
                        "manifest_fingerprint": fingerprint,
                        "classification": classification,
                        "role_count": len(role_keys),
                    },
                )

        return CompanyCorpusActivation(
            manifest_fingerprint=fingerprint,
            verified_files=len(expected),
            searchable_files=searchable,
            source_count=len(source_ids),
            granted_acl_count=grants,
            excluded_highly_restricted=excluded,
        )


async def activate_manifest(
    manifest_path: Path,
    knowledge_root: Path,
    approved_by: uuid.UUID,
    *,
    request_id: str = "tip027-company-corpus",
) -> CompanyCorpusActivation:
    return await CompanyCorpusActivator().activate(
        load_file_manifest(manifest_path),
        knowledge_root=knowledge_root,
        approved_by=approved_by,
        request_id=request_id,
    )


__all__ = [
    "ASK_SCOPE",
    "CompanyCorpusActivation",
    "CompanyCorpusActivator",
    "activate_manifest",
]
