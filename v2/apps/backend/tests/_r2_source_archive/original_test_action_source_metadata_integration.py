"""Builder-owned one-query metadata and conflicting-checksum regressions."""

from pathlib import Path
from typing import Any

import pytest
import pytest_asyncio
import test_action_contracts_integration as fixtures
from sqlalchemy import event
from test_action_execution_adversarial import domain

from rtr_copilot.actions.registry import ActionError
from rtr_copilot.actions.source_metadata import resolve_action_sources
from rtr_copilot.context.sources import revalidate_sot_references

pytestmark = fixtures.pytestmark


@pytest_asyncio.fixture
async def factory() -> Any:
    async for value in fixtures.factory.__wrapped__():
        yield value


@pytest.mark.asyncio
async def test_one_metadata_statement_no_content_and_shared_identity_parity(
    factory: Any, tmp_path: Path,
) -> None:
    _, owner, refs, _, _ = await domain(factory, tmp_path)
    expected = await revalidate_sot_references(owner, refs, factory=factory,
                                              use_class="proposal", request_id="RQB-shared")
    statements = []
    engine = factory.kw["bind"].sync_engine

    def observed(*args: Any) -> None:
        statements.append(args[2])

    event.listen(engine, "before_cursor_execute", observed)
    try:
        actual = await resolve_action_sources(owner, refs, factory=factory,
                                              use_class="proposal", request_id="RQB-batch")
    finally:
        event.remove(engine, "before_cursor_execute", observed)
    assert len(statements) == 1 and actual.subject == expected.subject
    assert not actual.gaps and not expected.gaps
    assert actual.sources[0].text is None
    assert actual.sources[0].model_copy(update={"retrieved_at": expected.sources[0].retrieved_at}) \
        == expected.sources[0]


@pytest.mark.asyncio
@pytest.mark.parametrize("reverse", [False, True])
async def test_same_tuple_conflicting_checksums_never_alias_valid_reference(
    factory: Any, tmp_path: Path, reverse: bool,
) -> None:
    actions, owner, refs, _, _ = await domain(factory, tmp_path)
    wrong = refs[0].model_copy(update={"content_sha256": "0" * 64})
    supplied = (refs[0], wrong) if reverse else (wrong, refs[0])
    expected = await revalidate_sot_references(owner, supplied, factory=factory,
                                              use_class="proposal", request_id="RQB-bad-shared")
    actual = await resolve_action_sources(owner, supplied, factory=factory,
                                          use_class="proposal", request_id="RQB-bad-batch")
    assert actual.gaps == expected.gaps and actual.gaps[0].code == "unavailable"
    assert len(actual.sources) == 1 and actual.sources[0].reference == refs[0]
    from rtr_copilot.actions.models import PlanRequest, StepRequest

    proposed = PlanRequest(idempotency_key="RQB-conflicting-checksum",
                           objective="No checksum alias authority", source_refs=supplied,
                           steps=(StepRequest(step_key="read", capability_id="sot.read",
                                              capability_version="2",
                                              arguments={"record_key": refs[0].record_key}),))
    with pytest.raises(ActionError):
        await actions.policy.sources(owner, proposed, "RQB-wrapper")
