"""TIP-046.1 · strict record chunks lead with the fact caption."""
from rtr_copilot.rag.reindex import (
    FACT_LABEL_MAX_CHARS,
    FACT_LABEL_SEPARATOR,
    compose_chunk_base,
    stable_split,
)


def test_strict_fact_chunk_carries_caption_then_verbatim_evidence() -> None:
    caption = "Maximum payload capacity · HERA tải trọng tối đa: 14 kg"
    evidence = "Maximum payloads weight: 30 lb(13.6 kg)"
    base = compose_chunk_base(caption, evidence)
    assert base == caption + FACT_LABEL_SEPARATOR + evidence
    assert base.endswith(evidence), "evidence quote must stay verbatim at the tail"
    assert stable_split(base, maximum=800, overlap=80) == [base]


def test_soft_record_without_evidence_is_unchanged() -> None:
    assert compose_chunk_base("  HERA là gì   ", "") == "HERA là gì"


def test_long_prose_record_keeps_evidence_only() -> None:
    prose = "x" * (FACT_LABEL_MAX_CHARS + 1)
    assert compose_chunk_base(prose, "verbatim span") == "verbatim span"


def test_identical_caption_and_evidence_not_duplicated() -> None:
    assert compose_chunk_base("same text", "same  text") == "same text"


def test_empty_record_yields_empty_base() -> None:
    assert compose_chunk_base("", "") == ""
