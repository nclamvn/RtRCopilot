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
    classify_intent,
    plan_query,
    requests_exhaustive,
    resolve_entities,
    understand,
    validate_entities,
)


class _StubRewriter:
    """Test double returning a fixed proposal."""

    def __init__(self, result: RewriteResult) -> None:
        self._result = result
        self.calls = 0
        self.questions: list[str] = []

    async def rewrite(self, question: str) -> RewriteResult:
        self.calls += 1
        self.questions.append(question)
        return self._result


class _FailingRewriter:
    calls = 0

    async def rewrite(self, question: str) -> RewriteResult:
        self.calls += 1
        raise RuntimeError("provider exploded")


class _SlowRewriter:
    calls = 0

    async def rewrite(self, question: str) -> RewriteResult:
        self.calls += 1
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


class TestPointAttributeRequests:
    def test_rename_question_is_not_exhaustive(self) -> None:
        assert requests_exhaustive("HeraLink giờ gọi là gì rồi?") is False


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

    def test_colloquial_structure_question_requires_procedural_synthesis(self) -> None:
        for question in (
            "SOT bên mình tổ chức sao",
            "quy trình này vận hành sao",
            "hệ thống hoạt động như nào",
        ):
            assert classify_intent(question) == "procedure"

    def test_full_legal_name_is_a_point_attribute_not_a_complete_set(self) -> None:
        question = "cty mình tên pháp nhân đầy đủ là gì vậy?"
        assert classify_intent(question) == "lookup"
        assert requests_exhaustive(question) is False

    def test_company_email_is_a_point_lookup(self) -> None:
        assert classify_intent("email cty là gì?") == "lookup"

    def test_brand_philosophy_is_a_point_lookup(self) -> None:
        assert classify_intent("triết lý thương hiệu bên mình là gì") == "lookup"

    def test_technical_stack_is_a_point_lookup(self) -> None:
        assert classify_intent("nó dùng tech stack gì?") == "lookup"

    def test_external_planner_cannot_promote_point_attribute_to_definition(self) -> None:
        stub = _StubRewriter(RewriteResult(
            entities=["Real-time Robotics"],
            intent="definition",
            answer_shape="direct",
        ))
        plan = asyncio.run(plan_query("triết lý thương hiệu bên mình là gì", stub))
        assert plan.intent == "lookup"

    def test_explicit_complete_product_list_remains_exhaustive(self) -> None:
        question = "liệt kê đầy đủ các sản phẩm của RtR"
        assert classify_intent(question) == "enumeration"
        assert requests_exhaustive(question) is True


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
        # TIP-029.2: bare "hr" is now a weak alias (governed ambiguity), so
        # this contract keeps its original purpose — expansion bounding and
        # additivity — on corroborated shorthand instead.
        out = asyncio.run(understand("hr mtow", stub))
        assert "HERA" in out and "payload" in out and "endurance" in out
        assert "x" * 999 not in out  # over-length expansion dropped
        assert out.startswith("hr mtow")

    def test_bare_weak_alias_rejects_llm_entity_confirmation(self) -> None:
        # TIP-029.2: the SAFE-007 leak also ran through the LLM-confirmation
        # route — a planner proposing HERA for bare "hr" must be refused just
        # like the deterministic resolver refuses it.
        stub = _StubRewriter(RewriteResult(entities=["HERA"]))
        out = asyncio.run(understand("hr", stub))
        assert "HERA" not in out

    def test_deterministic(self) -> None:
        stub = _StubRewriter(RewriteResult(entities=["HERA", "VEGA"]))
        first = asyncio.run(understand("compare them", stub))
        second = asyncio.run(understand("compare them", stub))
        assert first == second


class TestConversationPlanning:
    def test_external_planner_receives_bounded_history_and_resolves_follow_up(
        self,
    ) -> None:
        rewriter = _StubRewriter(RewriteResult(
            entities=["HERA"],
            intent="lookup",
            completeness="point",
            answer_shape="direct",
            retrieval_queries=["HERA flight endurance"],
            standalone_question="HERA bay được bao lâu?",
        ))
        plan = asyncio.run(plan_query(
            "thế nó bay được bao lâu?",
            rewriter,
            conversation_context=(
                "user: HERA là gì?",
                (
                    "assistant: HERA là nền tảng UAV đa nhiệm, dùng HeraHub "
                    "và HeraSight LR. [C1]"
                ),
            ),
        ))
        assert "<conversation_history>" in rewriter.questions[0]
        assert "<current_question>" in rewriter.questions[0]
        assert plan.entities == ("HERA",)
        assert plan.resolved_question == "HERA bay được bao lâu?"
        assert plan.context_message_count == 2
        assert plan.retrieval_query.startswith("thế nó bay được bao lâu?")
        assert "HERA bay được bao lâu?" in plan.retrieval_query
        audit = plan.audit_metadata()
        assert audit["context_message_count"] == 2
        assert "HERA bay được bao lâu?" not in repr(audit)

    def test_offline_fallback_does_not_consume_conversation_history(self) -> None:
        plan = asyncio.run(plan_query(
            "thế nó bay được bao lâu?",
            OfflineRewriter(),
            conversation_context=("user: HERA là gì?",),
        ))
        assert plan.resolved_question == "thế nó bay được bao lâu?"
        assert plan.context_message_count == 0
        assert "HERA" not in plan.retrieval_query


def test_exact_governed_definition_bypasses_external_planner_without_quality_loss() -> None:
    rewriter = _StubRewriter(RewriteResult(entities=["VEGA"]))
    plan = asyncio.run(plan_query("HERA là gì?", rewriter))
    assert rewriter.calls == 0
    assert plan.planner_source == "deterministic"
    assert plan.entities == ("HERA",)
    assert plan.resolution_state == "resolved"
    assert plan.profile_facets


class TestTokenBoundaryPunctuation:
    """TIP-029.1: sentence punctuation at token edges must not hide entities.

    Root cause of the TIP-029 RECALL-MISS class: TOKEN_RE keeps interior
    dots/hyphens for identifiers, so ``…Real-time Robotics.)`` tokenized as
    ``robotics.`` and neither the alias map nor the ontology surface index
    matched — a canonical mention became invisible to resolution, relevance
    and lexical retrieval at once.
    """

    def test_parenthesized_source_mention_resolves(self):
        assert resolve_entities("(Nguồn: Real-time Robotics.)") == [
            "Real-time Robotics",
        ]

    def test_sentence_final_product_with_trailing_dot_resolves(self):
        out = resolve_entities("OmniSight (DualSight).")
        assert out == ["OmniSight", "DualSight"]

    def test_interior_identifier_dots_survive(self):
        from rtr_copilot.rag.adapters import normalize_query
        assert "next.js" in normalize_query("dùng Next.js và Sanity.")
        assert "l3r.2.005" in normalize_query("mã L3R.2.005.")

    def test_edge_stripped_token_still_alias_mapped(self):
        from rtr_copilot.rag.adapters import normalize_query
        assert normalize_query("(Nguồn: Real-time Robotics.)") == \
            normalize_query("Nguồn: Real-time Robotics")


class TestWeakAliasAmbiguityGuard:
    """TIP-029.2: curated shorthand with a common outside meaning ("hr").

    SAFE-007 trap: "HR là gì?" must never be confidently answered as HERA —
    run 1 refused it only by LLM luck, run 2 answered (false-grounded). The
    weak-alias guard makes the refusal deterministic and pre-provider while
    preserving every TIP-014 contextual-alias contract.
    """

    def test_bare_weak_alias_identity_question_does_not_resolve(self):
        assert resolve_entities("HR là gì?") == []

    def test_bare_weak_alias_is_reported_as_governed_ambiguity(self):
        from rtr_copilot.rag.query_understanding import (
            uncorroborated_weak_surfaces,
        )
        assert uncorroborated_weak_surfaces("HR là gì?") == ("hr",)
        assert uncorroborated_weak_surfaces("hr payload capacity") == ()

    def test_bare_weak_alias_plan_requires_clarification(self):
        plan = asyncio.run(plan_query("HR là gì?", OfflineRewriter()))
        assert plan.resolution_state == "clarification_required"

    def test_corroborated_weak_alias_still_resolves_hera(self):
        # TIP-014 contracts: shorthand with product context keeps working.
        assert resolve_entities("hr payload capacity") == ["HERA"]
        assert resolve_entities("pin hr bao nhiêu vôn") == ["HERA"]
        plan = asyncio.run(plan_query("hr payload capacity", OfflineRewriter()))
        assert plan.resolution_state == "resolved"

    def test_strong_short_aliases_are_untouched(self):
        assert resolve_entities("VGA là gì") == ["VEGA"]
        assert resolve_entities("CRM bên mình làm gì?") == [
            "RtR CRM", "Real-time Robotics",
        ]
        assert resolve_entities("HERA là gì") == ["HERA"]

    def test_weak_alias_may_not_shadow_a_strong_surface(self):
        import pytest

        from rtr_copilot.rag.ontology import OntologyEntity
        with pytest.raises(Exception, match="shadows_strong_surface"):
            OntologyEntity(
                entity_id="rtr.test.dup",
                canonical_name="Dup",
                entity_type="product",
                domain="products",
                aliases=["dup-alias"],
                weak_aliases=["dup-alias"],
                owner="test",
                provenance_level="approved_internal",
            )
