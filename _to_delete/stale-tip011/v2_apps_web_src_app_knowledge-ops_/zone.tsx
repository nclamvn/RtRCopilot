import React from "react";
import {Proposal, TrustZone} from "../../governance/contracts";

const ZONE_TEXT: Record<TrustZone, string> = {
  sot: "SOT",
  research: "RESEARCH",
  private: "PRIVATE",
};

/**
 * Signature element: the persistent trust-zone chip. The `zone` value must
 * come from an API response (`zone_label` on research payloads and dashboard
 * tiles); callers without a server-provided label pass null and no chip
 * renders — the client never guesses a zone.
 */
export function ZoneChip({zone}: {zone: TrustZone | null | undefined}) {
  if (zone !== "sot" && zone !== "research" && zone !== "private") return null;
  return <span className={`zone-chip zone-${zone}`}>{ZONE_TEXT[zone]}</span>;
}

export type CrossingPhase =
  | "proposed" | "approved_staged" | "approved_unsubmitted" | "rejected";

export function crossingPhase(proposal: Proposal): CrossingPhase {
  if (proposal.state === "proposed") return "proposed";
  if (proposal.state === "rejected") return "rejected";
  return proposal.publish_package_id ? "approved_staged" : "approved_unsubmitted";
}

const PHASE_TEXT: Record<CrossingPhase, string> = {
  proposed:
    "Đề xuất đang ở vùng RESEARCH, chờ một curator khác quyết định trước cổng phát hành.",
  approved_staged:
    "Đã duyệt: bản nháp claim dừng tại cổng phát hành SOT, chưa kích hoạt — cổng vẫn có thể từ chối.",
  approved_unsubmitted:
    "Đã duyệt nhưng chưa vào được cổng phát hành; cần đề xuất lại để nộp.",
  rejected:
    "Bị từ chối: đề xuất ở lại vùng RESEARCH, quyết định là bất biến.",
};

/**
 * Graduation as a gated crossing: the proposal marker moves toward the SOT
 * zone and stops at the publish gate — it never enters the SOT box and there
 * is no drag-and-drop implying direct transfer. The same state is always
 * conveyed as text, so reduced-motion users lose nothing.
 */
export function GatedCrossing({proposal}: {proposal: Proposal}) {
  const phase = crossingPhase(proposal);
  return <figure className="gated-crossing">
    <div className="crossing-track" role="img" aria-label={PHASE_TEXT[phase]}>
      <span className="crossing-zone research" aria-hidden>RESEARCH</span>
      <span className={`crossing-marker ${phase}`} aria-hidden>
        {phase === "rejected" ? "×" : "▸"}
      </span>
      <span className="crossing-gate" aria-hidden>CỔNG PHÁT HÀNH</span>
      <span className="crossing-zone sot" aria-hidden>SOT</span>
    </div>
    <figcaption data-phase={phase}>{PHASE_TEXT[phase]}</figcaption>
  </figure>;
}
