/**
 * Typed contracts for the Knowledge Ops workspace (TIP-010 Task 7).
 *
 * Every research-zone payload is validated to carry the constant
 * `zone_label: "research"` exactly as the backend serializes it; a missing or
 * forged zone label rejects the whole payload before anything renders
 * (AC-07 on the client edge). SOT-plane chips render only from zone labels the
 * self-labeling dashboard endpoint returns — never from client-side guesses.
 */

export type TrustZone = "sot" | "research" | "private";
export type Classification =
  | "public_internal" | "internal" | "restricted" | "highly_restricted";
export type GapState =
  | "open" | "triaged" | "assigned" | "answered" | "published" | "declined"
  | "resolved" | "dismissed";
export type GapPriority = "low" | "normal" | "high" | "urgent";
export type QueueKind = "freshness" | "conflict" | "owner_review";
export type QueueStatus =
  | "expiring" | "expired" | "due" | "overdue" | "disputed"
  | "superseded_ambiguous";
export type ReviewTaskState = "assigned" | "completed" | "reopened";
export type ResearchTier = "P" | "S" | "H" | "X";
export type PackageImportState = "received" | "validating" | "imported" | "rejected";
export type ProposalState = "proposed" | "approved" | "rejected";
export type CorroborationState = "uncorroborated" | "corroborated" | "disputed";

export type TypedError = {code: string; message: string; requestId: string};

export type Gap = {
  /** Literal server zone label (TIP-011 AC-07); null = absent (older shape). */
  zone_label: "sot" | null;
  gap_id: string; question_fingerprint: string; sanitized_question: string;
  sanitized_summary: string; reason_category: string;
  classification: Classification; requester_id: string;
  owner_subject_id: string | null; routing_key: string;
  occurrence_count: number; lifecycle: GapState;
  origin: string; priority: GapPriority;
  first_seen_at: string; last_seen_at: string;
  triaged_at: string | null; assigned_at: string | null; due_at: string | null;
  answered_at: string | null; closed_at: string | null;
  resolving_version_id: string | null; decline_reason: string | null;
};
export type GapPage = {items: Gap[]; next_cursor: string | null};
export type GapTransition = {
  sequence: number; transition_id: string; gap_id: string;
  from_state: GapState; to_state: GapState; actor_subject_id: string;
  reason: string; occurred_at: string;
};
export type GapDetail = {gap: Gap; transitions: GapTransition[]};

export type ReviewTask = {
  zone_label: "sot" | null;
  task_id: string; queue_kind: QueueKind; record_version_id: string;
  assignee_subject_id: string; assigned_by: string; state: ReviewTaskState;
  due_at: string | null; note: string; created_at: string; updated_at: string;
  completed_at: string | null;
};
export type QueueConflictSide = {
  version_id: string; record_id: string; package_revision: number;
  provenance_level: string; verification_state: string; content_sha256: string;
  evidence_refs: string[]; effective_from: string; external: boolean;
};
export type QueueEntry = {
  zone_label: "sot" | null;
  queue_kind: QueueKind; record_id: string; record_key: string;
  record_version_id: string; owner_subject_id: string;
  classification: Classification; status: QueueStatus; sort_at: string;
  effective_to: string | null; review_due_at: string | null;
  sides: QueueConflictSide[]; task: ReviewTask | null;
};
export type QueueAggregates = {
  total: number; by_status: Record<string, number>;
  assigned: number; unassigned: number;
};
export type QueuePage = {
  zone_label: "sot" | null;
  queue_kind: QueueKind; computed_at: string; entries: QueueEntry[];
  aggregates: QueueAggregates; next_cursor: string | null;
};

export type SotTile = {zone_label: "sot"};
export type ResearchTile = {zone_label: "research"};
export type Dashboard = {
  computed_at: string;
  coverage: SotTile & {
    total_records: number; by_source_key: Record<string, number>;
    by_owner: Record<string, number>; by_classification: Record<string, number>;
  };
  freshness: SotTile & {
    total: number; expiring: number; expired: number;
    assigned: number; unassigned: number;
  };
  conflict: SotTile & {
    total: number; disputed: number; superseded_ambiguous: number;
    assigned: number; unassigned: number;
  };
  owner_review: SotTile & {
    total: number; due: number; overdue: number;
    assigned: number; unassigned: number;
  };
  gap_flow: SotTile & {
    open_total: number; closed_total: number; overdue: number;
    by_state: Record<string, number>; aging: Record<string, number>;
  };
  research_intake: ResearchTile & {
    sources_total: number; sources_active: number;
    packages_by_state: Record<string, number>;
    records_by_tier: Record<string, number>;
  };
  graduation: ResearchTile & {
    proposed: number; approved: number; rejected: number; submitted: number;
  };
};

export type ResearchPackage = {
  zone_label: "research"; package_id: string; source_key: string;
  fingerprint: string; payload_sha256: string; captured_at: string;
  snapshot_scope: string; adapter_version: string;
  tier_composition: Record<string, number>; import_state: PackageImportState;
  rejection_code: string | null; record_count: number;
  received_at: string; imported_at: string | null;
};
export type ResearchPackagePage = {items: ResearchPackage[]; next_cursor: string | null};
export type ResearchEvidence = {
  source_url: string; locator: Record<string, unknown>;
  quoted_text: string; checksum: string;
};
export type ResearchRecord = {
  zone_label: "research"; research_record_id: string; package_id: string;
  package_fingerprint: string; source_key: string; record_key: string;
  version_ordinal: number; tier: ResearchTier; content: Record<string, unknown>;
  searchable_text: string; evidence: ResearchEvidence[];
  corroboration_state: CorroborationState; content_sha256: string;
  created_at: string;
};
export type ResearchRecordPage = {items: ResearchRecord[]; next_cursor: string | null};

export type Proposal = {
  proposal_id: string; research_record_ids: string[];
  claim_draft: Record<string, unknown>; target_record_key: string;
  proposer_subject_id: string; rationale: string; state: ProposalState;
  decided_by: string | null; decision_reason: string | null;
  attestation_hash: string | null; publish_package_id: string | null;
  supersedes_proposal_id: string | null; proposed_at: string;
  decided_at: string | null;
};
export type ProposalPage = {items: Proposal[]; next_cursor: string | null};

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
const HEX64 = /^[0-9a-f]{64}$/i;
const CLASSIFICATIONS = new Set<Classification>([
  "public_internal", "internal", "restricted", "highly_restricted",
]);
const GAP_STATES = new Set<GapState>([
  "open", "triaged", "assigned", "answered", "published", "declined",
  "resolved", "dismissed",
]);
const GAP_PRIORITIES = new Set<GapPriority>(["low", "normal", "high", "urgent"]);
const QUEUE_KINDS = new Set<QueueKind>(["freshness", "conflict", "owner_review"]);
const QUEUE_STATUSES = new Set<QueueStatus>([
  "expiring", "expired", "due", "overdue", "disputed", "superseded_ambiguous",
]);
const TASK_STATES = new Set<ReviewTaskState>(["assigned", "completed", "reopened"]);
const TIERS = new Set<ResearchTier>(["P", "S", "H", "X"]);
const IMPORT_STATES = new Set<PackageImportState>([
  "received", "validating", "imported", "rejected",
]);
const PROPOSAL_STATES = new Set<ProposalState>(["proposed", "approved", "rejected"]);
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
function stamp(value: unknown): value is string {
  return typeof value === "string" && value.length <= 64
    && !Number.isNaN(Date.parse(value));
}
function optional(value: unknown, check: (input: unknown) => boolean) {
  return value === null || value === undefined || check(value);
}
function count(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
}
function countMap(value: unknown): value is Record<string, number> {
  return record(value) && Object.keys(value).length <= 500
    && Object.entries(value).every(([key, item]) => text(key, 200) && count(item));
}

/**
 * The one gate this module exists for: a research payload without the exact
 * `research` zone label — or carrying any other label — never parses.
 */
function researchZone(value: Record<string, unknown>): "research" {
  if (value.zone_label !== "research") throw new Error("zone_label_forged");
  return "research";
}

/**
 * SOT-plane payload gate (TIP-011 AC-07): the literal server label renders
 * the chip; an absent label (older shape) renders no chip; any OTHER value
 * is forged and rejects the payload.
 */
function sotZoneOptional(value: Record<string, unknown>): "sot" | null {
  if (value.zone_label === undefined) return null;
  if (value.zone_label !== "sot") throw new Error("zone_label_forged");
  return "sot";
}

export function parseTypedError(value: unknown, fallbackRequestId = ""): TypedError {
  const body = record(value) ? value : {};
  const error = record(body.error) ? body.error : {};
  return {
    code: text(error.code, 128) && error.code ? error.code : "unknown_error",
    message: text(error.message, 500) && error.message ? error.message : "",
    requestId: text(body.request_id, 128) && body.request_id
      ? body.request_id : fallbackRequestId,
  };
}

function parseGapItem(value: unknown): Gap {
  if (!record(value) || !uuid(value.gap_id) || !hex64(value.question_fingerprint)
      || !text(value.sanitized_question) || !text(value.sanitized_summary)
      || !text(value.reason_category, 100)
      || !CLASSIFICATIONS.has(value.classification as Classification)
      || !uuid(value.requester_id) || !optional(value.owner_subject_id, uuid)
      || !text(value.routing_key, 500) || !count(value.occurrence_count)
      || value.occurrence_count < 1
      || !GAP_STATES.has(value.lifecycle as GapState)
      || !text(value.origin, 40)
      || !GAP_PRIORITIES.has(value.priority as GapPriority)
      || !stamp(value.first_seen_at) || !stamp(value.last_seen_at)
      || !optional(value.triaged_at, stamp) || !optional(value.assigned_at, stamp)
      || !optional(value.due_at, stamp) || !optional(value.answered_at, stamp)
      || !optional(value.closed_at, stamp)
      || !optional(value.resolving_version_id, uuid)
      || !optional(value.decline_reason, input => text(input))) {
    throw new Error("invalid_gap");
  }
  return {
    zone_label: sotZoneOptional(value),
    gap_id: value.gap_id, question_fingerprint: value.question_fingerprint,
    sanitized_question: value.sanitized_question,
    sanitized_summary: value.sanitized_summary,
    reason_category: value.reason_category,
    classification: value.classification as Classification,
    requester_id: value.requester_id,
    owner_subject_id: uuid(value.owner_subject_id) ? value.owner_subject_id : null,
    routing_key: value.routing_key, occurrence_count: value.occurrence_count,
    lifecycle: value.lifecycle as GapState, origin: value.origin,
    priority: value.priority as GapPriority,
    first_seen_at: value.first_seen_at, last_seen_at: value.last_seen_at,
    triaged_at: stamp(value.triaged_at) ? value.triaged_at : null,
    assigned_at: stamp(value.assigned_at) ? value.assigned_at : null,
    due_at: stamp(value.due_at) ? value.due_at : null,
    answered_at: stamp(value.answered_at) ? value.answered_at : null,
    closed_at: stamp(value.closed_at) ? value.closed_at : null,
    resolving_version_id: uuid(value.resolving_version_id)
      ? value.resolving_version_id : null,
    decline_reason: text(value.decline_reason) && value.decline_reason !== undefined
      ? value.decline_reason as string : null,
  };
}

function parsePageShape(value: unknown): {items: unknown[]; next_cursor: string | null} {
  if (!record(value) || !Array.isArray(value.items) || value.items.length > 200
      || !optional(value.next_cursor, input => text(input, 512))) {
    throw new Error("invalid_page");
  }
  return {
    items: value.items,
    next_cursor: text(value.next_cursor, 512) && value.next_cursor
      ? value.next_cursor as string : null,
  };
}

export function parseGapPage(value: unknown): GapPage {
  const page = parsePageShape(value);
  return {items: page.items.map(parseGapItem), next_cursor: page.next_cursor};
}

export function parseGap(value: unknown): Gap {
  return parseGapItem(value);
}

export function parseGapDetail(value: unknown): GapDetail {
  if (!record(value) || !Array.isArray(value.transitions)
      || value.transitions.length > 500) {
    throw new Error("invalid_gap_detail");
  }
  const transitions = value.transitions.map((item): GapTransition => {
    if (!record(item) || !count(item.sequence) || !uuid(item.transition_id)
        || !uuid(item.gap_id) || !GAP_STATES.has(item.from_state as GapState)
        || !GAP_STATES.has(item.to_state as GapState)
        || !uuid(item.actor_subject_id) || !text(item.reason)
        || !stamp(item.occurred_at)) {
      throw new Error("invalid_gap_transition");
    }
    return {
      sequence: item.sequence, transition_id: item.transition_id,
      gap_id: item.gap_id, from_state: item.from_state as GapState,
      to_state: item.to_state as GapState,
      actor_subject_id: item.actor_subject_id, reason: item.reason,
      occurred_at: item.occurred_at,
    };
  });
  return {gap: parseGapItem(value.gap), transitions};
}

export function parseReviewTask(value: unknown): ReviewTask {
  if (!record(value) || !uuid(value.task_id)
      || !QUEUE_KINDS.has(value.queue_kind as QueueKind)
      || !uuid(value.record_version_id) || !uuid(value.assignee_subject_id)
      || !uuid(value.assigned_by)
      || !TASK_STATES.has(value.state as ReviewTaskState)
      || !optional(value.due_at, stamp) || !text(value.note, 2000)
      || !stamp(value.created_at) || !stamp(value.updated_at)
      || !optional(value.completed_at, stamp)) {
    throw new Error("invalid_review_task");
  }
  return {
    zone_label: sotZoneOptional(value),
    task_id: value.task_id, queue_kind: value.queue_kind as QueueKind,
    record_version_id: value.record_version_id,
    assignee_subject_id: value.assignee_subject_id,
    assigned_by: value.assigned_by, state: value.state as ReviewTaskState,
    due_at: stamp(value.due_at) ? value.due_at : null, note: value.note,
    created_at: value.created_at, updated_at: value.updated_at,
    completed_at: stamp(value.completed_at) ? value.completed_at : null,
  };
}

function parseQueueEntry(value: unknown): QueueEntry {
  if (!record(value) || !QUEUE_KINDS.has(value.queue_kind as QueueKind)
      || !uuid(value.record_id) || !text(value.record_key, 500)
      || !uuid(value.record_version_id) || !uuid(value.owner_subject_id)
      || !CLASSIFICATIONS.has(value.classification as Classification)
      || !QUEUE_STATUSES.has(value.status as QueueStatus)
      || !stamp(value.sort_at) || !optional(value.effective_to, stamp)
      || !optional(value.review_due_at, stamp) || !Array.isArray(value.sides)
      || value.sides.length > 50) {
    throw new Error("invalid_queue_entry");
  }
  const sides = value.sides.map((side): QueueConflictSide => {
    if (!record(side) || !uuid(side.version_id) || !uuid(side.record_id)
        || !count(side.package_revision) || !text(side.provenance_level, 100)
        || !text(side.verification_state, 100) || !hex64(side.content_sha256)
        || !Array.isArray(side.evidence_refs) || side.evidence_refs.length > 100
        || side.evidence_refs.some(ref => !text(ref, 2048))
        || !stamp(side.effective_from) || typeof side.external !== "boolean") {
      throw new Error("invalid_conflict_side");
    }
    return {
      version_id: side.version_id, record_id: side.record_id,
      package_revision: side.package_revision,
      provenance_level: side.provenance_level,
      verification_state: side.verification_state,
      content_sha256: side.content_sha256,
      evidence_refs: side.evidence_refs as string[],
      effective_from: side.effective_from, external: side.external,
    };
  });
  return {
    zone_label: sotZoneOptional(value),
    queue_kind: value.queue_kind as QueueKind, record_id: value.record_id,
    record_key: value.record_key, record_version_id: value.record_version_id,
    owner_subject_id: value.owner_subject_id,
    classification: value.classification as Classification,
    status: value.status as QueueStatus, sort_at: value.sort_at,
    effective_to: stamp(value.effective_to) ? value.effective_to : null,
    review_due_at: stamp(value.review_due_at) ? value.review_due_at : null,
    sides,
    task: value.task === null || value.task === undefined
      ? null : parseReviewTask(value.task),
  };
}

export function parseQueueAggregates(value: unknown): QueueAggregates {
  if (!record(value) || !count(value.total) || !countMap(value.by_status)
      || !count(value.assigned) || !count(value.unassigned)) {
    throw new Error("invalid_queue_aggregates");
  }
  return {
    total: value.total, by_status: value.by_status,
    assigned: value.assigned, unassigned: value.unassigned,
  };
}

export function parseQueuePage(value: unknown): QueuePage {
  if (!record(value) || !QUEUE_KINDS.has(value.queue_kind as QueueKind)
      || !stamp(value.computed_at) || !Array.isArray(value.entries)
      || value.entries.length > 200
      || !optional(value.next_cursor, input => text(input, 512))) {
    throw new Error("invalid_queue_page");
  }
  return {
    zone_label: sotZoneOptional(value),
    queue_kind: value.queue_kind as QueueKind, computed_at: value.computed_at,
    entries: value.entries.map(parseQueueEntry),
    aggregates: parseQueueAggregates(value.aggregates),
    next_cursor: text(value.next_cursor, 512) && value.next_cursor
      ? value.next_cursor as string : null,
  };
}

function sotTile(value: unknown): Record<string, unknown> {
  if (!record(value) || value.zone_label !== "sot") throw new Error("invalid_tile_zone");
  return value;
}
function researchTile(value: unknown): Record<string, unknown> {
  if (!record(value)) throw new Error("invalid_tile_zone");
  researchZone(value);
  return value;
}

export function parseDashboard(value: unknown): Dashboard {
  if (!record(value) || !stamp(value.computed_at)) throw new Error("invalid_dashboard");
  const coverage = sotTile(value.coverage);
  const freshness = sotTile(value.freshness);
  const conflict = sotTile(value.conflict);
  const ownerReview = sotTile(value.owner_review);
  const gapFlow = sotTile(value.gap_flow);
  const intake = researchTile(value.research_intake);
  const graduation = researchTile(value.graduation);
  if (!count(coverage.total_records) || !countMap(coverage.by_source_key)
      || !countMap(coverage.by_owner) || !countMap(coverage.by_classification)
      || !count(freshness.total) || !count(freshness.expiring)
      || !count(freshness.expired) || !count(freshness.assigned)
      || !count(freshness.unassigned)
      || !count(conflict.total) || !count(conflict.disputed)
      || !count(conflict.superseded_ambiguous) || !count(conflict.assigned)
      || !count(conflict.unassigned)
      || !count(ownerReview.total) || !count(ownerReview.due)
      || !count(ownerReview.overdue) || !count(ownerReview.assigned)
      || !count(ownerReview.unassigned)
      || !count(gapFlow.open_total) || !count(gapFlow.closed_total)
      || !count(gapFlow.overdue) || !countMap(gapFlow.by_state)
      || !countMap(gapFlow.aging)
      || !count(intake.sources_total) || !count(intake.sources_active)
      || !countMap(intake.packages_by_state) || !countMap(intake.records_by_tier)
      || !count(graduation.proposed) || !count(graduation.approved)
      || !count(graduation.rejected) || !count(graduation.submitted)) {
    throw new Error("invalid_dashboard");
  }
  return {
    computed_at: value.computed_at,
    coverage: {
      zone_label: "sot", total_records: coverage.total_records,
      by_source_key: coverage.by_source_key as Record<string, number>,
      by_owner: coverage.by_owner as Record<string, number>,
      by_classification: coverage.by_classification as Record<string, number>,
    },
    freshness: {
      zone_label: "sot", total: freshness.total, expiring: freshness.expiring,
      expired: freshness.expired, assigned: freshness.assigned,
      unassigned: freshness.unassigned,
    },
    conflict: {
      zone_label: "sot", total: conflict.total, disputed: conflict.disputed,
      superseded_ambiguous: conflict.superseded_ambiguous,
      assigned: conflict.assigned, unassigned: conflict.unassigned,
    },
    owner_review: {
      zone_label: "sot", total: ownerReview.total, due: ownerReview.due,
      overdue: ownerReview.overdue, assigned: ownerReview.assigned,
      unassigned: ownerReview.unassigned,
    },
    gap_flow: {
      zone_label: "sot", open_total: gapFlow.open_total,
      closed_total: gapFlow.closed_total, overdue: gapFlow.overdue,
      by_state: gapFlow.by_state as Record<string, number>,
      aging: gapFlow.aging as Record<string, number>,
    },
    research_intake: {
      zone_label: "research", sources_total: intake.sources_total,
      sources_active: intake.sources_active,
      packages_by_state: intake.packages_by_state as Record<string, number>,
      records_by_tier: intake.records_by_tier as Record<string, number>,
    },
    graduation: {
      zone_label: "research", proposed: graduation.proposed,
      approved: graduation.approved, rejected: graduation.rejected,
      submitted: graduation.submitted,
    },
  };
}

function parsePackageItem(value: unknown): ResearchPackage {
  if (!record(value)) throw new Error("invalid_research_package");
  const zone = researchZone(value);
  if (!uuid(value.package_id) || !text(value.source_key, 200)
      || !hex64(value.fingerprint) || !hex64(value.payload_sha256)
      || !stamp(value.captured_at) || !text(value.snapshot_scope, 512)
      || !text(value.adapter_version, 64) || !countMap(value.tier_composition)
      || !IMPORT_STATES.has(value.import_state as PackageImportState)
      || !optional(value.rejection_code, input => text(input, 128))
      || !count(value.record_count) || !stamp(value.received_at)
      || !optional(value.imported_at, stamp)) {
    throw new Error("invalid_research_package");
  }
  return {
    zone_label: zone, package_id: value.package_id,
    source_key: value.source_key, fingerprint: value.fingerprint,
    payload_sha256: value.payload_sha256, captured_at: value.captured_at,
    snapshot_scope: value.snapshot_scope, adapter_version: value.adapter_version,
    tier_composition: value.tier_composition,
    import_state: value.import_state as PackageImportState,
    rejection_code: text(value.rejection_code, 128) && value.rejection_code
      ? value.rejection_code as string : null,
    record_count: value.record_count, received_at: value.received_at,
    imported_at: stamp(value.imported_at) ? value.imported_at : null,
  };
}

export function parseResearchPackage(value: unknown): ResearchPackage {
  return parsePackageItem(value);
}

export function parseResearchPackagePage(value: unknown): ResearchPackagePage {
  const page = parsePageShape(value);
  return {items: page.items.map(parsePackageItem), next_cursor: page.next_cursor};
}

function parseRecordItem(value: unknown): ResearchRecord {
  if (!record(value)) throw new Error("invalid_research_record");
  const zone = researchZone(value);
  if (!uuid(value.research_record_id) || !uuid(value.package_id)
      || !hex64(value.package_fingerprint) || !text(value.source_key, 200)
      || !text(value.record_key, 500) || !count(value.version_ordinal)
      || value.version_ordinal < 1 || !TIERS.has(value.tier as ResearchTier)
      || !record(value.content) || !text(value.searchable_text, 200_000)
      || !Array.isArray(value.evidence) || value.evidence.length < 1
      || value.evidence.length > 1000
      || !CORROBORATION.has(value.corroboration_state as CorroborationState)
      || !hex64(value.content_sha256) || !stamp(value.created_at)) {
    throw new Error("invalid_research_record");
  }
  const evidence = value.evidence.map((span): ResearchEvidence => {
    if (!record(span) || !text(span.source_url, 2048) || !record(span.locator)
        || !text(span.quoted_text, 200_000) || !hex64(span.checksum)) {
      throw new Error("invalid_research_evidence");
    }
    return {
      source_url: span.source_url, locator: span.locator,
      quoted_text: span.quoted_text, checksum: span.checksum,
    };
  });
  return {
    zone_label: zone, research_record_id: value.research_record_id,
    package_id: value.package_id, package_fingerprint: value.package_fingerprint,
    source_key: value.source_key, record_key: value.record_key,
    version_ordinal: value.version_ordinal, tier: value.tier as ResearchTier,
    content: value.content, searchable_text: value.searchable_text,
    evidence, corroboration_state: value.corroboration_state as CorroborationState,
    content_sha256: value.content_sha256, created_at: value.created_at,
  };
}

export function parseResearchRecord(value: unknown): ResearchRecord {
  return parseRecordItem(value);
}

export function parseResearchRecordPage(value: unknown): ResearchRecordPage {
  const page = parsePageShape(value);
  return {items: page.items.map(parseRecordItem), next_cursor: page.next_cursor};
}

function parseProposalItem(value: unknown): Proposal {
  if (!record(value) || !uuid(value.proposal_id)
      || !Array.isArray(value.research_record_ids)
      || value.research_record_ids.length < 1
      || value.research_record_ids.length > 100
      || value.research_record_ids.some(id => !uuid(id))
      || !record(value.claim_draft) || !text(value.target_record_key, 500)
      || !uuid(value.proposer_subject_id) || !text(value.rationale)
      || !PROPOSAL_STATES.has(value.state as ProposalState)
      || !optional(value.decided_by, uuid)
      || !optional(value.decision_reason, input => text(input))
      || !optional(value.attestation_hash, hex64)
      || !optional(value.publish_package_id, uuid)
      || !optional(value.supersedes_proposal_id, uuid)
      || !stamp(value.proposed_at) || !optional(value.decided_at, stamp)) {
    throw new Error("invalid_proposal");
  }
  return {
    proposal_id: value.proposal_id,
    research_record_ids: value.research_record_ids as string[],
    claim_draft: value.claim_draft, target_record_key: value.target_record_key,
    proposer_subject_id: value.proposer_subject_id, rationale: value.rationale,
    state: value.state as ProposalState,
    decided_by: uuid(value.decided_by) ? value.decided_by : null,
    decision_reason: text(value.decision_reason) && value.decision_reason !== undefined
      ? value.decision_reason as string : null,
    attestation_hash: hex64(value.attestation_hash) ? value.attestation_hash : null,
    publish_package_id: uuid(value.publish_package_id)
      ? value.publish_package_id : null,
    supersedes_proposal_id: uuid(value.supersedes_proposal_id)
      ? value.supersedes_proposal_id : null,
    proposed_at: value.proposed_at,
    decided_at: stamp(value.decided_at) ? value.decided_at : null,
  };
}

export function parseProposal(value: unknown): Proposal {
  return parseProposalItem(value);
}

export function parseProposalPage(value: unknown): ProposalPage {
  const page = parsePageShape(value);
  return {items: page.items.map(parseProposalItem), next_cursor: page.next_cursor};
}

/** URL-restorable workspace state; ids only, no restricted metadata. */
export type WorkspaceView =
  | "dashboard" | "gaps" | "freshness" | "conflict" | "owner-review"
  | "research" | "graduation";
export type WorkspaceState = {
  view: WorkspaceView;
  gapId?: string; packageId?: string; recordId?: string; proposalId?: string;
  gapState?: GapState; gapPriority?: GapPriority;
};

const VIEWS = new Set<WorkspaceView>([
  "dashboard", "gaps", "freshness", "conflict", "owner-review",
  "research", "graduation",
]);

export function parseWorkspaceState(params: URLSearchParams): WorkspaceState {
  const view = params.get("view");
  const state: WorkspaceState = {
    view: VIEWS.has(view as WorkspaceView) ? view as WorkspaceView : "dashboard",
  };
  const gapId = params.get("gap");
  const packageId = params.get("package");
  const recordId = params.get("record");
  const proposalId = params.get("proposal");
  const gapState = params.get("state");
  const gapPriority = params.get("priority");
  if (uuid(gapId)) state.gapId = gapId;
  if (uuid(packageId)) state.packageId = packageId;
  if (uuid(recordId)) state.recordId = recordId;
  if (uuid(proposalId)) state.proposalId = proposalId;
  if (GAP_STATES.has(gapState as GapState)) state.gapState = gapState as GapState;
  if (GAP_PRIORITIES.has(gapPriority as GapPriority)) {
    state.gapPriority = gapPriority as GapPriority;
  }
  return state;
}

export function workspaceQuery(state: WorkspaceState): string {
  const params = new URLSearchParams();
  if (state.view !== "dashboard") params.set("view", state.view);
  if (state.gapId) params.set("gap", state.gapId);
  if (state.packageId) params.set("package", state.packageId);
  if (state.recordId) params.set("record", state.recordId);
  if (state.proposalId) params.set("proposal", state.proposalId);
  if (state.gapState) params.set("state", state.gapState);
  if (state.gapPriority) params.set("priority", state.gapPriority);
  return params.toString();
}
