"""Run an idempotent, real-runtime Document OS lifecycle proof."""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import uuid
from pathlib import Path
from typing import Any

from sqlalchemy import text

from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.documents.models import DecisionRequest, RenderRequest
from rtr_copilot.documents.service import DocumentOSService

PROOF_KEY = "tip031-document-lifecycle-v1"
TEMPLATE_KEY = "pilot.factsheet"
LEADER_ID = uuid.uuid5(uuid.NAMESPACE_URL, "rtr:tip031:document-leader")


def _subject(row: Any, roles: set[Role]) -> Subject:
    return Subject(
        user_id=str(row["user_id"]),
        issuer=str(row["issuer"]),
        sub=str(row["provider_sub"]),
        email=str(row["email"]),
        canonical_domain=str(row["canonical_domain"]),
        display_name=str(row["display_name"] or ""),
        roles=roles,
    )


async def _prepare() -> tuple[Subject, Subject, uuid.UUID, uuid.UUID | None]:
    uow = UnitOfWork()
    async with uow.transaction() as session:
        template = (await session.execute(text("""
            SELECT t.current_version_id,s.user_id,s.issuer,s.provider_sub,s.email,
                   s.canonical_domain,s.display_name
            FROM templates t JOIN subjects s ON s.user_id=t.owner_subject_id
            JOIN template_versions tv ON tv.version_id=t.current_version_id
            WHERE t.stable_key=:key AND t.lifecycle='approved'
              AND tv.status='approved'
        """), {"key": TEMPLATE_KEY})).mappings().one_or_none()
        if template is None:
            raise RuntimeError("document_proof_template_unavailable")
        await session.execute(text("""
            INSERT INTO subjects(
              user_id,issuer,provider_sub,email,canonical_domain,display_name,status
            ) VALUES (
              :id,'tip031-document-proof',:sub,:email,'rtrobotics.com',
              'TIP-031 Document Leader','active'
            ) ON CONFLICT (user_id) DO UPDATE SET status='active'
        """), {
            "id": LEADER_ID,
            "sub": LEADER_ID.hex,
            "email": "tip031-document-leader@rtrobotics.com",
        })
        await session.execute(text("""
            INSERT INTO subject_roles(subject_id,role_id)
            SELECT :id,role_id FROM roles WHERE key IN ('staff','leader')
            ON CONFLICT DO NOTHING
        """), {"id": LEADER_ID})
        existing_job = await session.scalar(text("""
            SELECT render_job_id FROM render_jobs
            WHERE requester_id=:owner AND idempotency_key=:key
            ORDER BY created_at LIMIT 1
        """), {"owner": template["user_id"], "key": PROOF_KEY})
    owner = _subject(template, {Role.STAFF, Role.CURATOR})
    leader = Subject(
        user_id=str(LEADER_ID),
        issuer="tip031-document-proof",
        sub=LEADER_ID.hex,
        email="tip031-document-leader@rtrobotics.com",
        canonical_domain="rtrobotics.com",
        display_name="TIP-031 Document Leader",
        roles={Role.STAFF, Role.LEADER},
    )
    return (
        owner,
        leader,
        uuid.UUID(str(template["current_version_id"])),
        uuid.UUID(str(existing_job)) if existing_job else None,
    )


async def _grant_approval(version_id: uuid.UUID) -> None:
    async with UnitOfWork().transaction() as session:
        await session.execute(text("""
            INSERT INTO acl_entries(
              resource_id,principal_type,principal_id,action,effect,
              granted_by,reason
            ) SELECT :version,'user',:leader,'approve','allow',:leader,
                     'TIP-031 Document OS lifecycle proof'
            WHERE NOT EXISTS (
              SELECT 1 FROM acl_entries WHERE resource_id=:version
                AND principal_type='user' AND principal_id=:leader
                AND action='approve' AND effect='allow'
                AND (expires_at IS NULL OR expires_at>now())
            )
        """), {"version": version_id, "leader": LEADER_ID})


async def _canonical_state(generated_id: uuid.UUID) -> dict[str, Any]:
    async with UnitOfWork().factory() as session:
        row = (await session.execute(text("""
            SELECT g.lifecycle,g.checksum,
              count(DISTINCT a.approval_id)::int AS approvals,
              count(DISTINCT i.issuance_id)::int AS issuances,
              count(DISTINCT i.issuance_id) FILTER (
                WHERE i.revoked_at IS NOT NULL
              )::int AS revocations,
              count(DISTINCT e.event_id) FILTER (
                WHERE e.action='document.render' AND e.result='success'
              )::int AS render_audits,
              count(DISTINCT e.event_id) FILTER (
                WHERE e.action='document.issue'
              )::int AS issue_audits,
              count(DISTINCT e.event_id) FILTER (
                WHERE e.action='document.revoke'
              )::int AS revoke_audits
            FROM generated_files g
            LEFT JOIN approvals a ON a.generated_file_id=g.generated_file_id
            LEFT JOIN document_issuances i
              ON i.generated_file_id=g.generated_file_id
            LEFT JOIN audit_events e
              ON (
                e.details->>'generated_file_id'=CAST(g.generated_file_id AS text)
                OR e.details->>'render_job_id'=CAST(g.render_job_id AS text)
              )
            WHERE g.generated_file_id=:id
            GROUP BY g.generated_file_id,g.lifecycle,g.checksum
        """), {"id": generated_id})).mappings().one()
    return dict(row)


async def prove(timeout_seconds: int) -> dict[str, Any]:
    if get_settings().app_env == "production":
        raise RuntimeError("document_proof_local_only")
    owner, leader, template_version, existing_job = await _prepare()
    service = DocumentOSService()
    if existing_job is None:
        status = await service.create_render(
            owner,
            template_version,
            RenderRequest(
                idempotency_key=PROOF_KEY,
                parameters={
                    "ten_san_pham": "HERA · TIP-031 lifecycle proof",
                    "mo_ta_ngan": "Bản chứng minh vận hành Document OS",
                    "ghi_chu": "Không dùng cho phát hành bên ngoài",
                    "ngay_lap": "2026-08-11",
                },
            ),
            request_id="tip031-document-render",
        )
    else:
        status = await service.status(
            owner, existing_job, request_id="tip031-document-resume",
        )
    deadline = time.monotonic() + timeout_seconds
    while status.state not in {"completed", "failed", "cancelled"}:
        if time.monotonic() >= deadline:
            raise RuntimeError("document_proof_render_timeout")
        await asyncio.sleep(1)
        status = await service.status(
            owner, status.render_job_id, request_id="tip031-document-poll",
        )
    if status.state != "completed" or not status.generated_file_id or not status.version_id:
        raise RuntimeError(f"document_proof_render_{status.error_code or status.state}")

    generated_id = status.generated_file_id
    await _grant_approval(status.version_id)
    async with UnitOfWork().factory() as session:
        lifecycle = await session.scalar(text(
            "SELECT lifecycle FROM generated_files WHERE generated_file_id=:id",
        ), {"id": generated_id})
    if lifecycle == "draft":
        await service.submit(owner, generated_id, request_id="tip031-document-submit")
        lifecycle = "in_review"
    if lifecycle == "in_review":
        await service.decide(
            leader,
            generated_id,
            "approved",
            DecisionRequest(reason="TIP-031 independent lifecycle approval"),
            request_id="tip031-document-approve",
        )
        lifecycle = "approved"
    if lifecycle == "approved":
        await service.issue(
            leader, generated_id, request_id="tip031-document-issue",
        )
        lifecycle = "issued"
    if lifecycle == "issued":
        await service.revoke(
            leader,
            generated_id,
            DecisionRequest(reason="TIP-031 proof completed; artifact retired"),
            request_id="tip031-document-revoke",
        )

    state = await _canonical_state(generated_id)
    expected = {
        "lifecycle": "revoked",
        "approvals": 1,
        "issuances": 1,
        "revocations": 1,
        "render_audits": 1,
        "issue_audits": 1,
        "revoke_audits": 1,
    }
    if any(state.get(key) != value for key, value in expected.items()):
        raise RuntimeError("document_proof_canonical_state_invalid")
    return {
        "schema_version": 1,
        "proof_key": PROOF_KEY,
        "template_key": TEMPLATE_KEY,
        "render_job_id": str(status.render_job_id),
        "generated_file_id": str(generated_id),
        "version_id": str(status.version_id),
        "checksum": str(state["checksum"]),
        "state": {key: state[key] for key in expected},
        "verdict": "passed",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approve", action="store_true")
    parser.add_argument("--timeout-seconds", type=int, default=180)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    if not args.approve:
        parser.error("proof requires --approve")
    result = asyncio.run(prove(args.timeout_seconds))
    payload = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(payload + "\n", encoding="utf-8")
    print(payload)


if __name__ == "__main__":
    main()
