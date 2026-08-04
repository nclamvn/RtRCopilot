"""Quality-first external grounded-answer providers for TIP-024.6.

The runtime contract is deliberately fail-closed.  When quality LLM mode is
required, missing policy/credentials or provider failures raise and the caller
records an honest-null.  The local extractive adapter is never selected as a
runtime fallback.
"""

from __future__ import annotations

import json
from collections.abc import Sequence
from typing import Any, Literal, Protocol

import httpx

from rtr_copilot.config import Settings
from rtr_copilot.rag.adapters import AnswerAdapter, OfflineExtractiveAnswer
from rtr_copilot.rag.models import ProviderAnswer, ProviderEvidence

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"

ANSWER_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "answerable": {"type": "boolean"},
        "answer": {"type": "string"},
        "used_markers": {
            "type": "array",
            "items": {"type": "string", "pattern": "^C[0-9]+$"},
            "maxItems": 20,
        },
        "follow_ups": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": 3,
        },
        "reason": {
            "type": "string",
            "enum": ["supported", "insufficient", "conflicting", "irrelevant"],
        },
    },
    "required": ["answerable", "answer", "used_markers", "follow_ups", "reason"],
    "additionalProperties": False,
}

REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "accept": {"type": "boolean"},
        "reason": {
            "type": "string",
            "enum": [
                "supported", "wrong_entity", "off_topic", "unsupported",
                "missing_citation", "conflicting", "incomplete",
            ],
        },
    },
    "required": ["accept", "reason"],
    "additionalProperties": False,
}


class InsufficientEvidence(ValueError):
    pass


def _generation_instructions(system_policy: str) -> str:
    return (
        "Role: grounded enterprise answerer for Real-time Robotics.\n"
        "Goal: answer the user's exact question from the supplied evidence.\n"
        "Success criteria:\n"
        "- use only relevant supplied evidence; ignore irrelevant records\n"
        "- preserve the language of the user's question\n"
        "- every factual sentence ends with one or more exact [C#] markers\n"
        "- distinguish similarly named products and state material conflicts\n"
        "- set answerable=false when evidence is insufficient, irrelevant or "
        "cannot resolve a conflict\n"
        "- never infer missing specifications, dates, owners or commercial facts\n"
        "Output only the required structured object. "
        f"Security policy: {system_policy}"
    )


def _review_instructions() -> str:
    return (
        "You are an independent grounded-answer quality reviewer. Accept only if "
        "the candidate directly answers the original question, uses the correct "
        "product/entity, contains no irrelevant facts, and every factual unit is "
        "supported by the cited evidence marker. Reject uncertainty disguised as "
        "fact and unresolved source conflicts. Output only the required object."
    )


def _evidence_payload(evidence: Sequence[ProviderEvidence]) -> list[dict[str, Any]]:
    return [item.model_dump(mode="json") for item in evidence]


def _parse_answer_text(text: str) -> ProviderAnswer:
    payload = json.loads(text)
    if not isinstance(payload, dict) or payload.get("answerable") is not True:
        reason = payload.get("reason", "insufficient") if isinstance(payload, dict) else "invalid"
        raise InsufficientEvidence(str(reason))
    answer = payload.get("answer")
    markers = payload.get("used_markers")
    follow_ups = payload.get("follow_ups", [])
    if not isinstance(answer, str) or not isinstance(markers, list):
        raise ValueError("invalid_answer_payload")
    return ProviderAnswer(
        answer=answer.strip(),
        used_markers=[item for item in markers if isinstance(item, str)],
        follow_ups=[item for item in follow_ups if isinstance(item, str)],
    )


def _parse_review_text(text: str) -> bool:
    payload = json.loads(text)
    return isinstance(payload, dict) and payload.get("accept") is True


def _openai_output_text(payload: dict[str, Any]) -> str:
    for item in payload.get("output", []):
        if not isinstance(item, dict) or item.get("type") != "message":
            continue
        for block in item.get("content", []):
            if isinstance(block, dict) and block.get("type") == "output_text":
                value = block.get("text")
                if isinstance(value, str):
                    return value
    raise ValueError("openai_output_text_missing")


class GroundedAnswerClient(Protocol):
    name: str
    model: str

    async def generate(
        self,
        question: str,
        evidence: Sequence[ProviderEvidence],
        *,
        system_policy: str,
    ) -> ProviderAnswer: ...

    async def review(
        self,
        question: str,
        evidence: Sequence[ProviderEvidence],
        candidate: ProviderAnswer,
    ) -> bool: ...


class OpenAIAnswerClient:
    name = "openai"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout: float,
        reasoning_effort: str,
        max_output_tokens: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._timeout = timeout
        self._reasoning_effort = reasoning_effort
        self._max_output_tokens = max_output_tokens
        self._transport = transport

    async def _structured(
        self,
        *,
        instructions: str,
        payload: dict[str, Any],
        schema_name: str,
        schema: dict[str, Any],
    ) -> str:
        async with httpx.AsyncClient(
            timeout=self._timeout,
            transport=self._transport,
        ) as client:
            response = await client.post(
                OPENAI_RESPONSES_URL,
                headers={
                    "authorization": f"Bearer {self._api_key}",
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "store": False,
                    "reasoning": {"effort": self._reasoning_effort},
                    "max_output_tokens": self._max_output_tokens,
                    "instructions": instructions,
                    "input": json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
                    "text": {
                        "verbosity": "medium",
                        "format": {
                            "type": "json_schema",
                            "name": schema_name,
                            "strict": True,
                            "schema": schema,
                        },
                    },
                },
            )
            response.raise_for_status()
            body = response.json()
        if body.get("status") != "completed":
            raise ValueError("openai_response_incomplete")
        return _openai_output_text(body)

    async def generate(
        self,
        question: str,
        evidence: Sequence[ProviderEvidence],
        *,
        system_policy: str,
    ) -> ProviderAnswer:
        output = await self._structured(
            instructions=_generation_instructions(system_policy),
            payload={"question": question, "evidence": _evidence_payload(evidence)},
            schema_name="rtr_grounded_answer",
            schema=ANSWER_SCHEMA,
        )
        return _parse_answer_text(output)

    async def review(
        self,
        question: str,
        evidence: Sequence[ProviderEvidence],
        candidate: ProviderAnswer,
    ) -> bool:
        output = await self._structured(
            instructions=_review_instructions(),
            payload={
                "question": question,
                "evidence": _evidence_payload(evidence),
                "candidate": candidate.model_dump(mode="json"),
            },
            schema_name="rtr_answer_review",
            schema=REVIEW_SCHEMA,
        )
        return _parse_review_text(output)


class AnthropicAnswerClient:
    name = "anthropic"

    def __init__(
        self,
        api_key: str,
        model: str,
        *,
        timeout: float,
        max_output_tokens: int,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._timeout = timeout
        self._max_output_tokens = max_output_tokens
        self._transport = transport

    async def _json(self, system: str, payload: dict[str, Any]) -> str:
        async with httpx.AsyncClient(
            timeout=self._timeout,
            transport=self._transport,
        ) as client:
            response = await client.post(
                ANTHROPIC_MESSAGES_URL,
                headers={
                    "x-api-key": self._api_key,
                    "anthropic-version": ANTHROPIC_VERSION,
                    "content-type": "application/json",
                },
                json={
                    "model": self.model,
                    "max_tokens": self._max_output_tokens,
                    "temperature": 0,
                    "system": system,
                    "messages": [{
                        "role": "user",
                        "content": json.dumps(
                            payload, ensure_ascii=False, separators=(",", ":"),
                        ),
                    }],
                },
            )
            response.raise_for_status()
            blocks = response.json().get("content", [])
        output = "".join(
            block.get("text", "")
            for block in blocks
            if isinstance(block, dict) and block.get("type") == "text"
        )
        start, end = output.find("{"), output.rfind("}")
        return output[start:end + 1] if 0 <= start < end else output

    async def generate(
        self,
        question: str,
        evidence: Sequence[ProviderEvidence],
        *,
        system_policy: str,
    ) -> ProviderAnswer:
        system = (
            _generation_instructions(system_policy)
            + " JSON Schema: " + json.dumps(ANSWER_SCHEMA, separators=(",", ":"))
        )
        output = await self._json(
            system,
            {"question": question, "evidence": _evidence_payload(evidence)},
        )
        return _parse_answer_text(output)

    async def review(
        self,
        question: str,
        evidence: Sequence[ProviderEvidence],
        candidate: ProviderAnswer,
    ) -> bool:
        system = (
            _review_instructions()
            + " JSON Schema: " + json.dumps(REVIEW_SCHEMA, separators=(",", ":"))
        )
        output = await self._json(
            system,
            {
                "question": question,
                "evidence": _evidence_payload(evidence),
                "candidate": candidate.model_dump(mode="json"),
            },
        )
        return _parse_review_text(output)


class QualityLLMAnswer:
    """Generate with one client and review with a separate route when possible."""

    name = "quality-llm"
    model = "provider-router"
    breaker_name = "quality-llm"

    def __init__(self, clients: list[GroundedAnswerClient]) -> None:
        self.clients = clients
        self.calls = 0

    async def answer(
        self,
        question: str,
        evidence: Sequence[ProviderEvidence],
        *,
        system_policy: str,
    ) -> ProviderAnswer:
        if not self.clients:
            raise InsufficientEvidence("provider_unavailable")
        for index, generator in enumerate(self.clients):
            try:
                self.calls += 1
                candidate = await generator.generate(
                    question,
                    evidence,
                    system_policy=system_policy,
                )
                reviewer = self.clients[(index + 1) % len(self.clients)]
                self.calls += 1
                accepted = await reviewer.review(question, evidence, candidate)
            except Exception:  # noqa: BLE001 — try configured provider fallback
                continue
            if accepted:
                self.name = generator.name
                self.model = generator.model
                return candidate
        raise InsufficientEvidence("quality_review_failed")


class UnavailableLLMAnswer:
    name = "unavailable"
    model = "none"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        self.calls = 0

    async def answer(
        self,
        question: str,
        evidence: Sequence[ProviderEvidence],
        *,
        system_policy: str,
    ) -> ProviderAnswer:
        del question, evidence, system_policy
        raise InsufficientEvidence(self.reason)


AnswerQualityReadiness = Literal["ready", "configuration_required"]


def answer_quality_readiness(settings: Settings) -> AnswerQualityReadiness:
    """Return a non-secret operational capability state for health surfaces."""
    allowlist = {
        item.strip()
        for item in settings.rag_external_classification_allowlist.split(",")
        if item.strip()
    }
    configured_provider = (
        settings.openai_api_key is not None
        or (
            settings.anthropic_api_key is not None
            and settings.rag_answer_anthropic_model is not None
        )
    )
    if (
        settings.rag_answer_llm_required
        and settings.rag_provider_mode == "external"
        and "internal" in allowlist
        and configured_provider
    ):
        return "ready"
    return "configuration_required"


def build_answer_provider(settings: Settings) -> AnswerAdapter:
    """Build the runtime provider without a quality-degrading fallback."""
    if not settings.rag_answer_llm_required:
        return OfflineExtractiveAnswer()
    if settings.rag_provider_mode != "external":
        return UnavailableLLMAnswer("external_mode_required")
    allowlist = {
        item.strip()
        for item in settings.rag_external_classification_allowlist.split(",")
        if item.strip()
    }
    if "internal" not in allowlist:
        return UnavailableLLMAnswer("internal_export_not_allowed")

    clients: list[GroundedAnswerClient] = []
    if settings.openai_api_key is not None:
        clients.append(OpenAIAnswerClient(
            settings.openai_api_key.get_secret_value(),
            settings.rag_answer_openai_model,
            timeout=settings.rag_answer_timeout_seconds,
            reasoning_effort=settings.rag_answer_reasoning_effort,
            max_output_tokens=settings.rag_answer_max_output_tokens,
        ))
    if (
        settings.anthropic_api_key is not None
        and settings.rag_answer_anthropic_model is not None
    ):
        clients.append(AnthropicAnswerClient(
            settings.anthropic_api_key.get_secret_value(),
            settings.rag_answer_anthropic_model,
            timeout=settings.rag_answer_timeout_seconds,
            max_output_tokens=settings.rag_answer_max_output_tokens,
        ))
    if not clients:
        return UnavailableLLMAnswer("provider_credentials_missing")
    return QualityLLMAnswer(clients)
