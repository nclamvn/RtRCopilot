"""Hermetic tests for the OR lexical-query builder (honest-null retrieval fix).

The bug: plainto_tsquery ANDs every term, so a terse fact chunk containing
"hera" but not "là"/"gì" scored 0 for the natural-language query "hera là gì"
and was dropped -> honest-null. lexical_query builds an OR tsquery so any term
contributes.
"""
from rtr_copilot.rag.adapters import lexical_query, normalize_query


def test_or_joins_terms() -> None:
    assert lexical_query("hera la gi") == "hera | la | gi"


def test_natural_language_question_end_to_end() -> None:
    # "Hera là gì?" -> normalized -> OR query that still contains "hera"
    built = lexical_query(normalize_query("Hera là gì?"))
    assert built == "hera | la | gi"
    assert "hera" in built.split(" | ")


def test_dedupes_preserving_order() -> None:
    assert lexical_query("hera payload hera") == "hera | payload"


def test_single_term() -> None:
    assert lexical_query("hera") == "hera"


def test_empty_is_empty() -> None:
    assert lexical_query("") == ""


def test_compound_token_is_split_into_lexemes() -> None:
    # identifiers split into OR'd alphanumeric lexemes (still matchable)
    assert lexical_query("l3f.ent.002") == "l3f | ent | 002"


def test_no_tsquery_operators_leak() -> None:
    # only lexemes and ' | ' separators — never a raw '&' or '!' from input
    built = lexical_query(normalize_query("hera & vega ! test"))
    assert "&" not in built
    assert "!" not in built
    assert "hera" in built and "vega" in built and "test" in built
