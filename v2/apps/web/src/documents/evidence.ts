/**
 * Documents-surface adapter for the shared Evidence Rail (TIP-011 Task 3).
 *
 * Each locked SOT fact of a bind result maps to one `EvidenceEntry`
 * carrying the record key, record/evidence checksums, provenance and
 * freshness exactly as the bind API returned them. The bind payload carries
 * NO server zone label, so `zone` stays null and no chip renders (AC-02 —
 * the client never guesses a zone).
 */

import type {EvidenceEntry} from "../rail/contracts";

export type LockedField = {
  field_path: string;
  source: string;
  value: unknown;
  record_key?: string | null;
  record_checksum?: string | null;
  evidence_checksum?: string | null;
  provenance_level?: string | null;
  freshness_state?: string | null;
};

export function lockedFieldEvidence(field: LockedField): EvidenceEntry {
  return {
    key: `locked-${field.field_path}`,
    marker: null,
    zone: null,
    grounding: null,
    tier: null,
    sourceKey: field.record_key ?? "",
    sourceLabel: field.field_path,
    sourceRevision: null,
    recordKey: field.record_key ?? field.field_path,
    recordVersionId: null,
    versionOrdinal: null,
    evidenceKey: null,
    recordChecksum: field.record_checksum ?? null,
    evidenceChecksums: field.evidence_checksum ? [field.evidence_checksum] : [],
    contentChecksum: null,
    provenanceLevel: field.provenance_level ?? null,
    verificationState: null,
    freshnessState: field.freshness_state ?? null,
    corroborationState: null,
    redacted: false,
    locator: null,
    snippet: field.value === null || field.value === undefined
      ? null
      : String(field.value),
  };
}
