"""Action input fences, followed by fresh metadata (never lock-query authority)."""

import json
import uuid
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from rtr_copilot.actions.authority import LeafCheckpoint, LeafRequest, lock_subjects
from rtr_copilot.actions.models import PlanPayload
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.auth.models import PolicyContext
from rtr_copilot.auth.policy import PolicyEngine
from rtr_copilot.rag.use_class import blocks


async def lock_inputs(
    session: AsyncSession, payload: PlanPayload, actors: tuple[uuid.UUID, ...],
    *, sources_only: bool = False,
) -> None:
    # Outer run/job/idempotency locks belong to the caller. Multi-actor locks
    # always precede source locks, avoiding actor/reviewer lock inversion.
    await lock_subjects(session, actors)
    if not sources_only:
        for capability_id, version in sorted({(s.capability_id, s.capability_version)
                                               for s in payload.steps}):
            await session.execute(text("""
                SELECT capability_id FROM capability_versions
                WHERE capability_id=:id AND version=:version FOR SHARE
            """), {"id": capability_id, "version": version})
        templates = {r.resource_id for s in payload.steps for r in s.resources
                     if r.resource_type == "template_version"}
        for version_id in sorted(templates, key=str):
            await session.execute(text("""
                SELECT tv.version_id FROM template_versions tv JOIN templates t USING(template_id)
                WHERE tv.version_id=:id FOR SHARE OF tv,t
            """), {"id": version_id})
    for version_id in sorted({r.record_version_id for r in payload.source_refs}, key=str):
        await session.execute(text("""
            SELECT rv.version_id FROM record_versions rv
            JOIN records r ON r.record_id=rv.record_id
            JOIN sot_packages p ON p.package_id=rv.package_id
            WHERE rv.version_id=:id FOR SHARE OF r,rv,p
        """), {"id": version_id})
    evidence = {(r.record_version_id, r.evidence_key) for r in payload.source_refs
                if r.evidence_key is not None}
    if len(evidence) > 20:
        raise ActionError("source_unavailable", 403)
    for version_id, key in sorted(evidence, key=lambda pair: (str(pair[0]), pair[1])):
        # Existence witness only, never actor permission. A single active row is
        # enough for the existing any-active-key predicate; hold its lifecycle,
        # key/version and deletion stable through the later metadata/frame.
        # No witness means deny here: a later unlocked insertion cannot grant.
        witness = await session.scalar(text("""
            SELECT span_id FROM evidence_spans
            WHERE record_version_id=:version AND evidence_key=:key AND lifecycle='active'
            ORDER BY span_id LIMIT 1 FOR SHARE
        """), {"version": version_id, "key": key})
        if witness is None:
            raise ActionError("source_unavailable", 403)


async def input_metadata(session: AsyncSession, payload: PlanPayload) -> Any:
    """One statement AFTER locks; project purpose keys only, never fact bodies."""
    refs = [r.model_dump(mode="json") for r in payload.source_refs]
    capabilities = [{"id": s.capability_id, "version": s.capability_version}
                    for s in payload.steps]
    templates = list({str(r.resource_id) for s in payload.steps for r in s.resources
                      if r.resource_type == "template_version"})
    return (await session.execute(text("""
        WITH refs AS (SELECT * FROM jsonb_to_recordset(CAST(:refs AS jsonb))
          AS q(source_key text,record_key text,record_version_id uuid,
               content_sha256 text,evidence_key text)), sources AS (
          SELECT q.*,r.record_id,r.source_key actual_source,r.record_key actual_key,
            r.current_version_id,r.lifecycle record_lifecycle,rv.content_sha256 actual_checksum,
            rv.lifecycle version_lifecycle,p.lifecycle package_lifecycle,rv.verification_state,
            rv.fact_state,rv.provenance_level,rv.freshness_state,rv.effective_from,
            rv.effective_to,rv.freshness_due_at,
            jsonb_build_object('use_class',rv.value_payload->'use_class',
              'sot_tier',rv.value_payload->'sot_tier') purpose,
            (q.evidence_key IS NULL OR EXISTS(SELECT 1 FROM evidence_spans e
              WHERE e.record_version_id=rv.version_id AND e.evidence_key=q.evidence_key
                AND e.lifecycle='active')) evidence_present
          FROM refs q LEFT JOIN record_versions rv ON rv.version_id=q.record_version_id
          LEFT JOIN records r ON r.record_id=rv.record_id
          LEFT JOIN sot_packages p ON p.package_id=rv.package_id)
        SELECT COALESCE((SELECT jsonb_agg(to_jsonb(s)) FROM sources s),'[]'::jsonb) sources,
          COALESCE((SELECT jsonb_agg(jsonb_build_object('capability_id',c.capability_id,
            'version',c.version,'admission',c.admission,'contract_digest',c.contract_digest,
            'schema_digest',c.schema_digest)) FROM capability_versions c
            JOIN jsonb_to_recordset(CAST(:caps AS jsonb)) AS q(id text,version text)
              ON c.capability_id=q.id AND c.version=q.version),'[]'::jsonb) capabilities,
          COALESCE((SELECT jsonb_agg(jsonb_build_object('version_id',tv.version_id,
            'source_sha256',tv.source_sha256,'field_schema',tv.field_schema,
            'renderer_version',tv.renderer_version,'status',tv.status,
            'document_class',t.document_class,'lifecycle',t.lifecycle))
            FROM template_versions tv JOIN templates t USING(template_id)
            WHERE tv.version_id=ANY(CAST(:templates AS uuid[]))),'[]'::jsonb) templates,
          (SELECT jsonb_build_object('scope_kind',scope_kind,'scope_key',scope_key)
            FROM context_packets WHERE packet_id=:packet AND owner_subject_id=:actor
              AND use_class=:purpose) packet
    """), {"refs": json.dumps(refs), "caps": json.dumps(capabilities),
            "templates": templates, "packet": payload.context_packet_id,
            "actor": payload.actor_id, "purpose": payload.purpose})).mappings().one()


def source_requests(metadata: Any) -> list[LeafRequest]:
    return [LeafRequest(uuid.UUID(s["record_id"]), "view", "record")
            for s in metadata["sources"] if s["record_id"] is not None]


def check_sources(
    metadata: Any, frame: LeafCheckpoint, payload: PlanPayload,
    policy: PolicyEngine, request_id: str,
) -> None:
    instant = datetime.now(UTC)
    for source in metadata["sources"]:
        record_id = source["record_id"]
        effective = (frame.attributes.get((uuid.UUID(record_id), "view"))
                     if record_id is not None else None)
        if (effective is None or effective[0].lifecycle_state != "active"
                or effective[0].source_zone != "sot"
                or not policy.decide(frame.subject, "view", effective[0],
                                     PolicyContext(request_id=request_id)).allow):
            raise ActionError("source_unavailable", 403)
        if (source["actual_source"] != source["source_key"]
                or source["actual_key"] != source["record_key"]
                or source["current_version_id"] != source["record_version_id"]
                or source["actual_checksum"] != source["content_sha256"]
                or any(source[key] != "active" for key in
                       ("record_lifecycle", "version_lifecycle", "package_lifecycle"))
                or source["verification_state"] not in {"verified", "approved"}
                or source["fact_state"] not in {"verified", "approved"}
                or source["provenance_level"] == "claim"
                or source["freshness_state"] != "current"
                or source["effective_from"] is None
                or datetime.fromisoformat(source["effective_from"]) > instant
                or any(source[key] is not None
                       and datetime.fromisoformat(source[key]) <= instant
                       for key in ("effective_to", "freshness_due_at"))
                or not source["evidence_present"]
                or blocks(source["purpose"], requested=payload.purpose,
                          provenance_level=source["provenance_level"])):
            raise ActionError("source_unavailable", 403)
