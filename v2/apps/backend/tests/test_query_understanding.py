"""Hermetic unit tests for TIP-014 Phase 1 query understanding.

No DB, no network, no provider. Proves: real product variants resolve to the
right canonical; the fuzzy net catches unlisted typos but stays strict; NO false
entity is ever emitted (the resolver's range is exactly the curated set); and
augmentation is additive + deterministic + grounding-neutral.
"""
from rtr_copilot.rag.product_aliases import PRODUCT_ALIASES
from rtr_copilot.rag.query_understanding import (
    FUZZY_THRESHOLD,
    augment_query,
    resolve_entities,
)


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
