import hashlib
import math
import re
import unicodedata
from collections.abc import Sequence
from typing import TYPE_CHECKING, Protocol

import httpx

from rtr_copilot.rag.models import ProviderAnswer, ProviderEvidence

if TYPE_CHECKING:
    from rtr_copilot.config import Settings

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
    # TOKEN_RE deliberately keeps interior dots/hyphens ("next.js",
    # "l3r.2.005", "real-time") but that let sentence punctuation contaminate
    # token EDGES: "…Real-time Robotics.)" tokenized as "robotics." so neither
    # the alias map nor the ontology surface index matched, and a perfectly
    # canonical entity mention became invisible to resolve_entities /
    # relevance / lexical retrieval (TIP-029 RECALL-MISS root cause). Strip
    # punctuation only at token boundaries; interior identifiers are intact.
    tokens = (
        stripped
        for token in TOKEN_RE.findall(folded)
        if (stripped := token.strip("._-"))
    )
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

    def __init__(self, dimension: int = 1536) -> None:
        # Default tracks the schema dimension (TIP-014RE migration 0013);
        # callers normally pass Settings.rag_embedding_dimension explicitly
        # via build_embedding_adapter.
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

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


OPENAI_EMBEDDINGS_URL = "https://api.openai.com/v1/embeddings"
# One HTTP request may carry many inputs; OpenAI accepts up to 2048 but a
# conservative page keeps request bodies small and retries cheap.
EMBEDDING_BATCH_SIZE = 128


class EmbeddingProviderError(RuntimeError):
    """Provider embedding failed; callers degrade to lexical-only retrieval."""


class OpenAIEmbedding:
    """Real semantic embeddings (TIP-014RE, closes TIP-014 AC-2).

    Trust surface: constructing this adapter is gated by
    ``Settings.rag_embedding_provider`` + the external-export policy validator
    (key AND ``internal`` in the classification allowlist) — the same
    fail-closed doctrine as the LLM rewrite path, because indexing sends
    corpus text and querying sends the user question to the provider.

    Vectors are L2-normalized on receipt so pgvector cosine scores are
    comparable regardless of provider-side conventions.
    """

    version = "1"

    def __init__(
        self,
        *,
        api_key: str,
        model: str,
        dimension: int,
        timeout_seconds: float,
        transport: httpx.MockTransport | None = None,
    ) -> None:
        self.model = model
        self.dimension = dimension
        self._api_key = api_key
        self._timeout = timeout_seconds
        # Test seam only: MockTransport serves both sync and async clients.
        self._transport = transport

    def _payload(self, texts: Sequence[str]) -> dict[str, object]:
        return {
            "model": self.model,
            "input": list(texts),
            "dimensions": self.dimension,
            "encoding_format": "float",
        }

    def _headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._api_key}"}

    def _vectors(self, body: dict[str, object], expected: int) -> list[list[float]]:
        data = body.get("data")
        if not isinstance(data, list) or len(data) != expected:
            raise EmbeddingProviderError("embedding_response_shape")
        rows = sorted(data, key=lambda item: int(item.get("index", 0)))
        vectors: list[list[float]] = []
        for row in rows:
            values = row.get("embedding")
            if not isinstance(values, list) or len(values) != self.dimension:
                raise EmbeddingProviderError("embedding_dimension_mismatch")
            vector = [float(value) for value in values]
            norm = math.sqrt(sum(value * value for value in vector))
            vectors.append(
                [value / norm for value in vector] if norm else vector,
            )
        return vectors

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """Synchronous batch embedding for the reindex/backfill path."""
        if not texts:
            return []
        vectors: list[list[float]] = []
        with httpx.Client(
            timeout=self._timeout, transport=self._transport,
        ) as client:
            for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
                page = list(texts[start:start + EMBEDDING_BATCH_SIZE])
                try:
                    response = client.post(
                        OPENAI_EMBEDDINGS_URL,
                        headers=self._headers(),
                        json=self._payload(page),
                    )
                    response.raise_for_status()
                except httpx.HTTPError as exc:
                    raise EmbeddingProviderError(
                        f"embedding_http_{type(exc).__name__}",
                    ) from exc
                vectors.extend(self._vectors(response.json(), len(page)))
        return vectors

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    async def aembed(self, text: str) -> list[float]:
        """Async single-text embedding for the query path (own timeout)."""
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport,
        ) as client:
            try:
                response = await client.post(
                    OPENAI_EMBEDDINGS_URL,
                    headers=self._headers(),
                    json=self._payload([text]),
                )
                response.raise_for_status()
            except httpx.HTTPError as exc:
                raise EmbeddingProviderError(
                    f"embedding_http_{type(exc).__name__}",
                ) from exc
        return self._vectors(response.json(), 1)[0]


def build_embedding_adapter(
    settings: "Settings",
) -> "OfflineHashEmbedding | OpenAIEmbedding":
    """Resolve the configured embedding adapter, fail-closed.

    The Settings validator already rejects ``rag_embedding_provider="openai"``
    without a key + ``internal`` allowlist, so reaching the provider branch
    here means policy was explicitly satisfied. The guard is repeated anyway:
    an adapter must never be buildable from a Settings object that bypassed
    validation (e.g. ``model_construct`` in tests).
    """
    if settings.rag_embedding_provider == "offline":
        return OfflineHashEmbedding(settings.rag_embedding_dimension)
    api_key = settings.openai_api_key
    allowlist = {
        item.strip().lower()
        for item in settings.rag_external_classification_allowlist.split(",")
        if item.strip()
    }
    if api_key is None or "internal" not in allowlist:
        raise ValueError("rag_embedding_provider:policy_required")
    return OpenAIEmbedding(
        api_key=api_key.get_secret_value(),
        model=settings.rag_embedding_openai_model,
        dimension=settings.rag_embedding_dimension,
        timeout_seconds=settings.rag_embedding_timeout_seconds,
    )


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
