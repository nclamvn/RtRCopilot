"""Hermetic unit tests for TIP-014 Phase 1 query understanding.

No DB, no network, no provider. Proves: real product variants resolve to the
right canonical; the fuzzy net catches unlisted typos but stays strict; NO false
entity is ever emitted (the resolver's range is exactly the curated set); and
augmentation is additive + deterministic + grounding-neutral.
"""
import asyncio

from rtr_copilot.rag.product_aliases import PRODUCT_ALIASES
from rtr_copilot.rag.query_understanding import (
    FUZZY_THRESHOLD,
    OfflineRewriter,
    RewriteResult,
    augment_query,
    resolve_entities,
    understand,
    validate_entities,
)


class _StubRewriter:
    """Test double returning a fixed proposal."""

    def __init__(self, result: RewriteResult) -> None:
        self._result = result

    async def rewrite(self, question: str) -> RewriteResult:
        return self._result


class _FailingRewriter:
    async def rewrite(self, question: str) -> RewriteResult:
        raise RuntimeError("provider exploded")


class _SlowRewriter:
    async def rewrite(self, question: str) -> RewriteResult:
        await asyncio.sleep(10)
        return RewriteResult()


class TestExactResolution:
    def test_canonical_mention(self) -> None:
        assert resolve_entities("HERA payload") == ["HERA"]

    def test_diacritics_and_casing_folded(self) -> None:
        # "Hera là gì?" -> normalized "hera la gi" -> HERA
        assert resolve_entities("Hera là gì?") == ["HERA"]

    def test_vietnamese_around_entity(self) -> None:
        assert resolve_entities("thông số VEGA là gì") == ["VEGA"]

    def test_compound_prefers_longest(self) -> None:
        # "hera sight" must be HeraSight, not HERA
        assert resolve_entities("HeraSight 61MP sensor") == ["HeraSight"]

    def test_three_token_compound(self) -> None:
        assert resolve_entities("HeraSight LR spec") == ["HeraSight LR"]

    def test_multiple_entities_in_order(self) -> None:
        assert resolve_entities("so sánh HeraHub và HERA") == ["HeraHub", "HERA"]


class TestAbbreviationAndVariant:
    def test_abbreviation_hr(self) -> None:
        assert resolve_entities("hr payload capacity") == ["HERA"]

    def test_typo_hira(self) -> None:
        assert resolve_entities("hira mtow") == ["HERA"]

    def test_typo_heara(self) -> None:
        assert resolve_entities("heara weight") == ["HERA"]

    def test_abbreviation_vga(self) -> None:
        assert resolve_entities("vga giá bao nhiêu") == ["VEGA"]

    def test_technical_name_61t(self) -> None:
        assert resolve_entities("61t sensor") == ["HeraSight LR"]

    def test_former_name_heralink(self) -> None:
        assert resolve_entities("heralink controller") == ["HeraHub"]


class TestFuzzyNetIsStrict:
    def test_unlisted_typo_resolves(self) -> None:
        # "herra" (double r) is not listed but is within threshold of "hera"
        assert resolve_entities("herra endurance") == ["HERA"]

    def test_near_word_below_threshold_does_not_resolve(self) -> None:
        # "mega" ~0.75 vs "vega" — must NOT resolve
        assert resolve_entities("mega pixel camera") == []

    def test_common_word_does_not_resolve(self) -> None:
        assert resolve_entities("what is the weather today") == []


class TestNoFalseEntities:
    def test_hr_inside_word_not_split(self) -> None:
        # "human resources" has no standalone "hr" token
        assert resolve_entities("human resources team policy") == []

    def test_resolver_range_is_curated_set(self) -> None:
        # Whatever a batch of varied questions produces, every emitted name is a
        # curated canonical — the resolver can never invent an entity.
        canonicals = set(PRODUCT_ALIASES.keys())
        probes = [
            "hr", "hira mtow", "human resources", "vega vs hera",
            "insight report", "sight line", "mega drone", "aero tunnel test",
            "dualsight thermal", "unknown gizmo 9000",
        ]
        for probe in probes:
            assert set(resolve_entities(probe)) <= canonicals


class TestAugmentation:
    def test_appends_canonical_for_abbreviation(self) -> None:
        out = augment_query("hr payload")
        assert out.startswith("hr payload")
        assert "HERA" in out

    def test_no_change_when_name_already_present(self) -> None:
        assert augment_query("HERA payload") == "HERA payload"

    def test_no_change_when_nothing_resolves(self) -> None:
        assert augment_query("weather forecast today") == "weather forecast today"

    def test_original_terms_preserved(self) -> None:
        out = augment_query("hira endurance range")
        # user terms are never removed
        for term in ("hira", "endurance", "range"):
            assert term in out

    def test_deterministic(self) -> None:
        question = "hira vs vga comparison"
        assert augment_query(question) == augment_query(question)

    def test_multiple_variants_both_appended(self) -> None:
        out = augment_query("hira vs vga")
        assert "HERA" in out and "VEGA" in out


class TestInvariants:
    def test_threshold_is_strict(self) -> None:
        assert FUZZY_THRESHOLD >= 0.85

    def test_empty_and_punctuation_safe(self) -> None:
        assert resolve_entities("") == []
        assert augment_query("") == ""
        assert resolve_entities("???") == []


class TestEntityGuard:
    def test_keeps_registered_drops_unknown(self) -> None:
        # An LLM hallucinating "human resources" from "hr" must be stripped.
        assert validate_entities(["HERA", "human resources", "VEGA"]) == [
            "HERA", "VEGA",
        ]

    def test_all_unknown_yields_empty(self) -> None:
        assert validate_entities(["Acme", "Skynet", "human resources"]) == []

    def test_dedups(self) -> None:
        assert validate_entities(["HERA", "HERA"]) == ["HERA"]


class TestUnderstand:
    def test_offline_rewriter_matches_augment_query(self) -> None:
        # With the shipped offline rewriter the pipeline == Phase 1 exactly.
        for question in ("hr payload", "HERA payload", "weather", "hira vs vga"):
            out = asyncio.run(understand(question, OfflineRewriter()))
            assert out == augment_query(question)

    def test_valid_rewrite_entities_are_applied(self) -> None:
        stub = _StubRewriter(RewriteResult(entities=["HERA"]))
        out = asyncio.run(understand("hr thing", stub))
        assert "HERA" in out and out.startswith("hr thing")

    def test_hallucinated_entity_is_dropped(self) -> None:
        # non-resolving question isolates the guard: only the LLM proposes, and
        # its unregistered entity must be dropped.
        stub = _StubRewriter(RewriteResult(entities=["human resources"]))
        out = asyncio.run(understand("tell me about it", stub))
        assert "human resources" not in out
        assert out == "tell me about it"  # nothing valid to add

    def test_deterministic_resolution_never_lost(self) -> None:
        # even when the LLM returns nothing, Phase 1 alias resolution still applies
        stub = _StubRewriter(RewriteResult(entities=[], expansions=[]))
        out = asyncio.run(understand("hira mtow", stub))
        assert out == augment_query("hira mtow")
        assert "HERA" in out

    def test_failure_falls_back_to_deterministic(self) -> None:
        out = asyncio.run(understand("hira mtow", _FailingRewriter()))
        assert out == augment_query("hira mtow")
        assert "HERA" in out

    def test_timeout_falls_back_to_deterministic(self) -> None:
        out = asyncio.run(understand("vga price", _SlowRewriter(), timeout=0.05))
        assert out == augment_query("vga price")
        assert "VEGA" in out

    def test_expansions_bounded_and_additive(self) -> None:
        stub = _StubRewriter(RewriteResult(
            entities=["HERA"],
            expansions=["payload", "  ", "x" * 999, "endurance"],
        ))
        out = asyncio.run(understand("hr", stub))
        assert "HERA" in out and "payload" in out and "endurance" in out
        assert "x" * 999 not in out  # over-length expansion dropped
        assert out.startswith("hr")

    def test_deterministic(self) -> None:
        stub = _StubRewriter(RewriteResult(entities=["HERA", "VEGA"]))
        first = asyncio.run(understand("compare them", stub))
        second = asyncio.run(understand("compare them", stub))
        assert first == second
