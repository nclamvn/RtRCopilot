"""Hermetic tests for the discriminative OR lexical-query builder.

OR search preserves recall for meaningful terms while Vietnamese/English
function words are removed so they cannot manufacture relevance.
"""
from rtr_copilot.rag.adapters import lexical_query, normalize_query


def test_or_joins_terms() -> None:
    assert lexical_query("hera la gi") == "hera"


def test_natural_language_question_end_to_end() -> None:
    # "Hera là gì?" -> normalized -> OR query that still contains "hera"
    built = lexical_query(normalize_query("Hera là gì?"))
    assert built == "hera"
    assert "hera" in built.split(" | ")


def test_dedupes_preserving_order() -> None:
    assert lexical_query("hera payload hera") == "hera | payload"


def test_single_term() -> None:
    assert lexical_query("hera") == "hera"


def test_empty_is_empty() -> None:
    assert lexical_query("") == ""


def test_all_stopwords_is_empty() -> None:
    assert lexical_query(normalize_query("là gì và ở đâu")) == ""


def test_compound_token_is_split_into_lexemes() -> None:
    # identifiers split into OR'd alphanumeric lexemes (still matchable)
    assert lexical_query("l3f.ent.002") == "l3f | ent | 002"


def test_no_tsquery_operators_leak() -> None:
    # only lexemes and ' | ' separators — never a raw '&' or '!' from input
    built = lexical_query(normalize_query("hera & vega ! test"))
    assert "&" not in built
    assert "!" not in built
    assert "hera" in built and "vega" in built and "test" in built
