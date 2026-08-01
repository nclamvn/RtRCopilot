/**
 * Shared Evidence Rail contract (TIP-011 Task 2, D-011-02).
 *
 * ONE typed evidence shape consumed by Ask today and by Files, Documents and
 * Knowledge Ops after Builder C's migration: zone, source, record/document
 * version, deep locator (rtr.locator.v1 union), evidence checksums,
 * freshness/effectiveness and policy state.
 *
 * Zone labels are SERVER-PROVIDED ONLY (client-edge gate, same rule as
 * `governance/contracts`):
 * - research-shaped evidence must carry the exact `zone_label: "research"` —
 *   any other label (including a forged `"sot"`) refuses to parse;
 * - TIP-007 Ask citations carry NO zone label by contract (the backend model
 *   forbids extra fields), so a citation payload that smuggles any
 *   `zone_label` refuses to parse and the entry renders with no chip;
 * - `zone: null` means "no server label" and the chip never renders — the
 *   client never guesses a zone.
 */

import {Locator, locatorQuery} from "../files/contracts";
import type {CorroborationState, ResearchTier, TrustZone} from "../governance/contracts";

export type EvidenceZone = TrustZone;
export type EvidenceGrounding = "grounded" | "research_supported";

export type EvidenceEntry = {
  /** Unique key inside one rail (citation marker or research record id). */
  key: string;
  /** Citation marker as the backend assigned it, e.g. "C1"; null otherwise. */
  marker: string | null;
  /** Server-provided trust zone; null = the server sent no zone label. */
  zone: EvidenceZone | null;
  /** Server grounding metadata: SOT-grounded fact vs research-supported. */
  grounding: EvidenceGrounding | null;
  tier: ResearchTier | null;
  sourceKey: string;
  sourceLabel: string;
  sourceRevision: number | null;
  recordKey: string;
  /** Immutable record/document version the evidence is bound to. */
  recordVersionId: string | null;
  versionOrdinal: number | null;
  evidenceKey: string | null;
  recordChecksum: string | null;
  evidenceChecksums: string[];
  contentChecksum: string | null;
  provenanceLevel: string | null;
  verificationState: string | null;
  freshnessState: string | null;
  corroborationState: CorroborationState | null;
  /** Policy state: true when DLP redacted part of the disclosed evidence. */
  redacted: boolean;
  /** rtr.locator.v1 deep locator; null when the evidence has no position. */
  locator: Locator | null;
  snippet: string | null;
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const HEX64 = /^[0-9a-f]{64}$/i;
const MARKER = /^C\d{1,3}$/;
const CELL = /^[A-Z]{1,3}[1-9][0-9]{0,6}$/;
const TIERS = new Set<ResearchTier>(["P", "S", "H", "X"]);
const CORROBORATION = new Set<CorroborationState>([
  "uncorroborated", "corroborated", "disputed",
]);

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function uuid(value: unknown): value is string {
  return typeof value === "string" && UUID.test(value);
}
function hex64(value: unknown): value is string {
  return typeof value === "string" && HEX64.test(value);
}
function text(value: unknown, maximum = 10_000): value is string {
  return typeof value === "string" && value.length <= maximum
    && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(value);
}
function count(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}

function boundedInt(value: unknown, minimum: number, maximum: number) {
  return typeof value === "number" && Number.isSafeInteger(value)
    && value >= minimum && value <= maximum ? value : undefined;
}

/**
 * Parse a server locator object into the bounded rtr.locator.v1 union
 * (page/sheet/cell/slide/timecode plus paragraph/table/shape/region).
 * Unknown or hostile keys are dropped; an empty result returns null.
 */
export function parseObjectLocator(value: unknown): Locator | null {
  if (!record(value)) return null;
  const locator: Locator = {};
  const page = boundedInt(value.page, 1, 5000);
  const paragraph = boundedInt(value.paragraph, 0, 100_000);
  const table = boundedInt(value.table, 0, 10_000);
  const slide = boundedInt(value.slide, 1, 5000);
  const shape = boundedInt(value.shape, 0, 100_000);
  const t = boundedInt(value.t, 0, 14_400_000);
  if (page) locator.page = page;
  if (paragraph !== undefined) locator.paragraph = paragraph;
  if (table !== undefined) locator.table = table;
  if (slide) locator.slide = slide;
  if (shape !== undefined) locator.shape = shape;
  if (t !== undefined) locator.t = t;
  if (typeof value.sheet === "string" && value.sheet.length > 0
      && value.sheet.length <= 100 && !/[\u0000-\u001f]/.test(value.sheet)) {
    locator.sheet = value.sheet;
  }
  if (typeof value.cell === "string" && CELL.test(value.cell.toUpperCase())) {
    locator.cell = value.cell.toUpperCase();
  }
  if (typeof value.region === "string" && /^[A-Za-z0-9._~-]{1,100}$/.test(value.region)) {
    locator.region = value.region;
  }
  return Object.keys(locator).length > 0 ? locator : null;
}

/**
 * TIP-008 deep-link contract: same-tab navigation to the file route with
 * rtr.locator.v1 params. `/files` preserves its query while redirecting to
 * the workspace, so this stays valid when Builder C moves the workspace
 * under `(shell)/files`.
 */
export function evidenceHref(entry: EvidenceEntry): string | null {
  if (!entry.recordVersionId) return null;
  const params = new URLSearchParams({version: entry.recordVersionId});
  const locatorParams = new URLSearchParams(locatorQuery(entry.locator ?? {}));
  locatorParams.forEach((value, key) => params.set(key, value));
  return `/files?${params}`;
}

export function railEntryId(key: string): string {
  return `rail-entry-${key.replace(/[^A-Za-z0-9_-]/g, "_")}`;
}

/**
 * The client-edge zone gate: research-shaped evidence without the exact
 * `research` label — or carrying any other label — never parses.
 */
function researchZone(value: Record<string, unknown>): "research" {
  if (value.zone_label !== "research") throw new Error("zone_label_forged");
  return "research";
}

/**
 * Adapt one TIP-007 Ask citation. The frozen backend model carries no zone
 * label (extra fields are forbidden server-side), so a payload that smuggles
 * one is treated as forged and refused; the entry renders without a chip.
 * `grounding` comes from the enclosing response's server state.
 */
export function evidenceFromAskCitation(
  value: unknown,
  grounding: "grounded",
): EvidenceEntry {
  if (!record(value)) throw new Error("invalid_citation");
  if ("zone_label" in value) throw new Error("zone_label_forged");
  if (!text(value.marker, 8) || !MARKER.test(value.marker as string)
      || !uuid(value.chunk_id) || !text(value.record_key, 500)
      || !uuid(value.record_version_id)
      || !(value.evidence_key === null || text(value.evidence_key, 500))
      || !hex64(value.record_checksum)
      || !(value.evidence_checksum === null || hex64(value.evidence_checksum))
      || !text(value.source_key, 200) || !count(value.source_revision)
      || !text(value.provenance_level, 100)
      || !text(value.verification_state, 100)
      || !text(value.freshness_state, 100) || !text(value.source_label, 500)
      || !record(value.locator) || typeof value.redacted !== "boolean") {
    throw new Error("invalid_citation");
  }
  return {
    key: value.marker as string,
    marker: value.marker as string,
    zone: null,
    grounding,
    tier: null,
    sourceKey: value.source_key as string,
    sourceLabel: value.source_label as string,
    sourceRevision: value.source_revision as number,
    recordKey: value.record_key as string,
    recordVersionId: value.record_version_id as string,
    versionOrdinal: null,
    evidenceKey: text(value.evidence_key, 500) && value.evidence_key
      ? value.evidence_key as string : null,
    recordChecksum: value.record_checksum as string,
    evidenceChecksums: hex64(value.evidence_checksum)
      ? [value.evidence_checksum] : [],
    contentChecksum: null,
    provenanceLevel: value.provenance_level as string,
    verificationState: value.verification_state as string,
    freshnessState: value.freshness_state as string,
    corroborationState: null,
    redacted: value.redacted as boolean,
    locator: parseObjectLocator(value.locator),
    snippet: null,
  };
}

/**
 * Adapt one research search hit. Both the hit and its citation must carry
 * the exact server `research` zone label — `zone_label: "sot"` on
 * research-shaped evidence refuses to render (forged-zone regression).
 */
export function evidenceFromResearchHit(value: unknown): EvidenceEntry {
  if (!record(value)) throw new Error("invalid_research_hit");
  const zone = researchZone(value);
  if (!uuid(value.research_record_id) || !text(value.record_key, 500)
      || !TIERS.has(value.tier as ResearchTier) || !text(value.snippet)
      || !record(value.citation)) {
    throw new Error("invalid_research_hit");
  }
  const citation = value.citation;
  researchZone(citation);
  if (!uuid(citation.research_record_id) || !text(citation.record_key, 500)
      || !count(citation.version_ordinal) || citation.version_ordinal < 1
      || !TIERS.has(citation.tier as ResearchTier)
      || !text(citation.source_key, 200) || !hex64(citation.package_fingerprint)
      || !hex64(citation.content_sha256)
      || !CORROBORATION.has(citation.corroboration_state as CorroborationState)
      || !Array.isArray(citation.evidence_checksums)
      || citation.evidence_checksums.length > 1000
      || citation.evidence_checksums.some(item => !hex64(item))) {
    throw new Error("invalid_research_citation");
  }
  return {
    key: `research-${value.research_record_id}`,
    marker: null,
    zone,
    grounding: "research_supported",
    tier: citation.tier as ResearchTier,
    sourceKey: citation.source_key as string,
    sourceLabel: value.record_key as string,
    sourceRevision: null,
    recordKey: value.record_key as string,
    recordVersionId: null,
    versionOrdinal: citation.version_ordinal as number,
    evidenceKey: null,
    recordChecksum: null,
    evidenceChecksums: citation.evidence_checksums as string[],
    contentChecksum: citation.content_sha256 as string,
    provenanceLevel: null,
    verificationState: null,
    freshnessState: null,
    corroborationState: citation.corroboration_state as CorroborationState,
    redacted: false,
    locator: null,
    snippet: value.snippet as string,
  };
}

export type ResearchSearchEvidence = {
  zone: "research";
  grounding: "research_supported";
  entries: EvidenceEntry[];
  requestId: string;
};

/**
 * Parse a whole research search response: the response-level zone label and
 * grounding constant are gated exactly as the backend serializes them.
 */
export function parseResearchSearchEvidence(value: unknown): ResearchSearchEvidence {
  if (!record(value)) throw new Error("invalid_research_search");
  researchZone(value);
  if (value.grounding !== "research_supported"
      || !Array.isArray(value.results) || value.results.length > 50
      || !text(value.request_id, 128)) {
    throw new Error("invalid_research_search");
  }
  return {
    zone: "research",
    grounding: "research_supported",
    entries: value.results.map(evidenceFromResearchHit),
    requestId: value.request_id as string,
  };
}
