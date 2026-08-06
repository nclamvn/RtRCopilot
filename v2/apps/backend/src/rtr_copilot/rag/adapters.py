import hashlib
import math
import re
import unicodedata
from collections.abc import Sequence
from typing import Protocol

from rtr_copilot.rag.models import ProviderAnswer, ProviderEvidence

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._-]*")
# Split conventional CamelCase only when the uppercase character starts a
# capitalized word. A terminal/multi-cap acronym such as ``RtR`` must remain
# atomic; the previous lower->upper rule changed it to ``rt r`` and silently
# defeated exact ontology aliases. Exact identifiers such as ``L3F.ENT.002``
# also remain unchanged.
CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z][a-z])")
ALIASES = {
    "uav": "drone",
    "uas": "drone",
    "maybaykhongnguoilai": "drone",
    "thiếtbịbaykhôngngườilái": "drone",
    "robotics": "robot",
    "tựđộng": "autonomous",
}


def normalize_query(value: str) -> str:
    value = CAMEL_RE.sub(" ", value)
    folded = "".join(
        char for char in unicodedata.normalize("NFKD", value.casefold())
        if not unicodedata.combining(char)
    ).replace("đ", "d")
    tokens = TOKEN_RE.findall(folded)
    return " ".join(ALIASES.get(token, token) for token in tokens)


_LEX_TOKEN = re.compile(r"[a-z0-9]+")

# Function words must never manufacture retrieval relevance.  This list is
# intentionally small and language-specific rather than an aggressive stemmer:
# identifiers, product names, measurements and domain verbs remain searchable.
QUERY_STOPWORDS = frozenset({
    "a", "an", "and", "are", "as", "at", "be", "by", "can", "cho", "co",
    "cua", "da", "de", "duoc", "gi", "how", "in", "is", "it", "la",
    "dau", "mot", "nao", "nhung", "o", "of", "on", "or", "the", "thi",
    "va", "ve", "what", "when", "where", "which", "who", "why",
    "with", "ben", "minh", "sao", "vay", "zay", "khong",
})


def lexical_query(normalized: str) -> str:
    """Build an OR ``tsquery`` string ("a | b | c") from a normalized query.

    ``plainto_tsquery`` ANDs every term, so a terse fact chunk that contains
    "hera" but not the function words in "hera là gì" scores 0 and is dropped —
    the honest-null bug on natural-language questions. OR-of-terms lets ANY
    matching term contribute, while ``ts_rank_cd`` still ranks chunks that match
    more terms higher. Deterministic; tokens are already safe lexemes.
    """
    seen: list[str] = []
    for token in _LEX_TOKEN.findall(normalized):
        if token not in QUERY_STOPWORDS and token not in seen:
            seen.append(token)
    return " | ".join(seen)


class EmbeddingAdapter(Protocol):
    model: str
    version: str
    dimension: int

    def embed(self, text: str) -> list[float]: ...


class AnswerAdapter(Protocol):
    name: str
    model: str
    calls: int

    async def answer(
        self,
        question: str,
        evidence: Sequence[ProviderEvidence],
        *,
        system_policy: str,
    ) -> ProviderAnswer: ...


class OfflineHashEmbedding:
    model = "rtr-offline-hash-embedding"
    version = "1"

    def __init__(self, dimension: int = 64) -> None:
        self.dimension = dimension

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        features: list[str] = []
        for token in normalize_query(text).split():
            padded = f"^{token}$"
            features.append(f"w:{token}")
            features.extend(
                f"c:{padded[index:index + 3]}"
                for index in range(max(1, len(padded) - 2))
            )
        for feature in features:
            digest = hashlib.sha256(feature.encode()).digest()
            index = int.from_bytes(digest[:4], "big") % self.dimension
            vector[index] += 1.0 if digest[4] % 2 else -1.0
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector


# Sentence split matching verify_grounding's factual-unit boundary, so every
# emitted sentence can carry its own citation marker.
_SENTENCE_RE = re.compile(r"(?<=[.!?])\s+")


class OfflineExtractiveAnswer:
    name = "local"
    model = "rtr-extractive-v1"

    def __init__(self) -> None:
        self.calls = 0

    async def answer(
        self,
        question: str,
        evidence: Sequence[ProviderEvidence],
        *,
        system_policy: str,
    ) -> ProviderAnswer:
        self.calls += 1
        if not evidence or "evidence only" not in system_policy.casefold():
            raise ValueError("evidence_required")
        selected = evidence[:3]
        # Cite EVERY sentence, not once per block. verify_grounding splits the
        # answer into factual units and requires a marker on each; multi-sentence
        # facts (l3_facts) left the non-final sentences ungrounded -> honest-null.
        statements: list[str] = []
        used: list[str] = []
        for item in selected:
            text = item.text.strip()
            if not text:
                continue
            sentences = [
                sentence.strip()
                for sentence in _SENTENCE_RE.split(text)
                if sentence.strip()
            ] or [text]
            statements.extend(f"{sentence} [{item.marker}]" for sentence in sentences)
            used.append(item.marker)
        return ProviderAnswer(
            answer=" ".join(statements),
            used_markers=used,
            follow_ups=[],
        )


class StrictEvidenceAnswer:
    """A no-inference fallback over one approved, current evidence unit.

    This is intentionally narrower than the legacy local extractor: it emits
    only the highest-ranked eligible chunk, verbatim, with a marker on every
    sentence.  It keeps the product useful without pretending to provide LLM
    synthesis when external processing is unavailable.
    """

    name = "evidence-only"
    model = "rtr-strict-evidence-v1"

    def __init__(self) -> None:
        self.calls = 0

    async def answer(
        self,
        question: str,
        evidence: Sequence[ProviderEvidence],
        *,
        system_policy: str,
    ) -> ProviderAnswer:
        del question
        self.calls += 1
        if "evidence only" not in system_policy.casefold():
            raise ValueError("evidence_required")
        selected = next(
            (
                item
                for item in evidence
                if item.text.strip()
                and item.provenance_level != "claim"
                and item.verification_state in {"verified", "approved"}
                and item.freshness_state == "current"
            ),
            None,
        )
        if selected is None:
            raise ValueError("approved_current_evidence_required")
        sentences = [
            sentence.strip()
            for sentence in _SENTENCE_RE.split(selected.text.strip())
            if sentence.strip()
        ] or [selected.text.strip()]
        return ProviderAnswer(
            answer=" ".join(f"{sentence} [{selected.marker}]" for sentence in sentences),
            used_markers=[selected.marker],
            follow_ups=[],
        )
