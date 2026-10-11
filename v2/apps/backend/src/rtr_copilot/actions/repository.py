import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from rtr_copilot.actions.models import (
    ActionEvent,
    ApprovalBinding,
    ApprovalView,
    BudgetUnits,
    ContractReceipt,
    PlanPayload,
    PlanView,
)
from rtr_copilot.actions.registry import ActionError, canonical, digest


class ActionRepository:
    async def plan(
        self, session: AsyncSession, plan_id: uuid.UUID, *, lock: bool = False
    ) -> PlanView:
        query = """
            SELECT p.*,r.run_id,r.state,r.budget_reserved FROM action_plans p
            JOIN action_runs r USING(plan_id) WHERE p.plan_id=:id
        """ + (" FOR UPDATE OF r" if lock else "")
        row = (await session.execute(text(query), {"id": plan_id})).mappings().one_or_none()
        if row is None:
            raise ActionError("not_found", 404)
        if digest(row["payload"]) != row["plan_digest"]:
            raise ActionError("contract_integrity_invalid")
        return PlanView(
            plan_id=row["plan_id"],
            root_plan_id=row["root_plan_id"],
            plan_version=row["plan_version"],
            plan_digest=str(row["plan_digest"]),
            payload=PlanPayload.model_validate_json(json.dumps(row["payload"])),
            run_id=row["run_id"],
            state=row["state"],
            reserved=BudgetUnits.model_validate_json(json.dumps(row["budget_reserved"])),
        )

    async def approvals(
        self, session: AsyncSession, plan_id: uuid.UUID
    ) -> tuple[ApprovalView, ...]:
        rows = (
            (
                await session.execute(
                    text("""
            SELECT approval_id,binding,decision,revoked_at FROM action_approvals
            WHERE plan_id=:id ORDER BY created_at DESC,approval_id DESC
        """),
                    {"id": plan_id},
                )
            )
            .mappings()
            .all()
        )
        return tuple(
            ApprovalView(
                approval_id=row["approval_id"],
                binding=ApprovalBinding.model_validate_json(json.dumps(row["binding"])),
                decision=row["decision"],
                revoked_at=row["revoked_at"],
            )
            for row in rows
        )

    async def event(
        self,
        session: AsyncSession,
        plan: PlanView,
        *,
        event_type: str,
        reason_code: str,
        request_id: str,
        event_key: str | None = None,
        usage: BudgetUnits | None = None,
    ) -> None:
        usage_body = usage.model_dump(mode="json") if usage else None
        await session.execute(
            text("""
            INSERT INTO action_events(event_id,run_id,event_key,event_type,reason_code,
              plan_digest,correlation_digest,usage,request_id,build_id)
            VALUES (:id,:run,:key,:type,:reason,:plan,:correlation,CAST(:usage AS jsonb),
              :request,:build)
        """),
            {
                "id": uuid.uuid4(),
                "run": plan.run_id,
                "key": event_key or digest(str(uuid.uuid4())),
                "type": event_type,
                "reason": reason_code,
                "plan": plan.plan_digest,
                "correlation": digest({"request": request_id, "usage": usage_body}),
                "usage": canonical(usage_body).decode() if usage else None,
                "request": request_id,
                "build": plan.payload.runtime_build_sha,
            },
        )

    async def receipt(
        self, session: AsyncSession, plan: PlanView, *, kind: str, request_id: str
    ) -> None:
        await session.execute(
            text("""
            INSERT INTO action_receipts(
                receipt_id,run_id,plan_digest,kind,outcome,request_id,build_id)
            VALUES (:id,:run,:digest,:kind,:outcome,:request,:build)
        """),
            {
                "id": uuid.uuid4(),
                "run": plan.run_id,
                "digest": plan.plan_digest,
                "kind": kind,
                "outcome": plan.state,
                "request": request_id,
                "build": plan.payload.runtime_build_sha,
            },
        )

    async def events(self, session: AsyncSession, run_id: uuid.UUID) -> tuple[ActionEvent, ...]:
        rows = (
            (
                await session.execute(
                    text("""
            SELECT event_id,run_id,sequence,event_type,reason_code,plan_digest,
              correlation_digest,request_id,build_id,usage,occurred_at
            FROM action_events WHERE run_id=:id ORDER BY sequence LIMIT 500
        """),
                    {"id": run_id},
                )
            )
            .mappings()
            .all()
        )
        return tuple(
            ActionEvent.model_validate_json(json.dumps(dict(row), default=str)) for row in rows
        )

    async def receipts(
        self, session: AsyncSession, run_id: uuid.UUID
    ) -> tuple[ContractReceipt, ...]:
        rows = (
            (
                await session.execute(
                    text("""
            SELECT receipt_id,run_id,plan_digest,kind,outcome,request_id,build_id,occurred_at
            FROM action_receipts WHERE run_id=:id ORDER BY occurred_at,receipt_id LIMIT 100
        """),
                    {"id": run_id},
                )
            )
            .mappings()
            .all()
        )
        return tuple(
            ContractReceipt.model_validate_json(json.dumps(dict(row), default=str)) for row in rows
        )

    async def capability(self, session: AsyncSession, capability_id: str, version: str) -> Any:
        return (
            (
                await session.execute(
                    text("""
            SELECT * FROM capability_versions WHERE capability_id=:id AND version=:version
        """),
                    {"id": capability_id, "version": version},
                )
            )
            .mappings()
            .one_or_none()
        )
