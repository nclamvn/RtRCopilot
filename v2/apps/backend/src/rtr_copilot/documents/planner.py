"""Deterministic, bounded artifact-intent planning for TIP-036.

This module deliberately performs no generation and has no corpus, connector or
provider dependency. It decides whether a user is asking to create an artifact
and ranks already-authorized template metadata supplied by Document OS.
"""

import re
import unicodedata
from dataclasses import dataclass

from rtr_copilot.documents.models import ArtifactKind, ArtifactPlanState, TemplateListItem

TOKEN = re.compile(r"[a-z0-9]+")

STRONG_CREATE_PHRASES = (
    "tao", "tao cho", "soan", "soan thao", "xuat",
    "chuan bi", "draft", "create", "generate", "prepare", "make", "write",
)
WEAK_CREATE_PHRASES = ("lam", "lam cho", "lap")
INTERROGATIVE_PREFIXES = (
    "ai ", "cai gi ", "tai sao ", "vi sao ", "khi nao ", "o dau ", "how ",
    "who ", "why ", "when ", "where ",
)

KIND_PHRASES: dict[ArtifactKind, tuple[str, ...]] = {
    "presentation": (
        "slide", "slides", "deck", "presentation", "ppt", "pptx", "thuyet trinh",
    ),
    "spreadsheet": (
        "bang tinh", "excel", "xlsx", "workbook", "spreadsheet",
    ),
    "report": (
        "bao cao", "report", "brief", "memo", "tong hop", "phan tich",
        "fact sheet", "factsheet",
    ),
    "form": (
        "bieu mau", "form", "phieu", "checklist", "mau dien",
    ),
    "document": (
        "tai lieu", "van ban", "document", "docx", "thu", "de xuat", "proposal",
        "hop dong", "contract", "ho so", "cong van", "letter",
    ),
}

FORMAT_AFFINITY: dict[ArtifactKind, tuple[str, ...]] = {
    "presentation": ("pptx",),
    "spreadsheet": ("xlsx",),
    "report": ("docx", "xlsx", "pdf", "pptx"),
    "form": ("xlsx", "docx", "pdf"),
    "document": ("docx", "pdf", "xlsx", "pptx"),
}


@dataclass(frozen=True)
class ArtifactIntent:
    state: ArtifactPlanState
    kind: ArtifactKind | None
    normalized_instruction: str


def normalize_artifact_text(value: str) -> str:
    folded = unicodedata.normalize("NFKD", value.casefold()).replace("đ", "d")
    ascii_text = "".join(character for character in folded if not unicodedata.combining(character))
    return " ".join(TOKEN.findall(ascii_text))


def _contains_phrase(text: str, phrase: str) -> bool:
    return f" {phrase} " in f" {text} "


def interpret_artifact_intent(instruction: str) -> ArtifactIntent:
    normalized = normalize_artifact_text(instruction)
    matches = [
        kind for kind, phrases in KIND_PHRASES.items()
        if any(_contains_phrase(normalized, phrase) for phrase in phrases)
    ]
    has_strong_creation = any(
        _contains_phrase(normalized, phrase) for phrase in STRONG_CREATE_PHRASES
    )
    has_weak_creation = bool(matches) and any(
        _contains_phrase(normalized, phrase) for phrase in WEAK_CREATE_PHRASES
    )
    looks_interrogative = normalized.startswith(INTERROGATIVE_PREFIXES)
    looks_passive = " duoc tao " in f" {normalized} "
    if looks_interrogative or looks_passive or not (has_strong_creation or has_weak_creation):
        return ArtifactIntent("not_applicable", None, normalized)
    if not matches:
        return ArtifactIntent("clarification_required", None, normalized)
    return ArtifactIntent("ready", matches[0], normalized)


def rank_template_items(
    intent: ArtifactIntent,
    items: list[TemplateListItem],
) -> list[TemplateListItem]:
    if intent.state != "ready" or intent.kind is None:
        return []
    query_tokens = set(TOKEN.findall(intent.normalized_instruction))
    affinity = FORMAT_AFFINITY[intent.kind]

    def metadata_for(item: TemplateListItem) -> str:
        return normalize_artifact_text(
            f"{item.display_name} {item.category} {item.stable_key}"
        )

    def compatible(item: TemplateListItem) -> bool:
        metadata = metadata_for(item)
        detected_kinds = {
            kind for kind, phrases in KIND_PHRASES.items()
            if any(_contains_phrase(metadata, phrase) for phrase in phrases)
        }
        if item.format == "xlsx":
            detected_kinds.add("spreadsheet")
        elif item.format == "pptx":
            detected_kinds.add("presentation")
        # A known template type must match the requested artifact kind.  This
        # prevents broad format affinity (for example DOCX) from presenting a
        # government letter as a generic company report.
        return intent.kind in detected_kinds

    def score(item: TemplateListItem) -> tuple[int, int, str, str]:
        metadata = metadata_for(item)
        overlap = len(query_tokens & set(TOKEN.findall(metadata)))
        try:
            format_score = len(affinity) - affinity.index(item.format)
        except ValueError:
            format_score = 0
        return (
            format_score * 10 + overlap * 4,
            overlap,
            normalize_artifact_text(item.display_name),
            str(item.version_id),
        )

    # Higher semantic/format scores first; lexical/id tie-breakers keep output stable.
    return sorted(
        (item for item in items if compatible(item)),
        key=lambda item: (
            -score(item)[0], -score(item)[1], score(item)[2], score(item)[3],
        ),
    )
