#!/usr/bin/env python3
"""TIP-014RE · One-off retrieval probe: which records reach the candidate set?

Runs the PRODUCTION RetrievalService.search for the semantic acceptance
questions with an existing corpus-authorized subject, printing the ranked
record keys + scores. No LLM call, read-only, diagnostic only.

    docker compose --env-file .env.demo run --rm \
      -v "$PWD/eval":/app/eval:ro api python /app/eval/embedding/probe_retrieval.py
"""

from __future__ import annotations

import asyncio
import sys
import uuid

from sqlalchemy import text

from rtr_copilot.auth.models import Role, Subject
from rtr_copilot.config import get_settings
from rtr_copilot.db.uow import UnitOfWork
from rtr_copilot.rag.adapters import normalize_query
from rtr_copilot.rag.models import SearchFilters
from rtr_copilot.rag.ontology import load_ontology
from rtr_copilot.rag.query_understanding import (
    DEFAULT_REWRITE_TIMEOUT,
    plan_query,
)
from rtr_copilot.rag.relevance import candidate_relevance_score, profile_query
from rtr_copilot.rag.retrieval import RetrievalService
from rtr_copilot.rag.rewrite_llm import build_rewriter

QUESTIONS = [
    ("SYS-007", "website công ty dùng tech stack gì?", "L3F.4.011"),
    ("MTH-004", "công ty đã audit những skill nội bộ nào", "L3F.2.035"),
]


async def _run() -> int:
    uow = UnitOfWork(None)
    async with uow.factory() as session:
        row = (await session.execute(text("""
            SELECT user_id, issuer, provider_sub, email, canonical_domain
            FROM subjects ORDER BY created_at LIMIT 1
        """))).mappings().one_or_none()
        # Cross-check the exact question text used by the campaign.
        digests = (await session.execute(text(
            "SELECT count(*) FROM chunks WHERE record_key = ANY(:keys)",
        ), {"keys": [oracle for _, _, oracle in QUESTIONS]})).scalar()
    if row is None:
        print("no subjects in database", file=sys.stderr)
        return 2
    print(f"probe subject: {row['email']} · oracle chunk rows: {digests}", file=sys.stderr)
    probe_subject = Subject(
        user_id=str(row["user_id"]),
        issuer=str(row["issuer"]),
        sub=str(row["provider_sub"]),
        email=str(row["email"]),
        canonical_domain=str(row["canonical_domain"]),
        roles={Role.STAFF},
    )
    settings = get_settings()
    ontology = load_ontology()
    rewriter = build_rewriter(settings, ontology)
    service = RetrievalService()
    for case_id, question, oracle in QUESTIONS:
        # Replicate the ASK path exactly: LLM plan first, then search with
        # the full plan contract (rewrite, entities, intent, support terms).
        plan = await plan_query(
            question,
            rewriter,
            registry=ontology,
            timeout=getattr(rewriter, "total_timeout", DEFAULT_REWRITE_TIMEOUT),
            candidate_limit=settings.rag_query_candidate_limit,
        )
        relevance_question = (
            question
            if normalize_query(plan.resolved_question) == normalize_query(question)
            else f"{question} {plan.resolved_question}"
        )
        print(f"\n== {case_id} · {question!r} · oracle={oracle}")
        print(f"   plan: source={plan.planner_source} intent={plan.intent} "
              f"resolution={plan.resolution_state}")
        print(f"   retrieval_query={plan.retrieval_query!r}")
        print(f"   entities={plan.retrieval_entities} "
              f"expansions={plan.expansions} retrieval_queries={plan.retrieval_queries}")
        print(f"   definition_keys={plan.definition_record_keys} "
              f"profile_keys={plan.profile_record_keys} "
              f"collection_keys={plan.collection_record_keys}")
        hits = await service.search(
            probe_subject,
            plan.retrieval_query,
            filters=SearchFilters(),
            request_id=f"probe-{uuid.uuid4().hex[:8]}",
            top_k=settings.rag_answer_candidate_k,
            query_entities=plan.retrieval_entities,
            query_collection_record_keys=plan.collection_record_keys,
            query_intent=plan.intent,
            query_definition_record_keys=plan.definition_record_keys,
            query_profile_record_keys=plan.profile_record_keys,
            ranking_query=relevance_question,
            support_queries=tuple(dict.fromkeys((
                *plan.expansions,
                *plan.retrieval_queries,
            ))),
        )
        # Decisive gate diagnostic: is the oracle even a SCORED candidate, or
        # is it excluded upstream at the allowed_ids / metadata-scan stage?
        async with uow.factory() as session:
            oracle_ids = {
                r[0] for r in (await session.execute(text("""
                    SELECT c.chunk_id FROM chunks c
                    JOIN active_search_generations g
                      ON g.generation_id = c.generation_id
                    WHERE c.lifecycle='active' AND c.record_key = :oracle
                """), {"oracle": oracle})).all()
            }
            total_active = (await session.execute(text("""
                SELECT count(*) FROM chunks c
                JOIN active_search_generations g
                  ON g.generation_id = c.generation_id
                WHERE c.lifecycle='active' AND c.source_zone='sot'
            """))).scalar()
        loaded = set(service.trace.loaded_chunk_ids)
        print(
            f"   trace: metadata={service.trace.metadata_rows} "
            f"policy_allowed={service.trace.policy_allowed} "
            f"loaded={len(loaded)} total_active_sot={total_active} "
            f"degraded={service.trace.embedding_degraded}",
        )
        print(
            f"   ORACLE in loaded_candidates: {bool(oracle_ids) and oracle_ids <= loaded} "
            f"(oracle_chunks={len(oracle_ids)})",
        )
        print(f"   hits={len(hits)} record_keys={[h.citation.record_key for h in hits]}")
        # Autopsy: score the ORACLE chunks under TWO embedding bases to
        # isolate the entity-dilution hypothesis:
        #   (A) relevance_question terms — the CURRENT runtime basis, which
        #       carries the planner-resolved entity ("Real-time Robotics").
        #   (B) raw user question terms — the CALIBRATION basis the harness
        #       used to pre-commit the 0.48 floor.
        # If the oracle passes the floor under (B) but not (A), the fix is to
        # embed the raw question, not the ranking query.
        qp = profile_query(
            relevance_question,
            entities=plan.retrieval_entities,
            intent=plan.intent,
        )
        basis_a = " ".join(qp.terms)
        basis_b = " ".join(profile_query(question).terms)
        print(f"   basis_A(relevance)={basis_a!r}")
        print(f"   basis_B(raw)={basis_b!r}")
        print(f"   profile: intent={qp.intent} entities={qp.entities} "
              f"def_keys={len(qp.definition_record_keys)}")
        vec_a = await service._query_vector(basis_a)
        vec_b = await service._query_vector(basis_b)
        jdump = __import__("json").dumps
        async with uow.factory() as session:
            oracle_rows = (await session.execute(text("""
                SELECT c.display_text,
                  greatest(0,1-(c.embedding <=> CAST(:va AS vector))) score_a,
                  greatest(0,1-(c.embedding <=> CAST(:vb AS vector))) score_b
                FROM chunks c
                JOIN active_search_generations g
                  ON g.generation_id = c.generation_id
                WHERE c.lifecycle='active' AND c.record_key = :oracle
            """), {"va": jdump(vec_a), "vb": jdump(vec_b), "oracle": oracle})).all()
        support = tuple(dict.fromkeys((*plan.expansions, *plan.retrieval_queries)))
        for display_text, score_a, score_b in oracle_rows:
            verdicts = []
            for vec in (float(score_a), float(score_b)):
                r = candidate_relevance_score(
                    qp, text=str(display_text), record_key=oracle,
                    base_score=0.03, vector_score=vec, min_vector_score=0.15,
                    support_queries=support, semantic_floor=0.48,
                )
                verdicts.append("None(EXCL)" if r is None else f"{r:.3f}")
            print(
                f"   ORACLE vec_A={float(score_a):.4f} scorer_A={verdicts[0]} "
                f"| vec_B={float(score_b):.4f} scorer_B={verdicts[1]} "
                f"| {str(display_text)[:60]!r}",
            )
        if not hits:
            print("   NO HITS")
        for rank, hit in enumerate(hits, 1):
            marker = " <-- ORACLE" if hit.citation.record_key == oracle else ""
            print(
                f"   #{rank:>2} {hit.citation.record_key:<14} "
                f"lex={hit.lexical_score:.3f} vec={hit.vector_score:.3f} "
                f"fusion={hit.fusion_score:.3f}{marker}",
            )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(_run()))
