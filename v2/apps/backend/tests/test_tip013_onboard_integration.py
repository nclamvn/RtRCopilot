"""TIP-013 Phase A · onboarding tool — integration (AC-A2).

Drives synthetic batches through the REAL gates against a live database:

* a clean batch onboards — an SOT revision activates and a research package
  imports then graduates into a STAGED (never auto-activated) candidate;
* a defective batch is rejected fail-closed with a typed reason and ZERO partial
  activation;
* re-applying the clean batch is idempotent (no double activation);
* a dry-run writes nothing.
"""

import os
import uuid
from pathlib import Path
from typing import Any

import pytest
from pydantic import SecretStr
from research_fixtures import build_research_package, research_record_row
from sot_fixtures import NOW, SECRET, build_package
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from rtr_copilot.commands.onboard_batch import BatchManifest, OnboardBatch
from rtr_copilot.config import get_settings
from rtr_copilot.governance.models import ResearchSource
from rtr_copilot.repositories.governance import GovernanceRepository

DATABASE_DSN = os.getenv("INTEGRATION_DATABASE_DSN")
pytestmark = pytest.mark.skipif(
    not DATABASE_DSN,
    reason="integration database not configured",
)


@pytest.fixture
def factory() -> async_sessionmaker[Any]:
    assert DATABASE_DSN
    engine = create_async_engine(
        DATABASE_DSN.replace("postgresql://", "postgresql+asyncpg://", 1),
    )
    return async_sessionmaker(engine, expire_on_commit=False)


def _settings(root: Path) -> Any:
    return get_settings().model_copy(update={
        "sot_staging_root": root,
        "research_staging_root": root,
        "sot_signing_secret": SecretStr(SECRET),
    })


def _tool(root: Path, factory: async_sessionmaker[Any]) -> OnboardBatch:
    return OnboardBatch(_settings(root), factory=factory, clock=lambda: NOW)


async def _insert_subject(factory: async_sessionmaker[Any], subject_id: uuid.UUID) -> None:
    async with factory() as session, session.begin():
        await session.execute(text("""
            INSERT INTO subjects(user_id,issuer,provider_sub,email,canonical_domain)
            VALUES (:id,'onboard-integration',:sub,:email,'rtrobotics.com')
            ON CONFLICT (user_id) DO NOTHING
        """), {
            "id": subject_id,
            "sub": subject_id.hex,
            "email": f"{subject_id.hex}@rtrobotics.com",
        })


async def _create_source(
    factory: async_sessionmaker[Any],
    owner_id: uuid.UUID,
) -> ResearchSource:
    source = ResearchSource(
        stable_key=f"refinery.{uuid.uuid4().hex}",
        display_name="Synthetic onboarding corpus",
        origin="refinery",
        owner_subject_id=owner_id,
        classification="internal",
        lifecycle="active",
    )
    async with factory() as session, session.begin():
        await GovernanceRepository().create_source(session, source)
    return source


async def _active_records(factory: async_sessionmaker[Any], source_key: str) -> int:
    async with factory() as session:
        return int(await session.scalar(text("""
            SELECT count(*) FROM records
            WHERE source_key=:source_key AND lifecycle='active'
        """), {"source_key": source_key}) or 0)


@pytest.mark.asyncio
async def test_clean_batch_onboards_sot_and_research_graduation(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
) -> None:
    curator = uuid.uuid4()
    proposer = uuid.uuid4()
    decider = uuid.uuid4()
    for subject_id in (curator, proposer, decider):
        await _insert_subject(factory, subject_id)
    source = await _create_source(factory, curator)
    sot_source_key = f"onboard.sot.{uuid.uuid4().hex}"
    sot_record_key = f"ONB.{uuid.uuid4().hex}"
    package_root = build_package(
        tmp_path,
        curator_id=curator,
        owner_id=curator,
        source_key=sot_source_key,
        record_key=sot_record_key,
    )
    grad_record_key = f"IND.{uuid.uuid4().hex[:12].upper()}"
    research_name = build_research_package(
        tmp_path,
        source_key=source.stable_key,
        records=[research_record_row(
            record_key=grad_record_key,
            text="industry corroborates synthetic beacon relays",
        )],
    )
    manifest = BatchManifest.model_validate({
        "batch_id": "clean-int",
        "curator_subject_id": str(curator),
        "sot_items": [{
            "staging_name": package_root.name,
            "expected_source_key": sot_source_key,
        }],
        "research_items": [{
            "staging_name": research_name,
            "source_key": source.stable_key,
            "graduation": {
                "proposer_subject_id": str(proposer),
                "decider_subject_id": str(decider),
                "target_record_key": f"company.claims.{uuid.uuid4().hex[:8]}",
                "record_keys": [grad_record_key],
                "claim_text": "Company operates synthetic beacon relays",
                "value": {"category": "capability"},
            },
        }],
    })
    report = await _tool(tmp_path, factory).run(manifest, apply=True, approved=True)
    assert report.status == "onboarded", report.summary
    assert report.activated_count == 1
    assert await _active_records(factory, sot_source_key) == 1
    research_item = next(item for item in report.items if item.kind == "research")
    assert research_item.state == "imported+graduated"
    graduation = research_item.detail["graduation"]
    assert graduation["state"] == "approved"
    # Graduation stages a candidate but MUST NOT auto-activate (REQ-033).
    assert graduation["publish_package_id"] is not None
    assert graduation["auto_activated"] is False
    async with factory() as session:
        candidate_state = await session.scalar(text("""
            SELECT lifecycle FROM sot_packages WHERE package_id=:pid
        """), {"pid": uuid.UUID(graduation["publish_package_id"])})
    assert candidate_state == "staged"

    # Idempotent re-apply: no double activation, gate reports idempotent.
    repeat = await _tool(tmp_path, factory).run(manifest, apply=True, approved=True)
    assert repeat.status == "onboarded"
    assert await _active_records(factory, sot_source_key) == 1
    sot_repeat = next(item for item in repeat.items if item.kind == "sot")
    assert sot_repeat.idempotent


@pytest.mark.asyncio
async def test_defective_batch_rejected_zero_partial_activation(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
) -> None:
    curator = uuid.uuid4()
    await _insert_subject(factory, curator)
    good_source = f"onboard.good.{uuid.uuid4().hex}"
    good = build_package(
        tmp_path,
        curator_id=curator,
        owner_id=curator,
        source_key=good_source,
        record_key=f"GOOD.{uuid.uuid4().hex}",
    )
    bad_source = f"onboard.bad.{uuid.uuid4().hex}"
    bad = build_package(
        tmp_path,
        curator_id=curator,
        owner_id=curator,
        source_key=bad_source,
        record_key=f"BAD.{uuid.uuid4().hex}",
        provenance_level="claim",
        verification_state="approved",
    )
    manifest = BatchManifest.model_validate({
        "batch_id": "defective-int",
        "curator_subject_id": str(curator),
        "sot_items": [
            {"staging_name": good.name},
            {"staging_name": bad.name},
        ],
    })
    report = await _tool(tmp_path, factory).run(manifest, apply=True, approved=True)
    assert report.status == "rejected"
    assert report.activated_count == 0
    # Zero partial activation: neither the good nor the bad source has any row.
    assert await _active_records(factory, good_source) == 0
    assert await _active_records(factory, bad_source) == 0
    async with factory() as session:
        staged = await session.scalar(text("""
            SELECT count(*) FROM sot_packages
            WHERE source_key IN (:good,:bad)
        """), {"good": good_source, "bad": bad_source})
    assert staged == 0


@pytest.mark.asyncio
async def test_dry_run_writes_nothing(
    tmp_path: Path,
    factory: async_sessionmaker[Any],
) -> None:
    curator = uuid.uuid4()
    await _insert_subject(factory, curator)
    source_key = f"onboard.dry.{uuid.uuid4().hex}"
    package_root = build_package(
        tmp_path,
        curator_id=curator,
        owner_id=curator,
        source_key=source_key,
        record_key=f"DRY.{uuid.uuid4().hex}",
    )
    manifest = BatchManifest.model_validate({
        "batch_id": "dry-int",
        "curator_subject_id": str(curator),
        "sot_items": [{"staging_name": package_root.name}],
    })
    report = await _tool(tmp_path, factory).run(manifest, apply=False, approved=False)
    assert report.status == "validated"
    async with factory() as session:
        staged = await session.scalar(text("""
            SELECT count(*) FROM sot_packages WHERE source_key=:source_key
        """), {"source_key": source_key})
    assert staged == 0
