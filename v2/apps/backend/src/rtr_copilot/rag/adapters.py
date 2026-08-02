import hashlib
import math
import re
import unicodedata
from collections.abc import Sequence
from typing import Protocol

from rtr_copilot.rag.models import ProviderAnswer, ProviderEvidence

TOKEN_RE = re.compile(r"[a-z0-9][a-z0-9._-]*")
# Split conventional CamelCase without changing exact identifiers such as
# ``L3F.ENT.002`` where an uppercase letter follows a digit.
CAMEL_RE = re.compile(r"(?<=[a-z])(?=[A-Z])")
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
        if token not in seen:
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
