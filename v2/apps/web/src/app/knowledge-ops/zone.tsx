import React from "react";
import {Proposal} from "../../governance/contracts";

/**
 * TIP-011 Task 2: the trust-zone chip now lives in the shared rail module
 * (`src/rail/ZoneChip`) so Ask, Files, Documents and Knowledge Ops render
 * the identical element. Re-exported here with zero behavior change.
 */
export {ZoneChip} from "../../rail/ZoneChip";

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
