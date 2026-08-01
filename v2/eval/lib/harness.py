"""TIP-013 · V2 seeding + ask harness (integration).

Reuses the exact machinery the backend integration tests use — the synthetic SOT
package builder and the publish -> reindex pipeline — so the parity and quality
runners exercise the REAL V2 answer path (retrieval + grounded answering) against
seeded synthetic fixtures. Requires a live database (``INTEGRATION_DATABASE_DSN``).
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any

from pydantic import SecretStr
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

_LIB = Path(__file__).resolve()
BACKEND = _LIB.parents[2] / "apps" / "backend"
TESTS = BACKEND / "tests"
if str(TESTS) not in sys.path:
    sys.path.insert(0, str(TESTS))
if str(BACKEND / "src") not in sys.path:
    sys.path.insert(0, str(BACKEND / "src"))

from research_fixtures import build_research_package, research_record_row  # noqa: E402
from sot_fixtures import NOW, SECRET, build_package  # noqa: E402

from rtr_copilot.auth.models import Role, Subject  # noqa: E402
from rtr_copilot.config import get_settings  # noqa: E402
from rtr_copilot.rag.adapters import OfflineExtractiveAnswer  # noqa: E402
from rtr_copilot.rag.answering import AnswerService  # noqa: E402
from rtr_copilot.rag.models import AskResponse, SearchFilters  # noqa: E402
from rtr_copilot.rag.reindex import ReindexService  # noqa: E402
from rtr_copilot.rag.retrieval import RetrievalService  # noqa: E402
from rtr_copilot.research.service import ResearchService  # noqa: E402
from rtr_copilot.sot.service import SOTPublishService  # noqa: E402


def make_factory(dsn: str) -> async_sessionmaker[Any]:
    engine = create_async_engine(
        dsn.replace("postgresql://", "postgresql+asyncpg://", 1),
    )
    return async_sessionmaker(engine, expire_on_commit=False)


def settings_for(root: Path) -> Any:
    return get_settings().model_copy(update={
        "sot_staging_root": root,
        "research_staging_root": root,
        "sot_signing_secret": SecretStr(SECRET),
        "rag_provider_mode": "local",
    })


def subject(user_id: uuid.UUID, role: Role = Role.STAFF) -> Subject:
    return Subject(
        user_id=str(user_id),
        issuer="tip013-eval",
        sub=user_id.hex,
        email=f"{user_id.hex}@rtrobotics.com",
        canonical_domain="rtrobotics.com",
        roles={role},
    )


class V2Harness:
    def __init__(self, root: Path, factory: async_sessionmaker[Any]) -> None:
        self.root = root
        self.factory = factory
        self.settings = settings_for(root)

    async def insert_subject(self, user_id: uuid.UUID) -> None:
        async with self.factory() as session, session.begin():
            await session.execute(text("""
                INSERT INTO subjects(user_id,issuer,provider_sub,email,canonical_domain)
                VALUES (:id,'tip013-eval',:sub,:email,'rtrobotics.com')
                ON CONFLICT (user_id) DO NOTHING
            """), {
                "id": user_id,
                "sub": user_id.hex,
                "email": f"{user_id.hex}@rtrobotics.com",
            })

    async def seed_sot(
        self,
        actor_id: uuid.UUID,
        *,
        source_key: str,
        record_key: str,
        text_value: str,
        revision: int = 1,
        ordinal: int = 1,
        supersedes: bool = False,
        classification: str = "internal",
        provenance_level: str = "approved_internal",
        verification_state: str = "approved",
        fact_state: str = "approved",
    ) -> uuid.UUID | None:
        # Deterministic package id so re-seeding identical content is idempotent
        # (stage/publish short-circuit on matching checksums) — the runners can be
        # re-run on a populated database without a revision_checksum_conflict.
        fingerprint = ":".join([
            "tip013", source_key, record_key, str(revision), str(ordinal),
            classification, provenance_level, verification_state, fact_state,
            text_value,
        ])
        package_id = uuid.uuid5(uuid.NAMESPACE_URL, fingerprint)
        staging_name = f"package-{package_id}"
        if not (self.root / staging_name).exists():
            build_package(
                self.root,
                curator_id=actor_id,
                owner_id=actor_id,
                package_id=package_id,
                source_key=source_key,
                record_key=record_key,
                revision=revision,
                ordinal=ordinal,
                supersedes=supersedes,
                classification=classification,
                text=text_value,
                provenance_level=provenance_level,
                verification_state=verification_state,
                fact_state=fact_state,
            )
        service = SOTPublishService(self.settings, factory=self.factory, clock=lambda: NOW)
        staged = await service.stage(
            staging_name, actor_id=actor_id, request_id=f"seed-stage-{revision}",
        )
        if staged.state not in ("staged", "validated"):
            # Already published (active/superseded) on an earlier run — idempotent.
            return await self._active_generation(source_key)
        if staged.state == "staged":
            await service.validate(
                staged.package_id,
                actor_id=actor_id,
                request_id=f"seed-validate-{revision}",
            )
        published = await service.publish(
            staged.package_id, actor_id=actor_id, request_id=f"seed-publish-{revision}",
        )
        if published.idempotent:
            return await self._active_generation(source_key)
        async with self.factory() as session:
            outbox_id = await session.scalar(text("""
                SELECT outbox_id FROM sot_reindex_outbox WHERE run_id=:run_id
            """), {"run_id": published.run_id})
        assert outbox_id is not None
        return await ReindexService(self.settings, factory=self.factory).process(outbox_id)

    async def _active_generation(self, source_key: str) -> uuid.UUID | None:
        async with self.factory() as session:
            return await session.scalar(text("""
                SELECT generation_id FROM active_search_generations
                WHERE source_key=:source_key
            """), {"source_key": source_key})

    async def deny_view(self, source_key: str, principal: uuid.UUID, owner: uuid.UUID) -> None:
        async with self.factory() as session, session.begin():
            record_id = await session.scalar(text("""
                SELECT record_id FROM records WHERE source_key=:source_key
            """), {"source_key": source_key})
            existing = await session.scalar(text("""
                SELECT count(*) FROM acl_entries
                WHERE resource_id=:record_id AND principal_type='user'
                  AND principal_id=:principal AND action='view' AND effect='deny'
            """), {"record_id": record_id, "principal": principal})
            if int(existing or 0) > 0:
                return
            await session.execute(text("""
                INSERT INTO acl_entries(
                  resource_id,principal_type,principal_id,action,effect,granted_by
                ) VALUES (:record_id,'user',:principal,'view','deny',:owner)
            """), {"record_id": record_id, "principal": principal, "owner": owner})

    async def ask(
        self,
        asker: Subject,
        question: str,
        *,
        source_key: str | None = None,
        require_verified: bool = True,
    ) -> AskResponse:
        retrieval = RetrievalService(self.settings, factory=self.factory)
        service = AnswerService(
            self.settings,
            factory=self.factory,
            retrieval=retrieval,
            provider=OfflineExtractiveAnswer(),
        )
        return await service.ask(
            asker,
            question,
            filters=SearchFilters(source_key=source_key),
            require_verified=require_verified,
            conversation_id=None,
            request_id=f"eval-{uuid.uuid4().hex[:8]}",
        )

    def research_service(self) -> ResearchService:
        return ResearchService(self.settings, factory=self.factory)

    async def create_research_source(
        self,
        owner: uuid.UUID,
        *,
        stable_key: str | None = None,
    ) -> str:
        from rtr_copilot.governance.models import ResearchSource
        from rtr_copilot.repositories.governance import GovernanceRepository

        stable_key = stable_key or f"refinery.{uuid.uuid4().hex}"
        async with self.factory() as session:
            existing = await GovernanceRepository().get_source_by_key(session, stable_key)
        if existing is not None:
            return stable_key
        source = ResearchSource(
            stable_key=stable_key,
            display_name="Synthetic eval research corpus",
            origin="refinery",
            owner_subject_id=owner,
            classification="internal",
            lifecycle="active",
        )
        async with self.factory() as session, session.begin():
            await GovernanceRepository().create_source(session, source)
        return stable_key

    async def import_research(
        self,
        curator: Subject,
        source_key: str,
        *,
        record_key: str,
        text_value: str,
    ) -> uuid.UUID:
        staging_name = build_research_package(
            self.root,
            source_key=source_key,
            records=[research_record_row(record_key=record_key, text=text_value)],
        )
        result = await self.research_service().import_package(
            curator,
            staging_name,
            request_id=f"eval-research-{uuid.uuid4().hex[:8]}",
        )
        return result.package.package_id

    async def research_search(
        self,
        curator: Subject,
        query: str,
    ) -> list[dict[str, Any]]:
        response = await self.research_service().search(
            curator,
            query,
            request_id=f"eval-research-search-{uuid.uuid4().hex[:8]}",
        )
        return [
            {
                "zone_label": hit.zone_label,
                "record_key": hit.record_key,
                "snippet": hit.snippet,
            }
            for hit in response.results
        ]


__all__ = [
    "NOW",
    "Role",
    "SearchFilters",
    "V2Harness",
    "build_research_package",
    "make_factory",
    "research_record_row",
    "settings_for",
    "subject",
]
