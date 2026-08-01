import React from "react";
import type {EvidenceZone} from "./contracts";

const ZONE_TEXT: Record<EvidenceZone, string> = {
  sot: "SOT",
  research: "RESEARCH",
  private: "PRIVATE",
};

/**
 * Signature element: the persistent trust-zone chip, lifted verbatim from
 * Knowledge Ops (TIP-010) into the shared rail module (TIP-011 Task 2).
 * The `zone` value must come from an API response (`zone_label` on research
 * payloads and dashboard tiles); callers without a server-provided label pass
 * null and no chip renders — the client never guesses a zone.
 */
export function ZoneChip({zone}: {zone: EvidenceZone | null | undefined}) {
  if (zone !== "sot" && zone !== "research" && zone !== "private") return null;
  return <span className={`zone-chip zone-${zone}`}>{ZONE_TEXT[zone]}</span>;
}
