"""TIP-013 Phase A · parity + eval runners — integration (AC-A3, AC-A4).

Executes the parity and quality runners against a live database and asserts the
load-bearing guarantees: parity agrees on every source-scoped question, and the
quality baseline has zero leaks with the expected grounded/null outcomes. These
give the runners teeth in the gate; the committed report artefacts are produced
by the standalone `make parity` / `make eval` runs.
"""

import os
import sys
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

DATABASE_DSN = os.getenv("INTEGRATION_DATABASE_DSN")
pytestmark = pytest.mark.skipif(
    not DATABASE_DSN,
    reason="integration database not configured",
)

EVAL = Path(__file__).resolve().parents[3] / "eval"
if str(EVAL) not in sys.path:
    sys.path.insert(0, str(EVAL))


@pytest.fixture
def factory() -> async_sessionmaker[Any]:
    assert DATABASE_DSN
    engine = create_async_engine(
        DATABASE_DSN.replace("postgresql://", "postgresql+asyncpg://", 1),
    )
    return async_sessionmaker(engine, expire_on_commit=False)


@pytest.mark.asyncio
async def test_parity_runner_agrees_on_scoped_questions(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
) -> None:
    import run_parity

    report = await run_parity.run(tmp_path, factory)
    rows = {row["id"]: row for row in report["rows"]}
    # Every source-scoped question must agree (fact-lookup + honest-null).
    for qid in ("P1", "P2", "P3", "P4", "P5", "P6"):
        assert rows[qid]["agree"], (qid, rows[qid])
    # Fact-lookups: both cite the expected record.
    assert rows["P1"]["v2_citation_correct"] is True
    assert rows["P1"]["pilot_citation_correct"] is True
    # The unscoped probe is a KNOWN, triaged divergence — it must be reported.
    assert rows["P7"]["agree"] is False
    assert report["divergence_count"] == 1
    assert report["triage"][0]["id"] == "P7"


@pytest.mark.asyncio
async def test_eval_runner_zero_leak_and_expected_outcomes(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
) -> None:
    import run_eval

    report = await run_eval.run(tmp_path, factory)
    metrics = report["metrics"]
    assert metrics["leak_count"] == 0
    assert metrics["grounded_rate"] == 1.0
    assert metrics["honest_null_quality"] == 1.0
    assert metrics["citation_accuracy"] == 1.0
    assert metrics["passed"] is True
    # Research zone separation side-check: the beacon lives only in the research
    # zone and never surfaces in the SOT answer (leak_count already 0).
    e7 = next(check for check in report["side_checks"] if check["case_id"] == "E7")
    assert e7["all_labeled_research"] is True
    assert e7["beacon_in_research"] is True


@pytest.mark.asyncio
async def test_eval_runner_is_idempotent(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
) -> None:
    import run_eval

    first = await run_eval.run(tmp_path / "a", factory)
    second = await run_eval.run(tmp_path / "b", factory)
    assert first["metrics"]["leak_count"] == second["metrics"]["leak_count"] == 0
    assert first["metrics"]["passed"] == second["metrics"]["passed"] is True
