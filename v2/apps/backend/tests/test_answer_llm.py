import asyncio
import json

import httpx
import pytest

from rtr_copilot.config import Settings
from rtr_copilot.rag.adapters import OfflineExtractiveAnswer, StrictEvidenceAnswer
from rtr_copilot.rag.answer_llm import (
    InsufficientEvidence,
    OpenAIAnswerClient,
    QualityLLMAnswer,
    UnavailableLLMAnswer,
    answer_quality_readiness,
    build_answer_provider,
)
from rtr_copilot.rag.models import ProviderAnswer, ProviderEvidence
from rtr_copilot.rag.provider_usage import ProviderUsage


def settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "postgres_dsn": "postgresql://user:password@localhost:5432/db",
        "redis_url": "redis://localhost:6379/0",
        "s3_endpoint": "http://localhost:9000",
        "s3_access_key": "local",
        "s3_secret_key": "local-secret",
        "s3_bucket": "rtr-test",
        "app_env": "development",
        # Hermetic: developer-shell credentials and policy must never alter
        # provider-selection unit tests.
        "openai_api_key": "",
        "anthropic_api_key": "",
        "rag_external_classification_allowlist": "",
        "rag_provider_mode": "local",
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


def evidence() -> list[ProviderEvidence]:
    return [ProviderEvidence(
        marker="C1",
        text="VEGA is RtR's tactical heavy-lift UAV platform.",
        provenance_level="approved_internal",
        verification_state="approved",
        freshness_state="current",
    )]


def response_payload(body: dict[str, object]) -> dict[str, object]:
    return {
        "status": "completed",
        "usage": {
            "input_tokens": 120,
            "input_tokens_details": {"cached_tokens": 40},
            "output_tokens": 30,
            "output_tokens_details": {"reasoning_tokens": 10},
            "total_tokens": 150,
        },
        "output": [{"type": "message", "content": [{
            "type": "output_text",
            "text": json.dumps(body),
        }]}],
    }


def transport(payloads: list[dict[str, object]]) -> httpx.MockTransport:
    queue = list(payloads)

    def handler(request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        assert sent["store"] is False
        assert sent["prompt_cache_key"].startswith("rtr-")
        assert sent["reasoning"]["effort"] == "high"
        assert sent["text"]["format"]["type"] == "json_schema"
        if sent["text"]["format"]["name"] == "rtr_grounded_answer":
            assert "useful partial content" in sent["instructions"]
            assert "best_effort" in sent["instructions"]
            assert "does not provide that detail" in sent["instructions"]
        if sent["text"]["format"]["name"] == "rtr_answer_review":
            assert "supported partial answer" in sent["instructions"]
            assert "complete supported member list" in sent["instructions"]
            assert "invent missing attributes" in sent["instructions"]
        return httpx.Response(200, json=queue.pop(0))

    return httpx.MockTransport(handler)


def test_openai_responses_generates_and_reviews_structured_answer() -> None:
    client = OpenAIAnswerClient(
        "key", "gpt-5.6-sol", timeout=5, reasoning_effort="high",
        max_output_tokens=1024,
        transport=transport([
            response_payload({
                "answerable": True,
                "answer": "VEGA is RtR's tactical heavy-lift UAV platform. [C1]",
                "used_markers": ["C1"],
                "follow_ups": [],
                "reason": "supported",
            }),
            response_payload({"accept": True, "reason": "supported"}),
        ]),
    )
    async def generate_with_usage() -> tuple[ProviderAnswer, ProviderUsage]:
        candidate = await client.generate(
            "What is VEGA?", evidence(), system_policy="Use supplied evidence only.",
        )
        return candidate, client.last_usage()

    candidate, usage = asyncio.run(generate_with_usage())
    assert candidate.used_markers == ["C1"]
    assert usage.input_tokens == 120
    assert usage.cached_input_tokens == 40
    assert usage.reasoning_tokens == 10
    assert usage.total_tokens == 150
    assert asyncio.run(client.review("What is VEGA?", evidence(), candidate))


def test_openai_uses_medium_reasoning_for_governed_enumeration() -> None:
    observed: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent = json.loads(request.content)
        observed.append(sent["reasoning"]["effort"])
        return httpx.Response(200, json=response_payload({
            "answerable": True,
            "answer": "VEGA is a governed product. [C1]",
            "used_markers": ["C1"],
            "follow_ups": [],
            "reason": "supported",
        }))

    client = OpenAIAnswerClient(
        "key", "gpt-5.6-sol", timeout=5, reasoning_effort="high",
        max_output_tokens=1024,
        transport=httpx.MockTransport(handler),
    )
    asyncio.run(client.generate(
        "Which products?",
        evidence(),
        system_policy=(
            "Use supplied evidence only. Intent=enumeration; "
            "completeness=exhaustive; answer_shape=list."
        ),
    ))
    assert observed == ["medium"]


class FakeClient:
    def __init__(
        self,
        name: str,
        *,
        fail_generate: bool = False,
        fail_review: bool = False,
        accept: bool = True,
    ) -> None:
        self.name = name
        self.model = f"{name}-model"
        self.fail_generate = fail_generate
        self.fail_review = fail_review
        self.accept = accept
        self.generated = 0
        self.reviewed = 0

    async def generate(
        self,
        question: str,
        items: list[ProviderEvidence],
        *,
        system_policy: str,
    ) -> ProviderAnswer:
        del question, items, system_policy
        self.generated += 1
        if self.fail_generate:
            raise RuntimeError("provider failed")
        return ProviderAnswer(
            answer="VEGA is a tactical heavy-lift platform. [C1]",
            used_markers=["C1"],
        )

    async def review(
        self,
        question: str,
        items: list[ProviderEvidence],
        candidate: ProviderAnswer,
    ) -> bool:
        del question, items, candidate
        self.reviewed += 1
        if self.fail_review:
            raise RuntimeError("reviewer failed")
        return self.accept


def test_quality_router_falls_back_and_uses_separate_review_route() -> None:
    primary = FakeClient("primary", fail_generate=True)
    fallback = FakeClient("fallback")
    router = QualityLLMAnswer([primary, fallback])
    result = asyncio.run(router.answer(
        "What is VEGA?", evidence(), system_policy="evidence only",
    ))
    assert result.used_markers == ["C1"]
    assert primary.generated == 1 and fallback.generated == 1
    assert primary.reviewed == 1
    assert router.name == "fallback" and router.calls == 3


def test_quality_router_all_generation_failures_are_not_review_rejections() -> None:
    router = QualityLLMAnswer([
        FakeClient("primary", fail_generate=True),
        FakeClient("fallback", fail_generate=True),
    ])
    with pytest.raises(InsufficientEvidence, match="provider_unavailable"):
        asyncio.run(router.answer(
            "What is VEGA?", evidence(), system_policy="evidence only",
        ))
    assert router.calls == 2


def test_quality_router_uses_dedicated_bounded_reviewer() -> None:
    generator = FakeClient("generator")
    reviewer = FakeClient("reviewer")
    router = QualityLLMAnswer([generator], reviewers=[reviewer])
    result = asyncio.run(router.answer(
        "What is VEGA?", evidence(), system_policy="evidence only",
    ))
    assert result.used_markers == ["C1"]
    assert generator.generated == 1 and generator.reviewed == 0
    assert reviewer.generated == 0 and reviewer.reviewed == 1
    assert router.calls == 2


def test_quality_router_preserves_complex_review_rejection_as_advisory() -> None:
    router = QualityLLMAnswer(
        [FakeClient("generator")],
        reviewers=[FakeClient("reviewer", accept=False)],
    )
    result = asyncio.run(router.answer(
        "What is VEGA?", evidence(), system_policy="evidence only",
    ))
    assert result.review_state == "advisory_rejected"


def test_quality_router_skips_advisory_review_for_point_lookup() -> None:
    reviewer = FakeClient("reviewer", accept=False)
    router = QualityLLMAnswer(
        [FakeClient("generator")],
        reviewers=[reviewer],
    )
    async def answer_with_usage() -> tuple[ProviderAnswer, int]:
        router.begin_request_usage()
        result = await router.answer(
            "What is VEGA?",
            evidence(),
            system_policy=(
                "Use supplied evidence only. Intent=lookup; completeness=point; "
                "answer_shape=direct."
            ),
        )
        return result, router.request_usage()

    result, request_calls = asyncio.run(answer_with_usage())
    assert result.review_state == "not_reviewed"
    assert result.used_markers == ["C1"]
    assert reviewer.reviewed == 0
    assert request_calls == 1


def test_quality_router_does_not_call_broken_reviewer_for_point_lookup() -> None:
    reviewer = FakeClient("reviewer", fail_review=True)
    router = QualityLLMAnswer(
        [FakeClient("generator")],
        reviewers=[reviewer],
    )
    result = asyncio.run(router.answer(
        "What is VEGA?",
        evidence(),
        system_policy=(
            "Use supplied evidence only. Intent=definition; completeness=point; "
            "answer_shape=direct."
        ),
    ))
    assert result.review_state == "not_reviewed"
    assert reviewer.reviewed == 0


def test_quality_router_request_usage_is_task_local() -> None:
    router = QualityLLMAnswer([FakeClient("generator")])

    async def run_one() -> int:
        router.begin_request_usage()
        await router.answer("What is VEGA?", evidence(), system_policy="evidence only")
        return router.request_usage()

    async def run_both() -> list[int]:
        return list(await asyncio.gather(run_one(), run_one()))

    usage = asyncio.run(run_both())
    assert usage == [2, 2]
    assert router.calls == 4


def test_builder_separates_high_quality_generator_from_bounded_reviewer() -> None:
    provider = build_answer_provider(settings(
        rag_provider_mode="external",
        rag_external_classification_allowlist="internal",
        openai_api_key="configured-secret",
    ))
    assert isinstance(provider, QualityLLMAnswer)
    assert provider.reviewers is not None
    generator = provider.clients[0]
    reviewer = provider.reviewers[0]
    assert generator is not reviewer
    assert isinstance(generator, OpenAIAnswerClient)
    assert isinstance(reviewer, OpenAIAnswerClient)
    assert generator._reasoning_effort == "high"
    assert reviewer._reasoning_effort == "low"
    assert reviewer._max_output_tokens == 256


def test_required_mode_builds_strict_evidence_fallback_without_credentials() -> None:
    provider = build_answer_provider(settings())
    assert isinstance(provider, StrictEvidenceAnswer)
    result = asyncio.run(provider.answer(
        "What is VEGA?", evidence(), system_policy="Use supplied evidence only.",
    ))
    assert result.used_markers == ["C1"]
    assert "tactical heavy-lift" in result.answer
    assert provider.calls == 1


def test_external_quality_mode_never_downgrades_to_evidence_only() -> None:
    provider = build_answer_provider(settings(
        rag_provider_mode="external",
        rag_external_classification_allowlist="internal",
        openai_api_key="",
        anthropic_api_key="",
    ))
    assert isinstance(provider, UnavailableLLMAnswer)
    assert provider.reason == "answer_quality_configuration_required"


def test_local_extract_only_when_requirement_explicitly_disabled() -> None:
    provider = build_answer_provider(settings(rag_answer_llm_required=False))
    assert isinstance(provider, OfflineExtractiveAnswer)


def test_answer_quality_readiness_requires_policy_and_credential() -> None:
    assert answer_quality_readiness(settings()) == "evidence_only"
    assert answer_quality_readiness(settings(
        rag_provider_mode="external",
        rag_external_classification_allowlist="internal",
        openai_api_key="",
    )) == "configuration_required"
    configured = settings(
        rag_provider_mode="external",
        rag_external_classification_allowlist="internal",
        openai_api_key="configured-secret",
    )
    assert answer_quality_readiness(configured) == "ready"
