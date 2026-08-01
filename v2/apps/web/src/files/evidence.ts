/**
 * Files-surface adapter for the shared Evidence Rail (TIP-011 Task 3).
 *
 * One viewer manifest maps to one `EvidenceEntry`: the immutable file
 * version id, the source checksum and the current rtr.locator.v1 position.
 * File manifests carry NO server zone label, so `zone` stays null and the
 * chip never renders — the client does not guess a zone (AC-02).
 */

import type {EvidenceEntry} from "../rail/contracts";
import type {FileItem, Locator, ViewerManifest} from "./contracts";

export function manifestEvidence(
  manifest: ViewerManifest,
  file: FileItem | null,
  locator: Locator,
  fallbackLabel: string,
): EvidenceEntry {
  return {
    key: `file-${manifest.version_id}`,
    marker: null,
    zone: null,
    grounding: null,
    tier: null,
    sourceKey: manifest.viewer_kind,
    sourceLabel: file?.display_filename ?? fallbackLabel,
    sourceRevision: null,
    recordKey: file?.logical_name ?? manifest.version_id,
    recordVersionId: manifest.version_id,
    versionOrdinal: null,
    evidenceKey: null,
    recordChecksum: manifest.source_sha256,
    evidenceChecksums: [],
    contentChecksum: null,
    provenanceLevel: null,
    verificationState: null,
    freshnessState: null,
    corroborationState: null,
    redacted: false,
    locator: Object.keys(locator).length > 0 ? locator : null,
    snippet: null,
  };
}
