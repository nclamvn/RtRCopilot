/**
 * Knowledge-Ops adapters for the shared Evidence Rail (TIP-011 Task 3).
 *
 * Zone values come ONLY from literal server `zone_label` payload fields —
 * gaps and queue payloads carry the SOT literal since TIP-011 (AC-07), and
 * research records carry the research literal since TIP-010. A payload
 * without a label yields `zone: null` and no chip renders.
 */

import type {EvidenceEntry} from "../rail/contracts";
import type {Gap, ResearchRecord} from "./contracts";

export function gapEvidence(gap: Gap): EvidenceEntry {
  return {
    key: `gap-${gap.gap_id}`,
    marker: null,
    zone: gap.zone_label,
    grounding: null,
    tier: null,
    sourceKey: gap.routing_key,
    sourceLabel: gap.sanitized_summary || gap.sanitized_question,
    sourceRevision: null,
    recordKey: gap.gap_id,
    recordVersionId: null,
    versionOrdinal: null,
    evidenceKey: null,
    recordChecksum: null,
    evidenceChecksums: [],
    contentChecksum: gap.question_fingerprint,
    provenanceLevel: null,
    verificationState: null,
    freshnessState: null,
    corroborationState: null,
    redacted: false,
    locator: null,
    snippet: null,
  };
}

export function researchRecordEvidence(record: ResearchRecord): EvidenceEntry {
  return {
    key: `research-${record.research_record_id}`,
    marker: null,
    zone: record.zone_label,
    grounding: null,
    tier: record.tier,
    sourceKey: record.source_key,
    sourceLabel: record.record_key,
    sourceRevision: null,
    recordKey: record.record_key,
    recordVersionId: null,
    versionOrdinal: record.version_ordinal,
    evidenceKey: null,
    recordChecksum: null,
    evidenceChecksums: record.evidence.map(span => span.checksum),
    contentChecksum: record.content_sha256,
    provenanceLevel: null,
    verificationState: null,
    freshnessState: null,
    corroborationState: record.corroboration_state,
    redacted: false,
    locator: null,
    snippet: record.evidence[0]?.quoted_text.slice(0, 300) ?? null,
  };
}
