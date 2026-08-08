"""Concurrency-safe, provider-neutral LLM usage accounting.

The provider APIs expose token usage only after a response completes.  This
module normalizes those response shapes without embedding a pricing table in
application code.  Pricing changes independently from the trust pipeline;
tokens, cache hits and reasoning usage are durable facts that operators can
price in their billing system of record.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


def _non_negative_int(value: object) -> int:
    if isinstance(value, bool):
        return 0
    if isinstance(value, int):
        return max(0, value)
    if isinstance(value, float):
        return max(0, int(value)) if value.is_integer() else 0
    if not isinstance(value, str):
        return 0
    try:
        return max(0, int(value))
    except ValueError:
        return 0


@dataclass(frozen=True)
class ProviderUsage:
    calls: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    total_tokens: int = 0

    def __add__(self, other: ProviderUsage) -> ProviderUsage:
        return ProviderUsage(
            calls=self.calls + other.calls,
            input_tokens=self.input_tokens + other.input_tokens,
            cached_input_tokens=(
                self.cached_input_tokens + other.cached_input_tokens
            ),
            output_tokens=self.output_tokens + other.output_tokens,
            reasoning_tokens=self.reasoning_tokens + other.reasoning_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )

    @classmethod
    def one_call(cls) -> ProviderUsage:
        return cls(calls=1)

    @classmethod
    def from_openai(cls, payload: dict[str, Any]) -> ProviderUsage:
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return cls.one_call()
        input_details = usage.get("input_tokens_details")
        output_details = usage.get("output_tokens_details")
        input_tokens = _non_negative_int(usage.get("input_tokens"))
        output_tokens = _non_negative_int(usage.get("output_tokens"))
        total_tokens = _non_negative_int(usage.get("total_tokens"))
        return cls(
            calls=1,
            input_tokens=input_tokens,
            cached_input_tokens=_non_negative_int(
                input_details.get("cached_tokens")
                if isinstance(input_details, dict)
                else 0,
            ),
            output_tokens=output_tokens,
            reasoning_tokens=_non_negative_int(
                output_details.get("reasoning_tokens")
                if isinstance(output_details, dict)
                else 0,
            ),
            total_tokens=total_tokens or input_tokens + output_tokens,
        )

    @classmethod
    def from_anthropic(cls, payload: dict[str, Any]) -> ProviderUsage:
        usage = payload.get("usage")
        if not isinstance(usage, dict):
            return cls.one_call()
        input_tokens = _non_negative_int(usage.get("input_tokens"))
        output_tokens = _non_negative_int(usage.get("output_tokens"))
        cached = _non_negative_int(usage.get("cache_read_input_tokens"))
        # Normalize to the OpenAI meaning: input_tokens includes every input
        # token, while cached_input_tokens is the cache-read subset. Anthropic
        # reports ordinary, cache-creation and cache-read input separately.
        cache_creation = _non_negative_int(usage.get("cache_creation_input_tokens"))
        effective_input = input_tokens + cache_creation + cached
        return cls(
            calls=1,
            input_tokens=effective_input,
            cached_input_tokens=cached,
            output_tokens=output_tokens,
            total_tokens=effective_input + output_tokens,
        )

    def audit_dict(self) -> dict[str, int]:
        return {
            "calls": self.calls,
            "input_tokens": self.input_tokens,
            "cached_input_tokens": self.cached_input_tokens,
            "output_tokens": self.output_tokens,
            "reasoning_tokens": self.reasoning_tokens,
            "total_tokens": self.total_tokens,
        }


EMPTY_PROVIDER_USAGE = ProviderUsage()
