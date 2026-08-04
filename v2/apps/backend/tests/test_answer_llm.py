import asyncio
import json

import httpx
import pytest

from rtr_copilot.config import Settings
from rtr_copilot.rag.adapters import OfflineExtractiveAnswer
from rtr_copilot.rag.answer_llm import (
    InsufficientEvidence,
    OpenAIAnswerClient,
    QualityLLMAnswer,
    UnavailableLLMAnswer,
    answer_quality_readiness,
    build_answer_provider,
)
from rtr_copilot.rag.models import ProviderAnswer, ProviderEvidence


def settings(**overrides: object) -> Settings:
    base: dict[str, object] = {
        "postgres_dsn": "postgresql://user:password@localhost:5432/db",
        "redis_url": "redis://localhost:6379/0",
        "s3_endpoint": "http://localhost:9000",
        "s3_access_key": "local",
        "s3_secret_key": "local-secret",
        "s3_bucket": "rtr-test",
        "app_env": "development",
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
        assert sent["reasoning"]["effort"] == "high"
        assert sent["text"]["format"]["type"] == "json_schema"
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
    candidate = asyncio.run(client.generate(
        "What is VEGA?", evidence(), system_policy="Use supplied evidence only.",
    ))
    assert candidate.used_markers == ["C1"]
    assert asyncio.run(client.review("What is VEGA?", evidence(), candidate))


class FakeClient:
    def __init__(
        self,
        name: str,
        *,
        fail_generate: bool = False,
        accept: bool = True,
    ) -> None:
        self.name = name
        self.model = f"{name}-model"
        self.fail_generate = fail_generate
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


def test_required_mode_never_builds_local_fallback() -> None:
    provider = build_answer_provider(settings())
    assert isinstance(provider, UnavailableLLMAnswer)
    with pytest.raises(InsufficientEvidence):
        asyncio.run(provider.answer("q", evidence(), system_policy="evidence only"))
    assert provider.calls == 0


def test_local_extract_only_when_requirement_explicitly_disabled() -> None:
    provider = build_answer_provider(settings(rag_answer_llm_required=False))
    assert isinstance(provider, OfflineExtractiveAnswer)


def test_answer_quality_readiness_requires_policy_and_credential() -> None:
    assert answer_quality_readiness(settings()) == "configuration_required"
    configured = settings(
        rag_provider_mode="external",
        rag_external_classification_allowlist="internal",
        openai_api_key="configured-secret",
    )
    assert answer_quality_readiness(configured) == "ready"
