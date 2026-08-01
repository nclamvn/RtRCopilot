import React from "react";
import {Proposal} from "../../../governance/contracts";
import type {MessageKey} from "../../../i18n/messages";
import {useI18n} from "../../../i18n/provider";

/**
 * TIP-011: the trust-zone chip lives in the shared rail module
 * (`src/rail/ZoneChip`); the temporary re-export shim was collapsed when
 * this workspace adopted the shell — import the chip from `src/rail`.
 * `GatedCrossing` stays knowledge-ops-local (it is not the rail).
 */

export type CrossingPhase =
  | "proposed" | "approved_staged" | "approved_unsubmitted" | "rejected";

export function crossingPhase(proposal: Proposal): CrossingPhase {
  if (proposal.state === "proposed") return "proposed";
  if (proposal.state === "rejected") return "rejected";
  return proposal.publish_package_id ? "approved_staged" : "approved_unsubmitted";
}

const PHASE_KEYS: Record<CrossingPhase, MessageKey> = {
  proposed: "ops.crossing.proposed",
  approved_staged: "ops.crossing.approvedStaged",
  approved_unsubmitted: "ops.crossing.approvedUnsubmitted",
  rejected: "ops.crossing.rejected",
};

/**
 * Graduation as a gated crossing: the proposal marker moves toward the SOT
 * zone and stops at the publish gate — it never enters the SOT box and there
 * is no drag-and-drop implying direct transfer. The same state is always
 * conveyed as text, so reduced-motion users lose nothing.
 */
export function GatedCrossing({proposal}: {proposal: Proposal}) {
  const {t} = useI18n();
  const phase = crossingPhase(proposal);
  return <figure className="gated-crossing">
    <div className="crossing-track" role="img" aria-label={t(PHASE_KEYS[phase])}>
      <span className="crossing-zone research" aria-hidden>RESEARCH</span>
      <span className={`crossing-marker ${phase}`} aria-hidden>
        {phase === "rejected" ? "×" : "▸"}
      </span>
      <span className="crossing-gate" aria-hidden>{t("ops.crossing.gate")}</span>
      <span className="crossing-zone sot" aria-hidden>SOT</span>
    </div>
    <figcaption data-phase={phase}>{t(PHASE_KEYS[phase])}</figcaption>
  </figure>;
}
