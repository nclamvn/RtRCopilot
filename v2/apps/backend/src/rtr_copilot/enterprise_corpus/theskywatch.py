"""Deterministic TheSkyWatch snapshot -> Research package adapter.

The adapter consumes only the normalized, locally built TheSkyWatch exports.
It never crawls, edits the source repository or promotes external research into
company SOT.  Every admitted fact retains its upstream tier and source locator;
null and unverified cells remain honest-null and are not indexed.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast
from urllib.parse import urlparse

from rtr_copilot.governance.models import CorroborationState, ResearchTier
from rtr_copilot.research.package import (
    RefineryEvidence,
    RefineryRecord,
    ResearchManifestMember,
    evidence_checksum,
    research_fingerprint,
    research_payload_sha,
    research_record_sha,
)
from rtr_copilot.sot.package import canonical_json, sha256_bytes

ADAPTER_VERSION = "theskywatch-adapter-1.0"
SOURCE_KEY = "theskywatch.registry"
SCOPE = "Global UAV systems, manufacturers and TheSkyWatch published analysis"
PUBLIC_DATA_URL = "https://theskywatch.com/data"
PUBLIC_ARTICLE_URL = "https://theskywatch.com"
SAFE_KEY = re.compile(r"[^a-z0-9._-]+")
DIRECT_STATUSES = frozenset({"verified", "sourced", "corroborated", "disputed"})
EXCLUDED_STATUSES = frozenset({"unverified", "missing", "rejected"})
TIER_MAP: dict[str, ResearchTier] = {
    "A": "P",
    "B": "S",
    "C": "H",
    "derived": "X",
}


class TheSkyWatchAdapterError(ValueError):
    """Fail-loud adapter error carrying a stable gate code."""

    def __init__(self, code: str, detail: str = "") -> None:
        super().__init__(f"{code}: {detail}" if detail else code)
        self.code = code
        self.detail = detail


@dataclass(frozen=True)
class TheSkyWatchBuildResult:
    staging_name: str
    package_root: Path
    fingerprint: str
    record_count: int
    entity_count: int
    entity_record_count: int
    admitted_field_count: int
    article_count: int
    excluded_null_count: int
    excluded_unverified_count: int
    tier_counts: dict[str, int]
    corroboration_counts: dict[str, int]
    source_registry_sha256: str


@dataclass(frozen=True)
class _Cell:
    field: str
    value: Any
    status: str
    confidence: str | None
    source_tier: str
    research_tier: ResearchTier
    sources: list[dict[str, Any]]


def _load_object(path: Path, code: str) -> dict[str, Any]:
    if not path.is_file():
        raise TheSkyWatchAdapterError(code, str(path))
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TheSkyWatchAdapterError("snapshot_json_invalid", path.name) from error
    if not isinstance(value, dict):
        raise TheSkyWatchAdapterError("snapshot_schema_invalid", path.name)
    return cast(dict[str, Any], value)


def _load_array(path: Path, code: str) -> list[dict[str, Any]]:
    if not path.is_file():
        raise TheSkyWatchAdapterError(code, str(path))
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TheSkyWatchAdapterError("snapshot_json_invalid", path.name) from error
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise TheSkyWatchAdapterError("snapshot_schema_invalid", path.name)
    return cast(list[dict[str, Any]], value)


def _canonical_snapshot_sha(value: dict[str, Any]) -> str:
    payload = json.dumps(value, sort_keys=True, ensure_ascii=False).encode()
    return hashlib.sha256(payload).hexdigest()


def _safe_key(value: str) -> str:
    key = SAFE_KEY.sub("-", value.casefold()).strip("-.")
    if not key:
        raise TheSkyWatchAdapterError("record_key_invalid", value)
    return key[:220]


def _source_url(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        return ""
    parsed = urlparse(candidate)
    if parsed.scheme in {"http", "https"}:
        return candidate
    if candidate.startswith("taxonomy:") or candidate.startswith("TSW Registry"):
        return candidate
    return f"https://{candidate.lstrip('/')}"


def _normal_sources(cell: dict[str, Any]) -> list[dict[str, Any]]:
    raw_sources = cell.get("sources")
    sources: list[dict[str, Any]] = []
    if isinstance(raw_sources, list):
        for raw in raw_sources:
            if not isinstance(raw, dict):
                continue
            url = _source_url(str(raw.get("url", "")))
            if not url:
                continue
            sources.append({
                "url": url,
                "tier": str(raw.get("tier") or cell.get("source_tier") or ""),
                "retrieved": raw.get("retrieved"),
                "claimed_value": raw.get("claimed_value"),
                "note": raw.get("note"),
            })
    raw_source = cell.get("source")
    if isinstance(raw_source, str) and raw_source.strip():
        sources.append({
            "url": _source_url(raw_source),
            "tier": str(cell.get("tier") or cell.get("source_tier") or ""),
            "retrieved": cell.get("retrieved"),
            "claimed_value": cell.get("value"),
            "note": cell.get("note"),
        })
    unique: dict[tuple[str, str], dict[str, Any]] = {}
    for source in sources:
        unique[(str(source["url"]), str(source["tier"]))] = source
    return [unique[key] for key in sorted(unique)]


def _parse_cell(field: str, raw: Any) -> tuple[_Cell | None, str | None]:
    if not isinstance(raw, dict) or "value" not in raw:
        return None, None
    if raw.get("value") is None:
        return None, "null"
    status = str(raw.get("status") or "").strip()
    if status in EXCLUDED_STATUSES:
        return None, "unverified"
    source_tier = str(raw.get("source_tier") or raw.get("tier") or "").strip()
    # A derived value stays hypothesis/derived tier even when its inputs came
    # from stronger sources. Input quality must not launder an inference.
    if status == "derived":
        source_tier = "derived"
    if source_tier and source_tier not in TIER_MAP:
        raise TheSkyWatchAdapterError("source_tier_invalid", f"{field}:{source_tier}")
    if not source_tier:
        # Identity/display metadata without a source is useful as a locator but
        # must not silently become an evidence-bearing claim.
        return None, None
    if source_tier != "derived" and status and status not in DIRECT_STATUSES:
        raise TheSkyWatchAdapterError("field_status_invalid", f"{field}:{status}")
    return _Cell(
        field=field,
        value=raw["value"],
        status=status or ("derived" if source_tier == "derived" else "sourced"),
        confidence=(str(raw["confidence"]) if raw.get("confidence") is not None else None),
        source_tier=source_tier,
        research_tier=TIER_MAP[source_tier],
        sources=_normal_sources(raw),
    ), None


def _identity(entity: dict[str, Any], index: int) -> dict[str, str]:
    identity: dict[str, str] = {}
    for key in ("canonical_id", "family_id", "entity_type", "slug", "name", "provenance_class"):
        value = entity.get(key)
        if isinstance(value, str | int | float) and str(value).strip():
            identity[key] = str(value)
    entity_type = identity.get("entity_type", "entity")
    stable = identity.get("canonical_id") or identity.get("slug") or identity.get("name")
    if not stable:
        raise TheSkyWatchAdapterError("entity_identity_missing", str(index))
    identity["stable_key"] = f"{entity_type}:{stable}"
    return identity


def _cell_quote(identity: dict[str, str], cell: _Cell) -> str:
    return canonical_json({
        "entity": identity["stable_key"],
        "field": cell.field,
        "value": cell.value,
        "status": cell.status,
        "confidence": cell.confidence,
        "source_tier": cell.source_tier,
    }).decode("utf-8")


def _entity_records(
    entities: list[Any],
) -> tuple[list[RefineryRecord], Counter[str]]:
    records: list[RefineryRecord] = []
    stats: Counter[str] = Counter()
    for index, raw_entity in enumerate(entities):
        if not isinstance(raw_entity, dict):
            raise TheSkyWatchAdapterError("entity_schema_invalid", str(index))
        entity = cast(dict[str, Any], raw_entity)
        identity = _identity(entity, index)
        groups: dict[ResearchTier, list[_Cell]] = defaultdict(list)
        for field, raw in sorted(entity.items()):
            cell, excluded = _parse_cell(field, raw)
            if excluded:
                stats[f"excluded_{excluded}"] += 1
            if cell is not None:
                groups[cell.research_tier].append(cell)
                stats["admitted_fields"] += 1
        for tier, cells in sorted(groups.items()):
            facts: dict[str, Any] = {}
            evidence: list[RefineryEvidence] = []
            for cell in cells:
                facts[cell.field] = {
                    "value": cell.value,
                    "status": cell.status,
                    "confidence": cell.confidence,
                    "source_tier": cell.source_tier,
                    "upstream_sources": cell.sources,
                }
                quote = _cell_quote(identity, cell)
                evidence.append(RefineryEvidence(
                    source_url=PUBLIC_DATA_URL,
                    locator={
                        "snapshot": "site-data.json",
                        "entity_index": index,
                        "entity_key": identity["stable_key"],
                        "field": cell.field,
                        "upstream_sources": cell.sources,
                    },
                    quoted_text=quote,
                    checksum=evidence_checksum(quote),
                ))
            statuses = {cell.status for cell in cells}
            corroboration: CorroborationState = (
                "disputed" if "disputed" in statuses
                else "corroborated" if statuses == {"corroborated"}
                else "uncorroborated"
            )
            searchable = "\n".join([
                *identity.values(),
                *(f"{cell.field}: {json.dumps(cell.value, ensure_ascii=False)}" for cell in cells),
            ])
            record = RefineryRecord(
                record_key=(
                    f"tsw.{_safe_key(identity['stable_key'])}.tier-{tier.casefold()}"
                ),
                version_ordinal=1,
                tier=tier,
                content={
                    "kind": "entity_profile",
                    "identity": identity,
                    "facts": facts,
                },
                searchable_text=searchable,
                evidence=evidence,
                corroboration_state=corroboration,
                content_sha256="0" * 64,
            )
            records.append(record.model_copy(update={
                "content_sha256": research_record_sha(record),
            }))
            stats[f"tier_{tier}"] += 1
            stats[f"corroboration_{corroboration}"] += 1
    stats["entities"] = len(entities)
    stats["entity_records"] = len(records)
    return records, stats


def _article_tier(sources: list[Any]) -> ResearchTier:
    tiers = {
        str(source.get("tier", ""))
        for source in sources
        if isinstance(source, dict)
    }
    if "C" in tiers:
        return "H"
    # The article itself is an editorial/secondary publication even when all
    # underlying references are primary.
    return "S" if tiers else "H"


def _article_records(articles: list[dict[str, Any]]) -> list[RefineryRecord]:
    records: list[RefineryRecord] = []
    for index, article in enumerate(articles):
        if article.get("status") != "published" or article.get("sample") is True:
            continue
        slug = str(article.get("slug") or "").strip()
        title = str(article.get("title") or "").strip()
        body = str(article.get("body") or "").strip()
        if not slug or not title or not body:
            raise TheSkyWatchAdapterError("article_schema_invalid", str(index))
        raw_sources = article.get("sources")
        sources = raw_sources if isinstance(raw_sources, list) else []
        tier = _article_tier(sources)
        hosts = {
            (urlparse(_source_url(str(source.get("url", "")))).hostname or "")
            for source in sources
            if isinstance(source, dict)
        }
        hosts.discard("")
        corroboration: CorroborationState = (
            "corroborated" if len(hosts) >= 2 and tier in {"P", "S"}
            else "uncorroborated"
        )
        evidence = RefineryEvidence(
            source_url=PUBLIC_ARTICLE_URL,
            locator={
                "snapshot": "articles_records.json",
                "article_index": index,
                "slug": slug,
                "upstream_sources": sources,
            },
            quoted_text=body,
            checksum=evidence_checksum(body),
        )
        record = RefineryRecord(
            record_key=f"tsw.article.{_safe_key(slug)}",
            version_ordinal=1,
            tier=tier,
            content={
                "kind": "published_article",
                "slug": slug,
                "title": title,
                "article_type": article.get("type"),
                "date": article.get("date"),
                "author": article.get("author"),
                "entity_tags": article.get("entity_tags") or [],
                "primary_section": article.get("primary_section"),
                "upstream_sources": sources,
            },
            searchable_text="\n".join([title, slug, str(article.get("type") or ""), body]),
            evidence=[evidence],
            corroboration_state=corroboration,
            content_sha256="0" * 64,
        )
        records.append(record.model_copy(update={
            "content_sha256": research_record_sha(record),
        }))
    return records


def _captured_at(
    master: dict[str, Any],
    entities: list[Any],
    articles: list[dict[str, Any]],
) -> datetime:
    candidates: list[datetime] = []

    def collect(value: Any) -> None:
        if not isinstance(value, str) or not value.strip():
            return
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            try:
                parsed = datetime.fromisoformat(f"{value}T00:00:00+00:00")
            except ValueError:
                return
        candidates.append(parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC))

    collect(master.get("generated"))
    for article in articles:
        collect(article.get("date"))
    for raw_entity in entities:
        if not isinstance(raw_entity, dict):
            continue
        for raw in raw_entity.values():
            if not isinstance(raw, dict):
                continue
            collect(raw.get("last_verified"))
            collect(raw.get("retrieved"))
            sources = raw.get("sources")
            if isinstance(sources, list):
                for source in sources:
                    if isinstance(source, dict):
                        collect(source.get("retrieved"))
    if not candidates:
        raise TheSkyWatchAdapterError("snapshot_capture_time_missing")
    return max(candidates).astimezone(UTC)


def build_records(snapshot_root: Path) -> tuple[list[RefineryRecord], Counter[str], str, datetime]:
    """Load, cross-check and normalize one complete local snapshot."""

    root = snapshot_root.resolve()
    master = _load_object(root / "master_registry.json", "master_registry_missing")
    site = _load_object(root / "site-data.json", "site_data_missing")
    articles = _load_array(root / "articles_records.json", "articles_missing")
    declared_sha = str(site.get("source_registry_sha256") or "")
    actual_sha = _canonical_snapshot_sha(master)
    if declared_sha != actual_sha:
        raise TheSkyWatchAdapterError(
            "source_registry_fingerprint_mismatch",
            f"declared={declared_sha} actual={actual_sha}",
        )
    entities = site.get("entities")
    if not isinstance(entities, list) or not entities:
        raise TheSkyWatchAdapterError("entity_set_empty")
    entity_records, stats = _entity_records(entities)
    article_records = _article_records(articles)
    for record in article_records:
        stats[f"tier_{record.tier}"] += 1
        stats[f"corroboration_{record.corroboration_state}"] += 1
    stats["articles"] = len(article_records)
    records = sorted(
        [*entity_records, *article_records], key=lambda item: item.record_key,
    )
    if len({record.record_key for record in records}) != len(records):
        raise TheSkyWatchAdapterError("duplicate_record_key")
    return records, stats, actual_sha, _captured_at(master, entities, articles)


def emit_package(snapshot_root: Path, out_root: Path) -> TheSkyWatchBuildResult:
    """Emit a byte-stable package accepted by the existing Research parser."""

    records, stats, source_registry_sha, captured_at = build_records(snapshot_root)
    records_bytes = b"".join(
        canonical_json(record.model_dump(mode="json")) + b"\n" for record in records
    )
    member = ResearchManifestMember(
        path="records.jsonl",
        byte_size=len(records_bytes),
        sha256=sha256_bytes(records_bytes),
    )
    payload_sha = research_payload_sha([member])
    fingerprint = research_fingerprint(
        source_key=SOURCE_KEY,
        scope=SCOPE,
        captured_at=captured_at,
        adapter_version=ADAPTER_VERSION,
        payload_sha256=payload_sha,
    )
    manifest = {
        "schema_version": "1.0",
        "source_key": SOURCE_KEY,
        "fingerprint": fingerprint,
        "payload_sha256": payload_sha,
        "captured_at": captured_at.isoformat(),
        "scope": SCOPE,
        "adapter_version": ADAPTER_VERSION,
        "record_count": len(records),
        "members": [member.model_dump(mode="json")],
    }
    staging_name = f"research-theskywatch-{fingerprint[:12]}"
    package_root = out_root.resolve() / staging_name
    package_root.mkdir(parents=True, exist_ok=True)
    outputs = {
        "manifest.json": canonical_json(manifest),
        "records.jsonl": records_bytes,
    }
    for name, payload in outputs.items():
        target = package_root / name
        if target.exists() and target.read_bytes() != payload:
            raise TheSkyWatchAdapterError("output_drift", str(target))
        target.write_bytes(payload)
    return TheSkyWatchBuildResult(
        staging_name=staging_name,
        package_root=package_root,
        fingerprint=fingerprint,
        record_count=len(records),
        entity_count=stats["entities"],
        entity_record_count=stats["entity_records"],
        admitted_field_count=stats["admitted_fields"],
        article_count=stats["articles"],
        excluded_null_count=stats["excluded_null"],
        excluded_unverified_count=stats["excluded_unverified"],
        tier_counts={tier: stats[f"tier_{tier}"] for tier in ("P", "S", "H", "X")},
        corroboration_counts={
            state: stats[f"corroboration_{state}"]
            for state in ("corroborated", "disputed", "uncorroborated")
        },
        source_registry_sha256=source_registry_sha,
    )
