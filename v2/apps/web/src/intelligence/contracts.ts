export type IntelligenceZone = "sot" | "research";
export type IntelligenceKind = "update" | "attention" | "research";
export type IntelligencePriority = "high" | "normal";

export type IntelligenceEvidence = {
  zoneLabel: IntelligenceZone;
  recordKey: string;
  sourceKey: string;
  sourceLabel: string;
  contentSha256: string;
  locator: Record<string, unknown>;
  recordVersionId: string | null;
  sourceRevision: number | null;
  provenanceLevel: string | null;
  verificationState: string | null;
  freshnessState: string | null;
  researchRecordId: string | null;
  packageFingerprint: string | null;
  tier: string | null;
  corroborationState: string | null;
};

export type IntelligenceItem = {
  itemId: string;
  zoneLabel: IntelligenceZone;
  kind: IntelligenceKind;
  priority: IntelligencePriority;
  title: string;
  summary: string;
  observedAt: string;
  askQuery: string;
  evidence: IntelligenceEvidence;
};

export type IntelligenceBriefing = {
  generatedAt: string;
  items: IntelligenceItem[];
  counts: {updates: number; attention: number; research: number};
  requestId: string;
};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const SHA = /^[0-9a-f]{64}$/;
const KINDS = new Set<IntelligenceKind>(["update", "attention", "research"]);
const PRIORITIES = new Set<IntelligencePriority>(["high", "normal"]);
const ZONES = new Set<IntelligenceZone>(["sot", "research"]);

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}
function text(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.length > 0 && value.length <= maximum
    && !/[\u0000-\u0008\u000b\u000c\u000e-\u001f]/.test(value);
}
function nullableText(value: unknown, maximum = 512): value is string | null | undefined {
  return value === null || value === undefined || text(value, maximum);
}
function nullableUuid(value: unknown): value is string | null | undefined {
  return value === null || value === undefined
    || (typeof value === "string" && UUID.test(value));
}

function parseEvidence(value: unknown): IntelligenceEvidence {
  if (!record(value) || !ZONES.has(value.zone_label as IntelligenceZone)
      || !text(value.record_key, 256) || !text(value.source_key, 256)
      || !text(value.source_label, 512)
      || typeof value.content_sha256 !== "string" || !SHA.test(value.content_sha256)
      || !record(value.locator)
      || !nullableUuid(value.record_version_id)
      || !(value.source_revision === null || value.source_revision === undefined
        || (Number.isInteger(value.source_revision) && Number(value.source_revision) > 0))
      || !nullableText(value.provenance_level, 64)
      || !nullableText(value.verification_state, 64)
      || !nullableText(value.freshness_state, 64)
      || !nullableUuid(value.research_record_id)
      || !(value.package_fingerprint === null || value.package_fingerprint === undefined
        || (typeof value.package_fingerprint === "string" && SHA.test(value.package_fingerprint)))
      || !(value.tier === null || value.tier === undefined
        || (typeof value.tier === "string" && /^[PSHX]$/.test(value.tier)))
      || !nullableText(value.corroboration_state, 64)) {
    throw new Error("invalid_intelligence_evidence");
  }
  const zone = value.zone_label as IntelligenceZone;
  const recordVersionId = typeof value.record_version_id === "string"
    ? value.record_version_id : null;
  const sourceRevision = typeof value.source_revision === "number"
    ? value.source_revision : null;
  const researchRecordId = typeof value.research_record_id === "string"
    ? value.research_record_id : null;
  const packageFingerprint = typeof value.package_fingerprint === "string"
    ? value.package_fingerprint : null;
  if ((zone === "sot" && (
    !recordVersionId || sourceRevision === null
    || researchRecordId || packageFingerprint
  )) || (zone === "research" && (
    !researchRecordId || !packageFingerprint
    || recordVersionId || sourceRevision !== null
  ))) {
    throw new Error("invalid_intelligence_evidence");
  }
  return {
    zoneLabel: zone,
    recordKey: value.record_key as string,
    sourceKey: value.source_key as string,
    sourceLabel: value.source_label as string,
    contentSha256: value.content_sha256 as string,
    locator: value.locator,
    recordVersionId,
    sourceRevision,
    provenanceLevel: typeof value.provenance_level === "string" ? value.provenance_level : null,
    verificationState: typeof value.verification_state === "string"
      ? value.verification_state : null,
    freshnessState: typeof value.freshness_state === "string" ? value.freshness_state : null,
    researchRecordId,
    packageFingerprint,
    tier: typeof value.tier === "string" ? value.tier : null,
    corroborationState: typeof value.corroboration_state === "string"
      ? value.corroboration_state : null,
  };
}

function parseItem(value: unknown): IntelligenceItem {
  if (!record(value) || typeof value.item_id !== "string" || !SHA.test(value.item_id)
      || !ZONES.has(value.zone_label as IntelligenceZone)
      || !KINDS.has(value.kind as IntelligenceKind)
      || !PRIORITIES.has(value.priority as IntelligencePriority)
      || !text(value.title, 180) || !text(value.summary, 700)
      || typeof value.observed_at !== "string" || Number.isNaN(Date.parse(value.observed_at))
      || !text(value.ask_query, 500)) {
    throw new Error("invalid_intelligence_item");
  }
  const evidence = parseEvidence(value.evidence);
  const zone = value.zone_label as IntelligenceZone;
  const kind = value.kind as IntelligenceKind;
  if (evidence.zoneLabel !== zone || (kind === "research") !== (zone === "research")) {
    throw new Error("invalid_intelligence_item");
  }
  return {
    itemId: value.item_id,
    zoneLabel: zone,
    kind,
    priority: value.priority as IntelligencePriority,
    title: value.title,
    summary: value.summary,
    observedAt: value.observed_at,
    askQuery: value.ask_query,
    evidence,
  };
}

export function parseIntelligenceBriefing(value: unknown): IntelligenceBriefing {
  if (!record(value) || typeof value.generated_at !== "string"
      || Number.isNaN(Date.parse(value.generated_at)) || !Array.isArray(value.items)
      || value.items.length > 20 || !record(value.counts)
      || !Number.isInteger(value.counts.updates) || Number(value.counts.updates) < 0
      || !Number.isInteger(value.counts.attention) || Number(value.counts.attention) < 0
      || !Number.isInteger(value.counts.research) || Number(value.counts.research) < 0
      || !text(value.request_id, 128)) {
    throw new Error("invalid_intelligence_briefing");
  }
  const items = value.items.map(parseItem);
  const actual = {
    updates: items.filter(item => item.kind === "update").length,
    attention: items.filter(item => item.kind === "attention").length,
    research: items.filter(item => item.kind === "research").length,
  };
  if (actual.updates !== value.counts.updates
      || actual.attention !== value.counts.attention
      || actual.research !== value.counts.research) {
    throw new Error("invalid_intelligence_briefing");
  }
  return {
    generatedAt: value.generated_at,
    items,
    counts: actual,
    requestId: value.request_id,
  };
}
