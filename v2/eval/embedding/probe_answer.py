#!/usr/bin/env python3
"""TIP-014RE · Answer probe: generate the real answer for the term-gated cases
and report which required_terms are present/missing. One provider call per
case; read-only against the corpus.

    docker compose --env-file .env.demo run --rm \
      -v "$PWD/eval":/app/eval:ro api python /app/eval/embedding/probe_answer.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid

from sqlalchemy import text

from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.rag.answering import AnswerService
from rtr_copilot.rag.models import SearchFilters

sys.path.insert(0, "/app/eval")
from lib.operational_acceptance import term_present  # noqa: E402

CASES = [
    ("SYS-007", "website công ty dùng tech stack gì?", ["Next.js", "Sanity"]),
    ("MTH-004", "công ty đã audit những skill nội bộ nào", ["6 skill", "vibecode-kit"]),
]


async def _run() -> int:
    uow = UnitOfWork(None)
    async with uow.factory() as session:
        row = (await session.execute(text("""
            SELECT user_id, issuer, provider_sub, email, canonical_domain
            FROM subjects ORDER BY created_at LIMIT 1
        """))).mappings().one_or_none()
    subject = Subject(
        user_id=str(row["user_id"]), issuer=str(row["issuer"]),
        sub=str(row["provider_sub"]), email=str(row["email"]),
        canonical_domain=str(row["canonical_domain"]), roles={Role.STAFF},
    )
    service = AnswerService()
    for case_id, question, required in CASES:
        resp = await service.ask(
            subject, question,
            filters=SearchFilters(), require_verified=True,
            conversation_id=None, request_id=f"probe-{uuid.uuid4().hex[:8]}",
        )
        print(f"\n== {case_id} · {question!r}")
        print(f"   state={resp.state} citations={[c.record_key for c in resp.citations]}")
        print(f"   answer={resp.answer!r}")
        for term in required:
            print(f"   term {term!r}: present={term_present(term, resp.answer)}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
