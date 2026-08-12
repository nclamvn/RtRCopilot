"""Quality-first grounded-answer providers for TIP-024.6.

External LLM generation remains the preferred path.  When its approved policy
or credentials are unavailable, runtime degrades to a deliberately narrow,
verbatim evidence-only answer rather than making the whole product unusable or
allowing a lower-confidence generative fallback.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from contextvars import ContextVar
from typing import Any, Literal, Protocol

import httpx
from pydantic import SecretStr

from rtr_copilot.config import Settings
from rtr_copilot.rag.adapters import (
    AnswerAdapter,
    OfflineExtractiveAnswer,
    StrictEvidenceAnswer,
)
from rtr_copilot.rag.models import ProviderAnswer, ProviderEvidence
from rtr_copilot.rag.provider_usage import EMPTY_PROVIDER_USAGE, ProviderUsage

OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses"
ANTHROPIC_MESSAGES_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"


def _prompt_cache_key(route: str, model: str) -> str:
    """Stable, non-PII routing key for provider-side prompt caching."""
    digest = hashlib.sha256(f"rtr-copilot:{route}:{model}:v1".encode()).hexdigest()
    return f"rtr-{route}-{digest[:32]}"


def _max_output_for_policy(configured: int, system_policy: str) -> int:
    """Right-size output headroom without truncating dossier/list answers."""
    if "governed entity-profile request" in system_policy:
        return min(configured, 3072)
    if "Intent=lookup" in system_policy and "completeness=point" in system_policy:
        return min(configured, 1024)
    if "Intent=definition" in system_policy:
        return min(configured, 1536)
    return configured

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
        "- do not emit an uncited factual heading, lead-in or standalone verdict; "
        "attach its evidence marker or make it a non-factual label\n"
        "- distinguish similarly named products and state material conflicts\n"
        "- collection membership and detailed attributes are separate coverage "
        "questions: when membership is supported but a member's requested detail "
        "is not, keep the member in the answer and explicitly say the supplied "
        "evidence does not provide that detail\n"
        "- a truthful, clearly labelled lack of detail is useful partial content, "
        "not a reason to discard otherwise supported facts\n"
        "- for best_effort coverage, set answerable=true whenever at least one "
        "material part of the request is supported; answer that part and never "
        "present it as complete\n"
        "- set answerable=false only when no material part is supported, evidence "
        "is irrelevant, or a material conflict cannot be resolved\n"
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
        "fact and unresolved source conflicts. A useful supported partial answer "
        "is acceptable for an ordinary question; missing detail alone is not a "
        "rejection unless the user explicitly asks for set or dossier coverage "
        "using all, complete, full, exhaustive, tất cả, toàn bộ or đầy đủ. "
        "Do not confuse a single requested attribute such as full legal name, "
        "full address, company email or exact identifier with an exhaustive set. "
        "For an ordinary point lookup, accept a concise direct answer and any "
        "directly supported alternatives (for example general and sales email). "
        "For a governed collection, accept "
        "a complete supported member list that clearly labels unavailable per-item "
        "detail; never require the candidate to invent missing attributes. Output "
        "only the required object."
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
        prompt_cache_enabled: bool = True,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._api_key = api_key
        self.model = model
        self._timeout = timeout
        self._reasoning_effort = reasoning_effort
        self._max_output_tokens = max_output_tokens
        self._prompt_cache_enabled = prompt_cache_enabled
        self._transport = transport
        self._last_usage: ContextVar[ProviderUsage] = ContextVar(
            f"openai_answer_usage_{id(self)}",
            default=EMPTY_PROVIDER_USAGE,
        )

    def last_usage(self) -> ProviderUsage:
        return self._last_usage.get()

    async def _structured(
        self,
        *,
        instructions: str,
        payload: dict[str, Any],
        schema_name: str,
        schema: dict[str, Any],
        reasoning_effort: str | None = None,
        max_output_tokens: int | None = None,
    ) -> str:
        self._last_usage.set(ProviderUsage())
        request_payload: dict[str, Any] = {
            "model": self.model,
            "store": False,
            "reasoning": {
                "effort": reasoning_effort or self._reasoning_effort,
            },
            "max_output_tokens": max_output_tokens or self._max_output_tokens,
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
        }
        if self._prompt_cache_enabled:
            request_payload["prompt_cache_key"] = _prompt_cache_key(
                schema_name,
                self.model,
            )
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
                json=request_payload,
            )
            response.raise_for_status()
            body = response.json()
        self._last_usage.set(ProviderUsage.from_openai(body))
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
        # Direct lookup and governed enumeration are evidence organization
        # tasks, not open-ended analysis. Medium reasoning is both more stable
        # and materially faster for long catalogs; high remains configured for
        # comparison/procedure/analysis where reasoning depth changes quality.
        adaptive_effort = (
            "medium"
            if any(
                marker in system_policy
                for marker in (
                    "Intent=definition",
                    "Intent=lookup",
                    "Intent=enumeration",
                )
            )
            else self._reasoning_effort
        )
        output = await self._structured(
            instructions=_generation_instructions(system_policy),
            payload={"question": question, "evidence": _evidence_payload(evidence)},
            schema_name="rtr_grounded_answer",
            schema=ANSWER_SCHEMA,
            reasoning_effort=adaptive_effort,
            max_output_tokens=_max_output_for_policy(
                self._max_output_tokens,
                system_policy,
            ),
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
        self._last_usage: ContextVar[ProviderUsage] = ContextVar(
            f"anthropic_answer_usage_{id(self)}",
            default=EMPTY_PROVIDER_USAGE,
        )

    def last_usage(self) -> ProviderUsage:
        return self._last_usage.get()

    async def _json(self, system: str, payload: dict[str, Any]) -> str:
        self._last_usage.set(ProviderUsage())
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
            body = response.json()
            blocks = body.get("content", [])
        self._last_usage.set(ProviderUsage.from_anthropic(body))
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
    """Generate with one client and review with a separate route when possible.

    Review is a small binary structured task.  A dedicated reviewer client can
    therefore use a 256-token budget and low reasoning effort without weakening
    the high-reasoning generator. Keeping the routes distinct also prevents a
    compact audit from inheriting the generator's 4K budget and
    turning every ordinary answer into two equally expensive calls.
    """

    name = "quality-llm"
    model = "provider-router"
    breaker_name = "quality-llm"

    def __init__(
        self,
        clients: list[GroundedAnswerClient],
        *,
        reviewers: list[GroundedAnswerClient] | None = None,
        review_mode: Literal["always", "on_demand"] = "always",
    ) -> None:
        self.clients = clients
        self.reviewers = reviewers
        self.review_mode = review_mode
        self.calls = 0
        self._request_calls: ContextVar[int] = ContextVar(
            "quality_llm_request_calls",
            default=0,
        )
        self._request_token_usage: ContextVar[ProviderUsage] = ContextVar(
            "quality_llm_request_token_usage",
            default=EMPTY_PROVIDER_USAGE,
        )
        self._request_generator_index: ContextVar[int] = ContextVar(
            "quality_llm_request_generator_index",
            default=0,
        )

    def begin_request_usage(self) -> None:
        """Reset usage for only the current async request context."""
        self._request_calls.set(0)
        self._request_token_usage.set(ProviderUsage())
        self._request_generator_index.set(0)

    def request_usage(self) -> int:
        return self._request_calls.get()

    def request_provider_usage(self) -> ProviderUsage:
        usage = self._request_token_usage.get()
        return ProviderUsage(
            calls=self._request_calls.get(),
            input_tokens=usage.input_tokens,
            cached_input_tokens=usage.cached_input_tokens,
            output_tokens=usage.output_tokens,
            reasoning_tokens=usage.reasoning_tokens,
            total_tokens=usage.total_tokens,
        )

    def _record_call(self) -> None:
        self.calls += 1
        self._request_calls.set(self._request_calls.get() + 1)

    def _record_tokens(self, client: object) -> None:
        usage_reader = getattr(client, "last_usage", None)
        if not callable(usage_reader):
            return
        usage = usage_reader()
        if not isinstance(usage, ProviderUsage):
            return
        self._request_token_usage.set(
            self._request_token_usage.get()
            + ProviderUsage(
                input_tokens=usage.input_tokens,
                cached_input_tokens=usage.cached_input_tokens,
                output_tokens=usage.output_tokens,
                reasoning_tokens=usage.reasoning_tokens,
                total_tokens=usage.total_tokens,
            )
        )

    async def answer(
        self,
        question: str,
        evidence: Sequence[ProviderEvidence],
        *,
        system_policy: str,
    ) -> ProviderAnswer:
        if not self.clients:
            raise InsufficientEvidence("provider_unavailable")
        generator_failures: list[str] = []
        for index, generator in enumerate(self.clients):
            try:
                self._record_call()
                candidate = await generator.generate(
                    question,
                    evidence,
                    system_policy=system_policy,
                )
            except InsufficientEvidence:
                # TIP-030: the model answered "not answerable" — a domain
                # verdict, not a transport failure. Trying another generator
                # on identical evidence is legitimate; record the verdict so
                # exhaustion reports it distinctly from provider errors.
                self._record_tokens(generator)
                generator_failures.append("declined")
                continue
            except Exception as failure:  # noqa: BLE001 — provider fallback
                self._record_tokens(generator)
                generator_failures.append(type(failure).__name__)
                continue
            self._record_tokens(generator)
            self._request_generator_index.set(index)
            # Point/direct answers still pass deterministic citation, evidence
            # overlap, entity and relevance gates in AnswerService. The LLM
            # reviewer is advisory and cannot change final acceptance, so a
            # second provider call here cannot improve the release decision.
            if (
                "completeness=point" in system_policy
                and "answer_shape=direct" in system_policy
            ):
                self.name = generator.name
                self.model = generator.model
                return candidate
            if self.review_mode == "on_demand":
                # AnswerService first applies every deterministic trust gate.
                # It calls ``review_candidate`` only when exact lexical support
                # cannot establish a semantically valid paraphrase.
                self.name = generator.name
                self.model = generator.model
                return candidate
            if self.reviewers:
                reviewer = self.reviewers[index % len(self.reviewers)]
            else:
                reviewer = self.clients[(index + 1) % len(self.clients)]
            try:
                self._record_call()
                accepted = await reviewer.review(question, evidence, candidate)
            except Exception:  # noqa: BLE001 — review transport/parse failure
                self._record_tokens(reviewer)
                self.name = generator.name
                self.model = generator.model
                return candidate.model_copy(update={"review_state": "advisory_rejected"})
            self._record_tokens(reviewer)
            if accepted:
                self.name = generator.name
                self.model = generator.model
                return candidate.model_copy(update={"review_state": "accepted"})
            # The reviewer is an independent semantic signal, not the final
            # availability authority. Live enterprise acceptance demonstrated
            # repeatable false negatives on correct multi-facet definitions.
            # Preserve the rejection for audit, then let AnswerService's
            # mandatory deterministic citation, evidence-overlap, entity,
            # profile and collection-coverage gates decide. This does not turn
            # missing or irrelevant evidence into a grounded answer.
            self.name = generator.name
            self.model = generator.model
            return candidate.model_copy(update={"review_state": "advisory_rejected"})
        # Every configured generator failed before a candidate existed. This is
        # a provider failure, not an advisory-review outcome; AnswerService must
        # not spend its grounding-repair attempt by calling the same failed
        # route again. TIP-030: name the per-generator failure classes so
        # campaign diagnostics can separate payload rejections from declines.
        detail = "_".join(generator_failures) or "no_generators"
        raise InsufficientEvidence(f"provider_unavailable_{detail}")

    async def review_candidate(
        self,
        question: str,
        evidence: Sequence[ProviderEvidence],
        candidate: ProviderAnswer,
    ) -> ProviderAnswer:
        """Run the bounded semantic reviewer for this request's generator.

        A rejection or reviewer transport failure is advisory and never grants
        support. Deterministic grounding will re-check the returned state and
        fail closed unless the reviewer explicitly accepted the paraphrase.
        """
        if candidate.review_state != "not_reviewed":
            return candidate
        index = self._request_generator_index.get()
        if self.reviewers:
            reviewer = self.reviewers[index % len(self.reviewers)]
        elif self.clients:
            reviewer = self.clients[(index + 1) % len(self.clients)]
        else:
            return candidate.model_copy(update={"review_state": "advisory_rejected"})
        try:
            self._record_call()
            accepted = await reviewer.review(question, evidence, candidate)
        except Exception:  # noqa: BLE001 — bounded reviewer is advisory
            self._record_tokens(reviewer)
            return candidate.model_copy(update={"review_state": "advisory_rejected"})
        self._record_tokens(reviewer)
        return candidate.model_copy(update={
            "review_state": "accepted" if accepted else "advisory_rejected",
        })


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


AnswerQualityReadiness = Literal[
    "ready", "evidence_only", "configuration_required",
]


def _credential_configured(value: SecretStr | None) -> bool:
    """True only for a non-empty secret; Compose commonly injects ``""``."""
    if value is None:
        return False
    return bool(str(value.get_secret_value()).strip())


def answer_quality_readiness(settings: Settings) -> AnswerQualityReadiness:
    """Return a non-secret operational capability state for health surfaces."""
    allowlist = {
        item.strip()
        for item in settings.rag_external_classification_allowlist.split(",")
        if item.strip()
    }
    configured_provider = (
        _credential_configured(settings.openai_api_key)
        or (
            _credential_configured(settings.anthropic_api_key)
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
    if settings.rag_answer_llm_required and settings.rag_provider_mode == "external":
        return "configuration_required"
    return "evidence_only"


def build_answer_provider(settings: Settings) -> AnswerAdapter:
    """Prefer reviewed LLM synthesis and fail closed in external-quality mode.

    Local/test mode retains the narrow strict-evidence adapter. Once operators
    explicitly select external processing, however, a missing policy or secret
    is a configuration error—not permission to silently downgrade answer
    quality.
    """
    if not settings.rag_answer_llm_required:
        return OfflineExtractiveAnswer()
    if settings.rag_provider_mode != "external":
        return StrictEvidenceAnswer()
    allowlist = {
        item.strip()
        for item in settings.rag_external_classification_allowlist.split(",")
        if item.strip()
    }
    if "internal" not in allowlist:
        return UnavailableLLMAnswer("answer_quality_policy_required")

    clients: list[GroundedAnswerClient] = []
    reviewers: list[GroundedAnswerClient] = []
    if _credential_configured(settings.openai_api_key):
        assert settings.openai_api_key is not None
        openai_key = settings.openai_api_key.get_secret_value()
        clients.append(OpenAIAnswerClient(
            openai_key,
            settings.rag_answer_openai_model,
            timeout=settings.rag_answer_timeout_seconds,
            reasoning_effort=settings.rag_answer_reasoning_effort,
            max_output_tokens=settings.rag_answer_max_output_tokens,
            prompt_cache_enabled=settings.rag_prompt_cache_enabled,
        ))
        reviewers.append(OpenAIAnswerClient(
            openai_key,
            settings.rag_review_openai_model or settings.rag_answer_openai_model,
            timeout=settings.rag_answer_timeout_seconds,
            reasoning_effort=settings.rag_review_reasoning_effort,
            max_output_tokens=settings.rag_review_max_output_tokens,
            prompt_cache_enabled=settings.rag_prompt_cache_enabled,
        ))
    if (
        _credential_configured(settings.anthropic_api_key)
        and settings.rag_answer_anthropic_model is not None
    ):
        assert settings.anthropic_api_key is not None
        anthropic_key = settings.anthropic_api_key.get_secret_value()
        clients.append(AnthropicAnswerClient(
            anthropic_key,
            settings.rag_answer_anthropic_model,
            timeout=settings.rag_answer_timeout_seconds,
            max_output_tokens=settings.rag_answer_max_output_tokens,
        ))
        reviewers.append(AnthropicAnswerClient(
            anthropic_key,
            settings.rag_answer_anthropic_model,
            timeout=settings.rag_answer_timeout_seconds,
            max_output_tokens=settings.rag_review_max_output_tokens,
        ))
    if not clients:
        return UnavailableLLMAnswer("answer_quality_configuration_required")
    if len(reviewers) > 1:
        # Prefer a different provider family for the independent review when
        # both approved routes exist; retain same-provider low-cost review as a
        # reliable single-credential deployment mode.
        reviewers = [*reviewers[1:], reviewers[0]]
    return QualityLLMAnswer(
        clients,
        reviewers=reviewers,
        review_mode=settings.rag_review_mode,
    )
