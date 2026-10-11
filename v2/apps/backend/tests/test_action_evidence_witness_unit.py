"""Bounded lock-query protocol only; real serialization is a separate SQL gate."""

import uuid
from typing import Any

import pytest

from rtr_copilot.actions.checkpoints import lock_inputs
from rtr_copilot.actions.models import BudgetRequest, PlanPayload
from rtr_copilot.actions.registry import ActionError
from rtr_copilot.context.models import SOTReference


def ref(*, version: uuid.UUID | None = None, key: str | None = None) -> SOTReference:
    return SOTReference(source_key="synthetic", record_key="SYNTHETIC", evidence_key=key,
                        record_version_id=version or uuid.uuid4(), content_sha256="a" * 64)


def payload(refs: Any) -> PlanPayload:
    actor = uuid.uuid4()
    return PlanPayload(actor_id=actor, actor_security_version=1, workspace_id=actor,
                       context_packet_id=None, objective="Bounded evidence witness",
                       purpose="proposal", source_refs=refs, steps=(), budget=BudgetRequest(),
                       reviewers=(), requested_internal_draft=False, runtime_build_sha="synthetic")


class Session:
    def __init__(self, *, missing: bool = False) -> None:
        self.missing = missing
        self.queries: list[tuple[str, Any]] = []
        self.witnesses: list[tuple[str, Any]] = []
        self.actors: list[uuid.UUID] = []

    async def execute(self, statement: Any, parameters: Any) -> Any:
        self.queries.append((str(statement), parameters))
        self.actors = parameters.get("actors", self.actors)
        return self

    def scalars(self) -> Any:
        return self

    def all(self) -> Any:
        return self.actors

    async def scalar(self, statement: Any, parameters: Any) -> uuid.UUID | None:
        self.witnesses.append((str(statement), parameters))
        return None if self.missing else uuid.uuid4()


@pytest.mark.asyncio
async def test_null_evidence_adds_zero_queries() -> None:
    plan = payload((ref(), ref()))
    session = Session()
    await lock_inputs(session, plan, (plan.actor_id,), sources_only=True)  # type: ignore[arg-type]
    assert not session.witnesses and len(session.queries) == 3  # Actor plus two source fences.


@pytest.mark.asyncio
async def test_witnesses_are_sorted_deduplicated_single_active_rows() -> None:
    version = uuid.uuid4()
    plan = payload((ref(version=version, key="z"), ref(version=version, key="a"),
                    ref(version=version, key="z")))
    session = Session()
    await lock_inputs(session, plan, (plan.actor_id,), sources_only=True)  # type: ignore[arg-type]
    assert [parameters["key"] for _, parameters in session.witnesses] == ["a", "z"]
    assert all("lifecycle='active'" in sql and "ORDER BY span_id LIMIT 1 FOR SHARE" in sql
               and "quoted_text" not in sql for sql, _ in session.witnesses)


@pytest.mark.asyncio
async def test_missing_witness_denies_without_a_later_insertion_grant() -> None:
    plan = payload((ref(key="missing"),))
    session = Session(missing=True)
    with pytest.raises(ActionError, match="source_unavailable"):
        await lock_inputs(session, plan, (plan.actor_id,), sources_only=True)  # type: ignore[arg-type]
    assert len(session.witnesses) == 1


@pytest.mark.asyncio
async def test_more_than_twenty_requested_pairs_cannot_lock_evidence() -> None:
    plan = payload(tuple(ref(key=str(n)) for n in range(21)))
    session = Session()
    with pytest.raises(ActionError, match="source_unavailable"):
        await lock_inputs(session, plan, (plan.actor_id,), sources_only=True)  # type: ignore[arg-type]
    assert not session.witnesses
