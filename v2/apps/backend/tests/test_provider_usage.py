"""Provider-neutral factual usage normalization for TIP-027.5."""

from rtr_copilot.rag.provider_usage import ProviderUsage


def test_openai_usage_preserves_cache_and_reasoning_subsets() -> None:
    usage = ProviderUsage.from_openai({
        "usage": {
            "input_tokens": 100,
            "input_tokens_details": {"cached_tokens": 60},
            "output_tokens": 40,
            "output_tokens_details": {"reasoning_tokens": 25},
            "total_tokens": 140,
        },
    })
    assert usage == ProviderUsage(
        calls=1,
        input_tokens=100,
        cached_input_tokens=60,
        output_tokens=40,
        reasoning_tokens=25,
        total_tokens=140,
    )


def test_anthropic_usage_normalizes_all_input_and_cache_subset() -> None:
    usage = ProviderUsage.from_anthropic({
        "usage": {
            "input_tokens": 20,
            "cache_creation_input_tokens": 30,
            "cache_read_input_tokens": 50,
            "output_tokens": 10,
        },
    })
    assert usage == ProviderUsage(
        calls=1,
        input_tokens=100,
        cached_input_tokens=50,
        output_tokens=10,
        total_tokens=110,
    )


def test_missing_or_invalid_usage_still_records_completed_call() -> None:
    assert ProviderUsage.from_openai({}).calls == 1
    malformed = ProviderUsage.from_anthropic({
        "usage": {"input_tokens": -2, "output_tokens": "bad"},
    })
    assert malformed.calls == 1
    assert malformed.total_tokens == 0
