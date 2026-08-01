"use client";

/**
 * Knowledge Ops workspace (TIP-010), living inside the unified shell since
 * TIP-011: the AppShell owns the topbar/nav/`<main>`; this page renders ONE
 * `PageHeader`, the queue ledger + work surface, and the SHARED Evidence
 * Rail (`src/rail`). Zone chips render ONLY from literal server
 * `zone_label` payload fields — gaps/queues carry them since TIP-011
 * (AC-07), so no chip waits on the dashboard response.
 *
 * TIP-011 Task 4: the assign and gap-answer forms consume the
 * policy-filtered pickers (`src/governance/Picker`) instead of raw-UUID
 * inputs; every user-visible string comes from the i18n catalog (AC-09).
 */

import React, {useCallback, useEffect, useMemo, useState} from "react";
import {
  Dashboard,
  Gap,
  GapDetail,
  GapPage,
  GapPriority,
  GapState,
  parseDashboard,
  parseGapDetail,
  parseGapPage,
  parseProposal,
  parseProposalPage,
  parseQueuePage,
  parseResearchPackagePage,
  parseResearchRecord,
  parseResearchRecordPage,
  parseTypedError,
  parseWorkspaceState,
  Proposal,
  ProposalPage,
  QueueEntry,
  QueuePage,
  ResearchPackagePage,
  ResearchRecord,
  ResearchRecordPage,
  TypedError,
  workspaceQuery,
  WorkspaceState,
  WorkspaceView,
} from "../../../governance/contracts";
import {gapEvidence, researchRecordEvidence} from "../../../governance/evidence";
import {PickerCombobox, PickerSelection} from "../../../governance/Picker";
import {formatDateTime} from "../../../i18n/format";
import type {Locale, MessageKey} from "../../../i18n/messages";
import {useI18n} from "../../../i18n/provider";
import type {EvidenceEntry} from "../../../rail/contracts";
import {EvidenceRail} from "../../../rail/EvidenceRail";
import {ZoneChip} from "../../../rail/ZoneChip";
import {IDLE, Surface, errorText, type Load} from "../../../shared/surface";
import {PageHeader} from "../../../shell/AppShell";
import {GatedCrossing} from "./zone";

type Identity = {user_id: string; email: string; display_name: string; roles: string[]};
type Evidence = {records: ResearchRecord[]; missing: number};
type Translate = (key: MessageKey) => string;

const QUEUE_VIEWS: Record<string, "freshness" | "conflict" | "owner-review"> = {
  freshness: "freshness", conflict: "conflict", "owner-review": "owner-review",
};
const GAP_STATES: GapState[] = [
  "open", "triaged", "assigned", "answered", "published", "declined",
];
const GAP_PRIORITIES: GapPriority[] = ["low", "normal", "high", "urgent"];
const STATUS_KEYS: Record<string, MessageKey> = {
  expiring: "ops.status.expiring", expired: "ops.status.expired",
  due: "ops.status.due", overdue: "ops.status.overdue",
  disputed: "ops.status.disputed",
  superseded_ambiguous: "ops.status.supersededAmbiguous",
};

const api = (path: string, init?: RequestInit) => fetch(`/api/governance/${path}`, {
  cache: "no-store", ...init,
  headers: {"content-type": "application/json", ...(init?.headers ?? {})},
});

function when(value: string | null, locale: Locale) {
  return value ? formatDateTime(value, locale) : "—";
}

function statusText(status: string, t: Translate) {
  const key = STATUS_KEYS[status];
  return key ? t(key) : status;
}

function slaBadge(gap: Gap, t: Translate, locale: Locale) {
  if (!gap.due_at || gap.closed_at) return null;
  const overdue = Date.parse(gap.due_at) <= Date.now();
  return <span className={`sla-badge ${overdue ? "overdue" : ""}`}>
    {overdue ? t("ops.sla.overdue") : `${t("ops.sla.due")} ${when(gap.due_at, locale)}`}
  </span>;
}

export default function KnowledgeOpsPage() {
  const {t, locale} = useI18n();
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [ws, setWs] = useState<WorkspaceState>({view: "dashboard"});
  const [dash, setDash] = useState<Load<Dashboard>>(IDLE);
  const [gaps, setGaps] = useState<Load<GapPage>>(IDLE);
  const [gapDetail, setGapDetail] = useState<Load<GapDetail>>(IDLE);
  const [queue, setQueue] = useState<Load<QueuePage>>(IDLE);
  const [packages, setPackages] = useState<Load<ResearchPackagePage>>(IDLE);
  const [records, setRecords] = useState<Load<ResearchRecordPage>>(IDLE);
  const [researchRecord, setResearchRecord] = useState<Load<ResearchRecord>>(IDLE);
  const [proposals, setProposals] = useState<Load<ProposalPage>>(IDLE);
  const [proposal, setProposal] = useState<Load<Proposal>>(IDLE);
  const [evidence, setEvidence] = useState<Load<Evidence>>(IDLE);
  const [actionError, setActionError] = useState<TypedError | null>(null);
  const [notice, setNotice] = useState<MessageKey | "">("");
  const [reason, setReason] = useState("");
  const [assigneePick, setAssigneePick] = useState<PickerSelection | null>(null);
  const [resolvingPick, setResolvingPick] = useState<PickerSelection | null>(null);
  const [claimText, setClaimText] = useState("");
  const [claimClassification, setClaimClassification] = useState("internal");
  const [targetKey, setTargetKey] = useState("");
  const [rationale, setRationale] = useState("");
  const [composerOpen, setComposerOpen] = useState(false);
  const [ledgerOpen, setLedgerOpen] = useState(false);
  const [railOpen, setRailOpen] = useState(false);

  const loseAccess = useCallback(() => {
    setIdentity(null);
    setDash(IDLE);
    setGaps(IDLE); setGapDetail(IDLE); setQueue(IDLE);
    setPackages(IDLE); setRecords(IDLE); setResearchRecord(IDLE);
    setProposals(IDLE); setProposal(IDLE); setEvidence(IDLE);
    setActionError(null); setNotice("");
  }, []);

  const fetchInto = useCallback(async function fetchInto<T>(
    path: string,
    parse: (value: unknown) => T,
    set: (load: Load<T>) => void,
  ) {
    set({state: "loading"});
    try {
      const response = await api(path);
      if (response.status === 401) return loseAccess();
      const body: unknown = await response.json().catch(() => null);
      if (response.status === 403) {
        return set({state: "denied", error: parseTypedError(body)});
      }
      if (!response.ok) return set({state: "error", error: parseTypedError(body)});
      set({state: "ready", data: parse(body)});
    } catch {
      set({state: "error", error: {
        code: "contract_violation", message: "", requestId: "",
      }});
    }
  }, [loseAccess]);

  const apply = useCallback((next: WorkspaceState, push = true) => {
    setWs(next);
    setActionError(null); setNotice(""); setComposerOpen(false);
    setLedgerOpen(false);
    const query = workspaceQuery(next);
    const url = query ? `/knowledge-ops?${query}` : "/knowledge-ops";
    if (push) history.pushState({}, "", url);
    else history.replaceState({}, "", url);
  }, []);

  useEffect(() => {
    fetch("/api/auth/me", {cache: "no-store"})
      .then(async response => setIdentity(
        response.ok ? await response.json() as Identity : null,
      ))
      .catch(() => setIdentity(null)).finally(() => setAuthReady(true));
    const restore = () => setWs(parseWorkspaceState(
      new URLSearchParams(location.search),
    ));
    restore();
    addEventListener("popstate", restore);
    return () => removeEventListener("popstate", restore);
  }, []);
  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setLedgerOpen(false); setRailOpen(false); }
    };
    addEventListener("keydown", close);
    return () => removeEventListener("keydown", close);
  }, []);

  // The dashboard carries ALL six SOT/research tiles incl. conflict and
  // owner-review since TIP-011, so the ledger needs no extra queue fetches.
  const loadLedger = useCallback(() => {
    void fetchInto("governance/dashboard", parseDashboard, setDash);
  }, [fetchInto]);
  useEffect(() => {
    if (!identity) return;
    const timer = setTimeout(loadLedger, 0);
    return () => clearTimeout(timer);
  }, [identity, loadLedger]);

  const loadGaps = useCallback(() => {
    const params = new URLSearchParams({limit: "50"});
    if (ws.gapState) params.set("state", ws.gapState);
    if (ws.gapPriority) params.set("priority", ws.gapPriority);
    void fetchInto(`gaps?${params}`, parseGapPage, setGaps);
  }, [fetchInto, ws.gapState, ws.gapPriority]);
  const loadGapDetail = useCallback(() => {
    if (ws.gapId) void fetchInto(`gaps/${ws.gapId}`, parseGapDetail, setGapDetail);
  }, [fetchInto, ws.gapId]);
  useEffect(() => {
    if (!identity || ws.view !== "gaps") return;
    const timer = setTimeout(loadGaps, 0);
    return () => clearTimeout(timer);
  }, [identity, ws.view, loadGaps]);
  useEffect(() => {
    if (!identity || ws.view !== "gaps") return;
    const timer = setTimeout(() => {
      if (ws.gapId) loadGapDetail();
      else setGapDetail(IDLE);
    }, 0);
    return () => clearTimeout(timer);
  }, [identity, ws.view, ws.gapId, loadGapDetail]);

  const queueView = QUEUE_VIEWS[ws.view] ?? null;
  const loadQueue = useCallback(() => {
    if (queueView) {
      void fetchInto(`governance/queues/${queueView}?limit=50`, parseQueuePage, setQueue);
    }
  }, [fetchInto, queueView]);
  useEffect(() => {
    if (!identity || !queueView) return;
    const timer = setTimeout(loadQueue, 0);
    return () => clearTimeout(timer);
  }, [identity, queueView, loadQueue]);

  const loadPackages = useCallback(() => {
    void fetchInto("research/packages?limit=50", parseResearchPackagePage, setPackages);
  }, [fetchInto]);
  useEffect(() => {
    if (!identity || ws.view !== "research") return;
    const timer = setTimeout(loadPackages, 0);
    return () => clearTimeout(timer);
  }, [identity, ws.view, loadPackages]);
  useEffect(() => {
    if (!identity || ws.view !== "research") return;
    const timer = setTimeout(() => {
      if (!ws.packageId) { setRecords(IDLE); return; }
      void fetchInto(
        `research/packages/${ws.packageId}/records?limit=50`,
        parseResearchRecordPage,
        setRecords,
      );
    }, 0);
    return () => clearTimeout(timer);
  }, [identity, ws.view, ws.packageId, fetchInto]);
  useEffect(() => {
    if (!identity || ws.view !== "research") return;
    const timer = setTimeout(() => {
      if (!ws.recordId) { setResearchRecord(IDLE); return; }
      void fetchInto(`research/records/${ws.recordId}`, parseResearchRecord, setResearchRecord);
    }, 0);
    return () => clearTimeout(timer);
  }, [identity, ws.view, ws.recordId, fetchInto]);

  const loadProposals = useCallback(() => {
    void fetchInto("graduation/proposals?limit=50", parseProposalPage, setProposals);
  }, [fetchInto]);
  const loadProposal = useCallback(() => {
    if (ws.proposalId) {
      void fetchInto(`graduation/proposals/${ws.proposalId}`, parseProposal, setProposal);
    }
  }, [fetchInto, ws.proposalId]);
  useEffect(() => {
    if (!identity || ws.view !== "graduation") return;
    const timer = setTimeout(loadProposals, 0);
    return () => clearTimeout(timer);
  }, [identity, ws.view, loadProposals]);
  useEffect(() => {
    if (!identity || ws.view !== "graduation") return;
    const timer = setTimeout(() => {
      if (ws.proposalId) loadProposal();
      else { setProposal(IDLE); setEvidence(IDLE); }
    }, 0);
    return () => clearTimeout(timer);
  }, [identity, ws.view, ws.proposalId, loadProposal]);
  useEffect(() => {
    let active = true;
    const timer = setTimeout(() => {
      if (proposal.state !== "ready") { setEvidence(IDLE); return; }
      setEvidence({state: "loading"});
      Promise.all(proposal.data.research_record_ids.slice(0, 10).map(async id => {
        const response = await api(`research/records/${id}`);
        if (response.status === 401) throw new Error("session_expired");
        if (!response.ok) return null;
        return parseResearchRecord(await response.json());
      })).then(loaded => {
        if (!active) return;
        const present = loaded.filter((item): item is ResearchRecord => item !== null);
        setEvidence({state: "ready", data: {
          records: present, missing: loaded.length - present.length,
        }});
      }).catch(error => {
        if (!active) return;
        if (error instanceof Error && error.message === "session_expired") loseAccess();
        else setEvidence({state: "error", error: {
          code: "contract_violation", message: "", requestId: "",
        }});
      });
    }, 0);
    return () => { active = false; clearTimeout(timer); };
  }, [proposal, loseAccess]);

  const act = useCallback(async (
    path: string,
    body: Record<string, unknown>,
    onDone: () => void,
    done: MessageKey,
  ) => {
    setActionError(null); setNotice("");
    try {
      const response = await api(path, {method: "POST", body: JSON.stringify(body)});
      if (response.status === 401) return loseAccess();
      if (!response.ok) {
        const envelope: unknown = await response.json().catch(() => null);
        return setActionError(parseTypedError(envelope));
      }
      setNotice(done);
      onDone();
    } catch {
      setActionError({code: "governance_service_unavailable", message: "", requestId: ""});
    }
  }, [loseAccess]);

  const gapAction = useCallback((operation: string, extra: Record<string, unknown>) => {
    if (!ws.gapId) return;
    void act(
      `gaps/${ws.gapId}/${operation}`,
      {reason: reason.trim() || t("ops.reason.default"), ...extra},
      () => { loadGapDetail(); loadGaps(); loadLedger(); },
      "ops.notice.transition",
    );
  }, [act, ws.gapId, reason, t, loadGapDetail, loadGaps, loadLedger]);

  const assignQueueEntry = useCallback((entry: QueueEntry) => {
    if (!queueView || !assigneePick) return;
    void act(
      `governance/queues/${queueView}/assign`,
      {
        record_version_id: entry.record_version_id,
        assignee_subject_id: assigneePick.id,
        note: reason.trim(),
      },
      () => { loadQueue(); loadLedger(); },
      "ops.notice.assigned",
    );
  }, [act, queueView, assigneePick, reason, loadQueue, loadLedger]);

  const completeTask = useCallback((taskId: string) => {
    void act(
      `governance/review-tasks/${taskId}/complete`,
      {},
      () => { loadQueue(); loadLedger(); },
      "ops.notice.completed",
    );
  }, [act, loadQueue, loadLedger]);

  const propose = useCallback((record: ResearchRecord) => {
    void act(
      "graduation/proposals",
      {
        research_record_ids: [record.research_record_id],
        claim: {
          claim_text: claimText.trim(),
          classification: claimClassification,
        },
        target_record_key: targetKey.trim() || record.record_key,
        rationale: rationale.trim() || t("ops.reason.propose"),
      },
      () => { setComposerOpen(false); loadLedger(); },
      "ops.notice.proposed",
    );
  }, [act, claimText, claimClassification, targetKey, rationale, t, loadLedger]);

  const decide = useCallback((decision: "approved" | "rejected") => {
    if (!ws.proposalId) return;
    void act(
      `graduation/proposals/${ws.proposalId}/decide`,
      {decision, reason: reason.trim() || t("ops.reason.decide")},
      () => { loadProposal(); loadProposals(); loadLedger(); },
      decision === "approved" ? "ops.notice.approved" : "ops.notice.rejected",
    );
  }, [act, ws.proposalId, reason, t, loadProposal, loadProposals, loadLedger]);

  /** Ledger/graduation rows without their own payload label reuse the
   *  dashboard tiles' server labels (payload data, never a client guess). */
  const sotZone = dash.state === "ready" ? dash.data.gap_flow.zone_label : null;
  const researchZone = dash.state === "ready"
    ? dash.data.research_intake.zone_label : null;

  const ledgerRows = useMemo(() => {
    const d = dash.state === "ready" ? dash.data : null;
    const rows: Array<{
      view: WorkspaceView; label: string; zone: "sot" | "research" | null;
      count: string; badge: string;
    }> = [
      {view: "gaps", label: t("ops.row.gaps"), zone: sotZone,
        count: d ? String(d.gap_flow.open_total) : "…",
        badge: d && d.gap_flow.overdue > 0
          ? `${d.gap_flow.overdue} ${t("ops.badge.overdueSla")}` : ""},
      {view: "freshness", label: t("ops.row.freshness"), zone: sotZone,
        count: d ? String(d.freshness.total) : "…",
        badge: d && d.freshness.expired > 0
          ? `${d.freshness.expired} ${t("ops.badge.expired")}` : ""},
      {view: "conflict", label: t("ops.row.conflict"), zone: sotZone,
        count: d ? String(d.conflict.total) : "…",
        badge: d && d.conflict.disputed > 0
          ? `${d.conflict.disputed} ${t("ops.badge.disputed")}` : ""},
      {view: "owner-review", label: t("ops.row.ownerReview"), zone: sotZone,
        count: d ? String(d.owner_review.total) : "…",
        badge: d && d.owner_review.overdue > 0
          ? `${d.owner_review.overdue} ${t("ops.badge.overdue")}` : ""},
      {view: "research", label: t("ops.row.research"), zone: researchZone,
        count: d ? String(Object.values(d.research_intake.packages_by_state)
          .reduce((sum, item) => sum + item, 0)) : "…",
        badge: d && (d.research_intake.packages_by_state.rejected ?? 0) > 0
          ? `${d.research_intake.packages_by_state.rejected} ${t("ops.badge.rejected")}`
          : ""},
      {view: "graduation", label: t("ops.row.graduation"), zone: researchZone,
        count: d ? String(d.graduation.proposed) : "…",
        badge: d && d.graduation.submitted > 0
          ? `${d.graduation.submitted} ${t("ops.badge.atGate")}` : ""},
    ];
    return rows;
  }, [dash, sotZone, researchZone, t]);

  const selectedGap = gapDetail.state === "ready" ? gapDetail.data : null;
  const selectedRecord = researchRecord.state === "ready" ? researchRecord.data : null;
  const selectedProposal = proposal.state === "ready" ? proposal.data : null;
  const selectedPackage = packages.state === "ready"
    ? packages.data.items.find(item => item.package_id === ws.packageId) ?? null
    : null;
  const queuePage = queue.state === "ready" ? queue.data : null;

  const railEntries = useMemo<EvidenceEntry[]>(() => {
    if (ws.view === "gaps" && selectedGap) return [gapEvidence(selectedGap.gap)];
    if (ws.view === "research" && selectedRecord) {
      return [researchRecordEvidence(selectedRecord)];
    }
    return [];
  }, [ws.view, selectedGap, selectedRecord]);

  const railNote = useMemo<React.ReactNode>(() => {
    if (ws.view === "dashboard") {
      return <dl className="rail-facts">
        <div><dt>{t("rail.zone")}</dt><dd>{t("ops.rail.zoneNote")}</dd></div>
        {dash.state === "ready" && <div><dt>{t("ops.rail.computedAt")}</dt>
          <dd>{when(dash.data.computed_at, locale)}</dd></div>}
      </dl>;
    }
    if (ws.view === "gaps" && selectedGap) {
      return <dl className="rail-facts">
        <div><dt>{t("ops.rail.classification")}</dt>
          <dd>{selectedGap.gap.classification}</dd></div>
        <div><dt>{t("ops.rail.origin")}</dt><dd>{selectedGap.gap.origin}</dd></div>
        {selectedGap.gap.resolving_version_id
          && <div><dt>{t("ops.rail.resolvingVersion")}</dt>
            <dd><code>{selectedGap.gap.resolving_version_id}</code></dd></div>}
        {selectedGap.gap.decline_reason && <div><dt>{t("ops.rail.declineReason")}</dt>
          <dd>{selectedGap.gap.decline_reason}</dd></div>}
      </dl>;
    }
    if (queueView && queuePage) {
      return <dl className="rail-facts">
        <div><dt>{t("ops.rail.zone")}</dt>
          <dd><ZoneChip zone={queuePage.zone_label}/></dd></div>
        <div><dt>{t("ops.rail.method")}</dt><dd>{t("ops.rail.queueNote")}</dd></div>
        <div><dt>{t("ops.rail.computedAt")}</dt>
          <dd>{when(queuePage.computed_at, locale)}</dd></div>
        {Object.entries(queuePage.aggregates.by_status).map(([key, value]) =>
          <div key={key}><dt>{statusText(key, t)}</dt><dd>{value}</dd></div>)}
      </dl>;
    }
    if (ws.view === "research" && selectedRecord && selectedPackage) {
      return <dl className="rail-facts">
        <div><dt>{t("ops.rail.snapshot")}</dt><dd>{selectedPackage.snapshot_scope} ·
          {" "}{when(selectedPackage.captured_at, locale)}</dd></div>
        <div><dt>{t("ops.rail.adapter")}</dt>
          <dd><code>{selectedPackage.adapter_version}</code></dd></div>
      </dl>;
    }
    if (ws.view === "research" && !selectedRecord && selectedPackage) {
      return <dl className="rail-facts">
        <div><dt>{t("ops.rail.zone")}</dt>
          <dd><ZoneChip zone={selectedPackage.zone_label}/></dd></div>
        <div><dt>{t("ops.rail.fingerprint")}</dt>
          <dd><code title={selectedPackage.fingerprint}>
            {selectedPackage.fingerprint.slice(0, 16)}…</code></dd></div>
        <div><dt>{t("ops.rail.snapshot")}</dt><dd>{selectedPackage.snapshot_scope} ·
          {" "}{when(selectedPackage.captured_at, locale)}</dd></div>
        <div><dt>{t("ops.rail.importState")}</dt><dd>{selectedPackage.import_state}
          {selectedPackage.rejection_code && <> · {selectedPackage.rejection_code}</>}
        </dd></div>
      </dl>;
    }
    if (ws.view === "graduation" && selectedProposal) {
      return <dl className="rail-facts">
        <div><dt>{t("ops.rail.zone")}</dt><dd><ZoneChip zone={researchZone}/></dd></div>
        <div><dt>{t("ops.rail.state")}</dt><dd>{selectedProposal.state}</dd></div>
        {selectedProposal.attestation_hash && <div><dt>{t("ops.rail.attestation")}</dt>
          <dd><code title={selectedProposal.attestation_hash}>
            {selectedProposal.attestation_hash.slice(0, 16)}…</code></dd></div>}
        {selectedProposal.publish_package_id
          && <div><dt>{t("ops.rail.publishPackage")}</dt>
            <dd><code>{selectedProposal.publish_package_id}</code></dd></div>}
        {selectedProposal.supersedes_proposal_id
          && <div><dt>{t("ops.rail.supersedes")}</dt>
            <dd><code>{selectedProposal.supersedes_proposal_id}</code></dd></div>}
        <div><dt>{t("ops.rail.lineage")}</dt>
          <dd>{selectedProposal.research_record_ids.length}
            {" "}{t("ops.rail.lineageSuffix")}</dd></div>
      </dl>;
    }
    return <p className="surface-empty">{t("ops.rail.pick")}</p>;
  }, [
    ws.view, dash, selectedGap, queueView, queuePage, selectedRecord,
    selectedPackage, selectedProposal, researchZone, t, locale,
  ]);

  if (!authReady || !identity) {
    return <>
      <PageHeader eyebrow={t("ops.eyebrow")} title={t("ops.title")}/>
      <section className="placeholder-card">
        {!authReady && <p role="status">{t("shell.sessionChecking")}</p>}
        {authReady && <p className="lede">{t("ops.gate.lede")}</p>}
      </section>
    </>;
  }

  return <div className="ops-workspace-embed">
    <PageHeader eyebrow={t("ops.eyebrow")} title={t("ops.title")}
      actions={<div className="page-actions">
        <button className="ledger-toggle" type="button"
          onClick={() => {setRailOpen(false); setLedgerOpen(true);}}>
          {t("ops.ledgerButton")}
        </button>
        <button className="rail-sheet-toggle" type="button"
          onClick={() => {setLedgerOpen(false); setRailOpen(true);}}>
          {t("rail.toggle")}
        </button>
      </div>}/>
    <div className="ops-layout">
    <nav className={`ops-ledger ${ledgerOpen ? "open" : ""}`} aria-label={t("ops.ledgerLabel")}>
      <div className="panel-heading">
        <p className="eyebrow">{t("ops.eyebrow")}</p>
        <button className="close-mobile" type="button" aria-label={t("ops.ledgerClose")}
          onClick={() => setLedgerOpen(false)}>×</button>
      </div>
      <ol className="queue-list">
        <li><button type="button"
          aria-current={ws.view === "dashboard" ? "true" : undefined}
          onClick={() => apply({view: "dashboard"})}>
          <strong>{t("ops.row.dashboard")}</strong>
          <small>{t("ops.row.dashboardSub")}</small>
        </button></li>
        {ledgerRows.map(row => <li key={row.view}><button type="button"
          aria-current={ws.view === row.view ? "true" : undefined}
          onClick={() => apply({view: row.view})}>
          <span className="queue-head"><ZoneChip zone={row.zone}/>
            <strong>{row.label}</strong><output>{row.count}</output></span>
          {row.badge && <span className="sla-badge overdue">{row.badge}</span>}
        </button></li>)}
      </ol>
      {dash.state === "denied" && <p role="alert" className="surface-denied">
        {t("ops.deniedDashboard")} · {errorText(dash.error)}</p>}
      {ws.view === "gaps" && <fieldset className="gap-filters">
        <legend>{t("ops.filter.legend")}</legend>
        <label>{t("ops.filter.state")}
          <select value={ws.gapState ?? ""} onChange={event => apply({
            ...ws, gapId: undefined,
            gapState: (event.target.value || undefined) as GapState | undefined,
          }, false)}>
            <option value="">{t("ops.filter.all")}</option>
            {GAP_STATES.map(item => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label>{t("ops.filter.priority")}
          <select value={ws.gapPriority ?? ""} onChange={event => apply({
            ...ws, gapId: undefined,
            gapPriority: (event.target.value || undefined) as GapPriority | undefined,
          }, false)}>
            <option value="">{t("ops.filter.all")}</option>
            {GAP_PRIORITIES.map(item => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
      </fieldset>}
    </nav>

    {/* tabIndex: the work surface is a scrollable region and must be
        keyboard-focusable (axe scrollable-region-focusable, AC-10). */}
    <section className="ops-surface" aria-label={t("ops.surfaceAria")} tabIndex={0}>
      {notice && <p role="status" className="ops-notice">{t(notice)}</p>}
      {actionError && <p role="alert" className="surface-error">
        {t("ops.actionBlocked")} · {errorText(actionError)}</p>}

      {ws.view === "dashboard" && <div className="ops-dashboard">
        <h2>{t("ops.dashboardTitle")}</h2>
        <Surface load={dash} retry={loadLedger}>{data => <div className="tile-grid">
          <article className="tile"><header><ZoneChip zone={data.coverage.zone_label}/>
            <h3>{t("ops.tile.coverage")}</h3></header>
            <p className="tile-figure">{data.coverage.total_records}</p>
            <dl>{Object.entries(data.coverage.by_classification).map(([key, value]) =>
              <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>
          </article>
          <article className="tile"><header><ZoneChip zone={data.freshness.zone_label}/>
            <h3>{t("ops.tile.freshness")}</h3></header>
            <p className="tile-figure">{data.freshness.total}</p>
            <dl>
              <div><dt>{t("ops.status.expiring")}</dt><dd>{data.freshness.expiring}</dd></div>
              <div><dt>{t("ops.status.expired")}</dt><dd>{data.freshness.expired}</dd></div>
              <div><dt>{t("ops.fact.assigned")}</dt><dd>{data.freshness.assigned}</dd></div>
              <div><dt>{t("ops.fact.unassigned")}</dt><dd>{data.freshness.unassigned}</dd></div>
            </dl>
          </article>
          <article className="tile"><header><ZoneChip zone={data.conflict.zone_label}/>
            <h3>{t("ops.tile.conflict")}</h3></header>
            <p className="tile-figure">{data.conflict.total}</p>
            <dl>
              <div><dt>{t("ops.status.disputed")}</dt><dd>{data.conflict.disputed}</dd></div>
              <div><dt>{t("ops.status.supersededAmbiguous")}</dt>
                <dd>{data.conflict.superseded_ambiguous}</dd></div>
              <div><dt>{t("ops.fact.assigned")}</dt><dd>{data.conflict.assigned}</dd></div>
              <div><dt>{t("ops.fact.unassigned")}</dt><dd>{data.conflict.unassigned}</dd></div>
            </dl>
          </article>
          <article className="tile"><header><ZoneChip zone={data.owner_review.zone_label}/>
            <h3>{t("ops.tile.ownerReview")}</h3></header>
            <p className="tile-figure">{data.owner_review.total}</p>
            <dl>
              <div><dt>{t("ops.fact.due")}</dt><dd>{data.owner_review.due}</dd></div>
              <div><dt>{t("ops.fact.overdue")}</dt><dd>{data.owner_review.overdue}</dd></div>
              <div><dt>{t("ops.fact.assigned")}</dt><dd>{data.owner_review.assigned}</dd></div>
              <div><dt>{t("ops.fact.unassigned")}</dt>
                <dd>{data.owner_review.unassigned}</dd></div>
            </dl>
          </article>
          <article className="tile"><header><ZoneChip zone={data.gap_flow.zone_label}/>
            <h3>{t("ops.tile.gapFlow")}</h3></header>
            <p className="tile-figure">{data.gap_flow.open_total}</p>
            <dl>
              <div><dt>{t("ops.fact.closed")}</dt><dd>{data.gap_flow.closed_total}</dd></div>
              <div><dt>{t("ops.sla.overdue")}</dt><dd>{data.gap_flow.overdue}</dd></div>
              {Object.entries(data.gap_flow.aging).map(([key, value]) =>
                <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}
            </dl>
          </article>
          <article className="tile research"><header>
            <ZoneChip zone={data.research_intake.zone_label}/>
            <h3>{t("ops.tile.researchIntake")}</h3></header>
            <p className="tile-figure">{data.research_intake.sources_active}
              <small>/{data.research_intake.sources_total}
                {" "}{t("ops.fact.sourcesActive")}</small></p>
            <dl>
              {Object.entries(data.research_intake.packages_by_state).map(([key, value]) =>
                <div key={key}><dt>{t("ops.fact.package")} {key}</dt><dd>{value}</dd></div>)}
              {Object.entries(data.research_intake.records_by_tier).map(([key, value]) =>
                <div key={`tier-${key}`}><dt>Tier {key}</dt><dd>{value}</dd></div>)}
            </dl>
          </article>
          <article className="tile research"><header>
            <ZoneChip zone={data.graduation.zone_label}/>
            <h3>{t("ops.tile.graduationFunnel")}</h3></header>
            <p className="tile-figure">{data.graduation.proposed}</p>
            <dl>
              <div><dt>{t("ops.fact.approved")}</dt><dd>{data.graduation.approved}</dd></div>
              <div><dt>{t("ops.fact.rejected")}</dt><dd>{data.graduation.rejected}</dd></div>
              <div><dt>{t("ops.fact.atPublishGate")}</dt>
                <dd>{data.graduation.submitted}</dd></div>
            </dl>
          </article>
        </div>}</Surface>
      </div>}

      {ws.view === "gaps" && <div className="ops-split">
        <div className="ops-list" aria-label={t("ops.gaps.listAria")}>
          <h2>{t("ops.gaps.title")}</h2>
          <Surface load={gaps} retry={loadGaps}>{page => page.items.length === 0
            ? <p className="surface-empty">{t("ops.gaps.empty")}</p>
            : <ol>{page.items.map(gap => <li key={gap.gap_id}><button type="button"
                aria-current={ws.gapId === gap.gap_id ? "true" : undefined}
                onClick={() => apply({...ws, gapId: gap.gap_id})}>
                <span className="row-head"><ZoneChip zone={gap.zone_label}/>
                  <code>{gap.lifecycle}</code><code>{gap.priority}</code></span>
                <strong>{gap.sanitized_summary || gap.sanitized_question}</strong>
                <small>{gap.occurrence_count} {t("ops.gaps.asked")} ·
                  {" "}{when(gap.last_seen_at, locale)}</small>
                {slaBadge(gap, t, locale)}
              </button></li>)}</ol>}
          </Surface>
        </div>
        <div className="ops-detail">
          {!ws.gapId && <p className="surface-empty">{t("ops.gaps.pick")}</p>}
          {ws.gapId && <Surface load={gapDetail} retry={loadGapDetail}>{detail => <>
            <header className="detail-head"><ZoneChip zone={detail.gap.zone_label}/>
              <h3>{detail.gap.sanitized_question}</h3></header>
            <p className="detail-sub">{detail.gap.sanitized_summary}</p>
            <dl className="detail-facts">
              <div><dt>{t("ops.detail.state")}</dt>
                <dd><code>{detail.gap.lifecycle}</code></dd></div>
              <div><dt>{t("ops.detail.priority")}</dt><dd>{detail.gap.priority}</dd></div>
              <div><dt>{t("ops.detail.occurrences")}</dt>
                <dd>{detail.gap.occurrence_count}</dd></div>
              <div><dt>{t("ops.detail.firstSeen")}</dt>
                <dd>{when(detail.gap.first_seen_at, locale)}</dd></div>
              <div><dt>{t("ops.detail.lastSeen")}</dt>
                <dd>{when(detail.gap.last_seen_at, locale)}</dd></div>
              <div><dt>{t("ops.detail.sla")}</dt>
                <dd>{when(detail.gap.due_at, locale)} {slaBadge(detail.gap, t, locale)}</dd></div>
              <div><dt>{t("ops.detail.owner")}</dt>
                <dd><code>{detail.gap.owner_subject_id ?? t("ops.detail.unassigned")}</code></dd></div>
            </dl>
            <form className="action-form" onSubmit={event => event.preventDefault()}>
              <label>{t("ops.form.reason")}
                <input value={reason} onChange={event => setReason(event.target.value)}
                  placeholder={t("ops.form.reasonPlaceholder")}/></label>
              <PickerCombobox kind="subjects" value={assigneePick}
                onSelect={setAssigneePick} onSessionLost={loseAccess}/>
              <PickerCombobox kind="records" value={resolvingPick}
                onSelect={setResolvingPick} onSessionLost={loseAccess}/>
              <div className="action-row">
                <button type="button" onClick={() => gapAction("triage", {})}>
                  {t("ops.action.triage")}</button>
                <button type="button" disabled={!assigneePick}
                  onClick={() => assigneePick && gapAction("assign", {
                    owner_subject_id: assigneePick.id,
                  })}>
                  {t("ops.action.assign")}</button>
                <button type="button" disabled={!resolvingPick}
                  onClick={() => resolvingPick && gapAction("answer", {
                    resolving_version_id: resolvingPick.id,
                  })}>{t("ops.action.answer")}</button>
                <button type="button" className="danger"
                  onClick={() => gapAction("decline", {
                    decline_reason: reason.trim() || t("ops.reason.decline"),
                  })}>{t("ops.action.decline")}</button>
              </div>
              <p className="form-note">{t("ops.form.gapNote")}</p>
            </form>
            <h4>{t("ops.transitions.title")}</h4>
            <ol className="transition-history">{detail.transitions.map(item =>
              <li key={item.transition_id}>
                <code>{item.from_state} → {item.to_state}</code>
                <span>{item.reason}</span>
                <small>{when(item.occurred_at, locale)}</small>
              </li>)}
              {detail.transitions.length === 0
                && <li><span>{t("ops.transitions.empty")}</span></li>}
            </ol>
          </>}</Surface>}
        </div>
      </div>}

      {queueView && <div className="ops-queue">
        <h2>{queueView === "freshness" ? t("ops.queue.freshnessTitle")
          : queueView === "conflict" ? t("ops.queue.conflictTitle")
            : t("ops.queue.ownerReviewTitle")}</h2>
        <Surface load={queue} retry={loadQueue}>{page => <>
          <p className="queue-meta">
            {t("ops.queue.computedAt")} {when(page.computed_at, locale)} ·
            {" "}{page.aggregates.total} {t("ops.queue.items")} ·
            {" "}{t("ops.queue.assigned")} {page.aggregates.assigned} ·
            {" "}{t("ops.queue.unassigned")} {page.aggregates.unassigned}
          </p>
          <form className="action-form inline" onSubmit={event => event.preventDefault()}>
            <PickerCombobox kind="subjects" value={assigneePick}
              onSelect={setAssigneePick} onSessionLost={loseAccess}/>
            <label>{t("ops.form.note")}
              <input value={reason} onChange={event => setReason(event.target.value)}/></label>
          </form>
          {page.entries.length === 0
            && <p className="surface-empty">{t("ops.queue.empty")}</p>}
          <ol className="queue-entries">{page.entries.map(entry => {
            const task = entry.task;
            return <li key={entry.record_version_id}>
              <article>
                <header className="row-head"><ZoneChip zone={entry.zone_label}/>
                  <strong>{entry.record_key}</strong>
                  <span className={`sla-badge ${
                    ["expired", "overdue", "disputed"].includes(entry.status)
                      ? "overdue" : ""}`}>
                    {statusText(entry.status, t)}</span>
                </header>
                <small>
                  {entry.classification} · {t("ops.queue.owner")}
                  {" "}<code>{entry.owner_subject_id}</code>
                  {entry.effective_to && <> · {t("ops.queue.expires")}
                    {" "}{when(entry.effective_to, locale)}</>}
                  {entry.review_due_at && <> · {t("ops.queue.reviewDue")}
                    {" "}{when(entry.review_due_at, locale)}</>}
                </small>
                {entry.sides.length > 0 && <div className="conflict-sides">
                  {entry.sides.map(side => <article key={side.version_id}>
                    <strong>{side.external
                      ? t("ops.queue.sideReplacement") : t("ops.queue.sideActive")}
                      · rev {side.package_revision}</strong>
                    <small>{side.provenance_level} · {side.verification_state}</small>
                    <code title={side.content_sha256}>{side.content_sha256.slice(0, 16)}…</code>
                    <small>{t("ops.queue.evidence")} {side.evidence_refs.join(", ") || "—"}</small>
                  </article>)}
                </div>}
                {task && <small className="task-state">
                  {t("ops.queue.task")} {task.state} · {t("ops.queue.taskAssignee")}
                  {" "}<code>{task.assignee_subject_id}</code>
                  {task.due_at && <> · {t("ops.queue.taskDue")} {when(task.due_at, locale)}</>}
                </small>}
                <div className="action-row">
                  <button type="button" disabled={!assigneePick}
                    onClick={() => assignQueueEntry(entry)}>{t("ops.action.assign")}</button>
                  {task && task.state !== "completed"
                    && <button type="button"
                      onClick={() => completeTask(task.task_id)}>{t("ops.action.complete")}</button>}
                </div>
              </article>
            </li>;
          })}</ol>
          <p className="form-note">{t("ops.queue.resolveNote")}</p>
        </>}</Surface>
      </div>}

      {ws.view === "research" && <div className="ops-split">
        <div className="ops-list" aria-label={t("ops.row.research")}>
          <h2>{t("ops.row.research")}</h2>
          <Surface load={packages} retry={loadPackages}>{page => page.items.length === 0
            ? <p className="surface-empty">{t("ops.research.empty")}</p>
            : <ol>{page.items.map(item => <li key={item.package_id}><button type="button"
                aria-current={ws.packageId === item.package_id ? "true" : undefined}
                onClick={() => apply({...ws, packageId: item.package_id, recordId: undefined})}>
                <span className="row-head"><ZoneChip zone={item.zone_label}/>
                  <code>{item.import_state}</code></span>
                <strong>{item.source_key} · {item.snapshot_scope}</strong>
                <small>{item.record_count} {t("ops.research.records")} ·
                  {" "}{when(item.received_at, locale)}</small>
                {item.rejection_code && <span className="sla-badge overdue">
                  {item.rejection_code}</span>}
              </button></li>)}</ol>}
          </Surface>
        </div>
        <div className="ops-detail">
          {!ws.packageId && <p className="surface-empty">{t("ops.research.pickPackage")}</p>}
          {ws.packageId && !ws.recordId && <Surface load={records}
            retry={() => ws.packageId && void fetchInto(
              `research/packages/${ws.packageId}/records?limit=50`,
              parseResearchRecordPage, setRecords,
            )}>{page => page.items.length === 0
              ? <p className="surface-empty">{t("ops.research.noRecords")}</p>
              : <ol className="record-list">{page.items.map(item =>
                <li key={item.research_record_id}><button type="button"
                  onClick={() => apply({...ws, recordId: item.research_record_id})}>
                  <span className="row-head"><ZoneChip zone={item.zone_label}/>
                    <code>Tier {item.tier}</code><code>{item.corroboration_state}</code></span>
                  <strong>{item.record_key}</strong>
                  <small>{item.evidence.length} {t("ops.research.evidenceCount")}</small>
                </button></li>)}</ol>}
            </Surface>}
          {ws.recordId && <Surface load={researchRecord}>{item => <>
            <header className="detail-head"><ZoneChip zone={item.zone_label}/>
              <h3>{item.record_key}</h3>
              <code>Tier {item.tier}</code>
            </header>
            <p className="detail-sub">
              {t("ops.research.source")} {item.source_key} ·
              {" "}{t("ops.research.version")} {item.version_ordinal} ·
              {" "}{item.corroboration_state}
            </p>
            <pre className="record-content">{
              JSON.stringify(item.content, null, 2).slice(0, 2000)
            }</pre>
            <h4>{t("ops.research.quotesTitle")}</h4>
            <ol className="evidence-spans">{item.evidence.map(span =>
              <li key={span.checksum}>
                <blockquote>{span.quoted_text.slice(0, 500)}</blockquote>
                <small>{span.source_url}</small>
                <code title={span.checksum}>{span.checksum.slice(0, 16)}…</code>
              </li>)}</ol>
            {!composerOpen && <button type="button" className="primary"
              onClick={() => {setComposerOpen(true); setTargetKey(item.record_key);}}>
              {t("ops.action.propose")}</button>}
            {composerOpen && <form className="action-form"
              onSubmit={event => {event.preventDefault(); propose(item);}}>
              <h4>{t("ops.research.composerTitle")}</h4>
              <label>{t("ops.form.claim")}
                <input value={claimText} required
                  onChange={event => setClaimText(event.target.value)}/></label>
              <label>{t("ops.form.targetKey")}
                <input value={targetKey}
                  onChange={event => setTargetKey(event.target.value)}/></label>
              <label>{t("ops.form.classification")}
                <select value={claimClassification}
                  onChange={event => setClaimClassification(event.target.value)}>
                  {["public_internal", "internal", "restricted", "highly_restricted"]
                    .map(item2 => <option key={item2} value={item2}>{item2}</option>)}
                </select></label>
              <label>{t("ops.form.rationale")}
                <input value={rationale}
                  onChange={event => setRationale(event.target.value)}/></label>
              <div className="action-row">
                <button type="submit" className="primary" disabled={!claimText.trim()}>
                  {t("ops.action.propose")}</button>
                <button type="button" onClick={() => setComposerOpen(false)}>
                  {t("ops.cancel")}</button>
              </div>
              <p className="form-note">{t("ops.proposeNote")}</p>
            </form>}
          </>}</Surface>}
        </div>
      </div>}

      {ws.view === "graduation" && <div className="ops-split">
        <div className="ops-list" aria-label={t("ops.grad.listAria")}>
          <h2>{t("ops.grad.title")}</h2>
          <Surface load={proposals} retry={loadProposals}>{page => page.items.length === 0
            ? <p className="surface-empty">{t("ops.grad.empty")}</p>
            : <ol>{page.items.map(item => <li key={item.proposal_id}><button type="button"
                aria-current={ws.proposalId === item.proposal_id ? "true" : undefined}
                onClick={() => apply({...ws, proposalId: item.proposal_id})}>
                <span className="row-head"><ZoneChip zone={researchZone}/>
                  <code>{item.state}</code></span>
                <strong>{item.target_record_key}</strong>
                <small>{item.research_record_ids.length} {t("ops.grad.records")} ·
                  {" "}{when(item.proposed_at, locale)}</small>
              </button></li>)}</ol>}
          </Surface>
        </div>
        <div className="ops-detail">
          {!ws.proposalId && <p className="surface-empty">{t("ops.grad.pick")}</p>}
          {ws.proposalId && <Surface load={proposal} retry={loadProposal}>{item => <>
            <header className="detail-head"><ZoneChip zone={researchZone}/>
              <h3>{item.target_record_key}</h3><code>{item.state}</code>
            </header>
            <GatedCrossing proposal={item}/>
            <div className="grad-compare">
              <section aria-label={t("ops.grad.evidenceTitle")}>
                <h4>{t("ops.grad.evidenceTitle")}</h4>
                {evidence.state === "loading"
                  && <p role="status">{t("ops.grad.evidenceLoading")}</p>}
                {evidence.state === "error" && <p role="alert" className="surface-error">
                  {t("ops.grad.evidenceError")}</p>}
                {evidence.state === "ready" && <>
                  {evidence.data.missing > 0 && <p className="surface-denied" role="note">
                    {evidence.data.missing} {t("ops.grad.hidden")}</p>}
                  {evidence.data.records.map(item2 => <article key={item2.research_record_id}
                    className="evidence-card">
                    <header className="row-head"><ZoneChip zone={item2.zone_label}/>
                      <strong>{item2.record_key}</strong><code>Tier {item2.tier}</code>
                    </header>
                    {item2.evidence.slice(0, 3).map(span => <blockquote key={span.checksum}>
                      {span.quoted_text.slice(0, 300)}
                      <footer><small>{span.source_url}</small></footer>
                    </blockquote>)}
                  </article>)}
                </>}
              </section>
              <section aria-label={t("ops.grad.claimTitle")}>
                <h4>{t("ops.grad.claimTitle")}</h4>
                <p className="claim-text">{String(item.claim_draft.claim_text ?? "")}</p>
                <dl className="detail-facts">
                  <div><dt>{t("ops.grad.targetKey")}</dt>
                    <dd><code>{item.target_record_key}</code></dd></div>
                  <div><dt>{t("ops.form.classification")}</dt>
                    <dd>{String(item.claim_draft.classification ?? "—")}</dd></div>
                  <div><dt>{t("ops.grad.proposer")}</dt>
                    <dd><code>{item.proposer_subject_id}</code></dd></div>
                  <div><dt>{t("ops.grad.rationale")}</dt><dd>{item.rationale}</dd></div>
                  {item.decision_reason && <div><dt>{t("ops.grad.decisionReason")}</dt>
                    <dd>{item.decision_reason}</dd></div>}
                </dl>
              </section>
            </div>
            {item.state === "proposed" && <form className="action-form"
              onSubmit={event => event.preventDefault()}>
              <label>{t("ops.form.decisionReason")}
                <input value={reason} onChange={event => setReason(event.target.value)}/></label>
              <div className="action-row">
                <button type="button" className="primary" onClick={() => decide("approved")}>
                  {t("ops.action.approve")}</button>
                <button type="button" className="danger" onClick={() => decide("rejected")}>
                  {t("ops.action.reject")}</button>
              </div>
              <p className="form-note">{t("ops.grad.decideNote")}</p>
            </form>}
          </>}</Surface>}
        </div>
      </div>}
    </section>

    <EvidenceRail entries={railEntries} open={railOpen}
      onClose={() => setRailOpen(false)} note={railNote}/>
    </div>
    {(ledgerOpen || railOpen) && <button className="scrim" type="button"
      aria-label={t("shell.closePanels")}
      onClick={() => {setLedgerOpen(false); setRailOpen(false);}}/>}
  </div>;
}
