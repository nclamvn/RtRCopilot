"use client";

import React, {useCallback, useEffect, useMemo, useState} from "react";
import Link from "next/link";
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
} from "../../governance/contracts";
import {GatedCrossing, ZoneChip} from "./zone";

type Identity = {user_id: string; email: string; display_name: string; roles: string[]};
type Load<T> =
  | {state: "idle"}
  | {state: "loading"}
  | {state: "ready"; data: T}
  | {state: "denied"; error: TypedError}
  | {state: "error"; error: TypedError};
type Evidence = {records: ResearchRecord[]; missing: number};

const IDLE = {state: "idle"} as const;
const QUEUE_VIEWS: Record<string, "freshness" | "conflict" | "owner-review"> = {
  freshness: "freshness", conflict: "conflict", "owner-review": "owner-review",
};
const GAP_STATES: GapState[] = [
  "open", "triaged", "assigned", "answered", "published", "declined",
];
const GAP_PRIORITIES: GapPriority[] = ["low", "normal", "high", "urgent"];
const STATUS_TEXT: Record<string, string> = {
  expiring: "Sắp hết hạn", expired: "Đã hết hạn", due: "Đến hạn rà soát",
  overdue: "Quá hạn rà soát", disputed: "Đang tranh chấp",
  superseded_ambiguous: "Thay thế chưa rõ",
};

const api = (path: string, init?: RequestInit) => fetch(`/api/governance/${path}`, {
  cache: "no-store", ...init,
  headers: {"content-type": "application/json", ...(init?.headers ?? {})},
});

function errorText(error: TypedError) {
  return error.requestId ? `${error.code} · ${error.requestId}` : error.code;
}

function when(value: string | null) {
  return value ? new Date(value).toLocaleString("vi-VN") : "—";
}

function slaBadge(gap: Gap) {
  if (!gap.due_at || gap.closed_at) return null;
  const overdue = Date.parse(gap.due_at) <= Date.now();
  return <span className={`sla-badge ${overdue ? "overdue" : ""}`}>
    {overdue ? "Quá hạn SLA" : `Hạn ${when(gap.due_at)}`}
  </span>;
}

function Surface<T>({load, children, empty, retry}: {
  load: Load<T>; empty?: string; retry?: () => void;
  children: (data: T) => React.ReactNode;
}) {
  if (load.state === "idle" || load.state === "loading") {
    return <p role="status" className="surface-loading">Đang tải…</p>;
  }
  if (load.state === "denied") {
    return <div role="alert" className="surface-denied">
      Bị từ chối theo chính sách · {errorText(load.error)}
    </div>;
  }
  if (load.state === "error") {
    return <div role="alert" className="surface-error">
      Không tải được dữ liệu · {errorText(load.error)}
      {retry && <button type="button" onClick={retry}>Thử lại</button>}
    </div>;
  }
  const isEmpty = Array.isArray(load.data) && load.data.length === 0;
  if (isEmpty && empty) return <p className="surface-empty">{empty}</p>;
  return <>{children(load.data)}</>;
}

export default function KnowledgeOpsPage() {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [ws, setWs] = useState<WorkspaceState>({view: "dashboard"});
  const [dash, setDash] = useState<Load<Dashboard>>(IDLE);
  const [conflictAgg, setConflictAgg] = useState<Load<QueuePage>>(IDLE);
  const [reviewAgg, setReviewAgg] = useState<Load<QueuePage>>(IDLE);
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
  const [notice, setNotice] = useState("");
  const [reason, setReason] = useState("");
  const [assignee, setAssignee] = useState("");
  const [resolvingVersion, setResolvingVersion] = useState("");
  const [claimText, setClaimText] = useState("");
  const [claimClassification, setClaimClassification] = useState("internal");
  const [targetKey, setTargetKey] = useState("");
  const [rationale, setRationale] = useState("");
  const [composerOpen, setComposerOpen] = useState(false);
  const [ledgerOpen, setLedgerOpen] = useState(false);
  const [railOpen, setRailOpen] = useState(false);

  const loseAccess = useCallback(() => {
    setIdentity(null);
    setDash(IDLE); setConflictAgg(IDLE); setReviewAgg(IDLE);
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

  const loadLedger = useCallback(() => {
    void fetchInto("governance/dashboard", parseDashboard, setDash);
    void fetchInto("governance/queues/conflict?limit=1", parseQueuePage, setConflictAgg);
    void fetchInto("governance/queues/owner-review?limit=1", parseQueuePage, setReviewAgg);
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
    done: string,
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
      {reason: reason.trim() || "Xử lý qua Knowledge Ops", ...extra},
      () => { loadGapDetail(); loadGaps(); loadLedger(); },
      "Đã ghi nhận chuyển trạng thái.",
    );
  }, [act, ws.gapId, reason, loadGapDetail, loadGaps, loadLedger]);

  const assignQueueEntry = useCallback((entry: QueueEntry) => {
    if (!queueView) return;
    void act(
      `governance/queues/${queueView}/assign`,
      {
        record_version_id: entry.record_version_id,
        assignee_subject_id: assignee.trim(),
        note: reason.trim(),
      },
      () => { loadQueue(); loadLedger(); },
      "Đã giao nhiệm vụ rà soát.",
    );
  }, [act, queueView, assignee, reason, loadQueue, loadLedger]);

  const completeTask = useCallback((taskId: string) => {
    void act(
      `governance/review-tasks/${taskId}/complete`,
      {},
      () => { loadQueue(); loadLedger(); },
      "Đã hoàn tất nhiệm vụ; hàng đợi sẽ tự mở lại nếu metadata chưa đổi.",
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
        rationale: rationale.trim() || "Đề xuất từ Knowledge Ops",
      },
      () => { setComposerOpen(false); loadLedger(); },
      "Đã tạo đề xuất nâng cấp — theo dõi trong hàng đợi Nâng cấp.",
    );
  }, [act, claimText, claimClassification, targetKey, rationale, loadLedger]);

  const decide = useCallback((decision: "approved" | "rejected") => {
    if (!ws.proposalId) return;
    void act(
      `graduation/proposals/${ws.proposalId}/decide`,
      {decision, reason: reason.trim() || "Quyết định qua Knowledge Ops"},
      () => { loadProposal(); loadProposals(); loadLedger(); },
      decision === "approved"
        ? "Đã đưa bản nháp claim vào cổng phát hành SOT."
        : "Đã từ chối đề xuất (bất biến).",
    );
  }, [act, ws.proposalId, reason, loadProposal, loadProposals, loadLedger]);

  async function logout() {
    await fetch("/api/auth/logout", {method: "POST"});
    loseAccess();
  }

  /** SOT chips render only the zone label the dashboard API returned. */
  const sotZone = dash.state === "ready" ? dash.data.gap_flow.zone_label : null;
  const researchZone = dash.state === "ready"
    ? dash.data.research_intake.zone_label : null;

  const ledgerRows = useMemo(() => {
    const d = dash.state === "ready" ? dash.data : null;
    const conflictTotal = conflictAgg.state === "ready"
      ? String(conflictAgg.data.aggregates.total) : "…";
    const reviewOverdue = reviewAgg.state === "ready"
      ? reviewAgg.data.aggregates.by_status.overdue ?? 0 : 0;
    const rows: Array<{
      view: WorkspaceView; label: string; zone: "sot" | "research" | null;
      count: string; badge: string;
    }> = [
      {view: "gaps", label: "Khoảng trống", zone: sotZone,
        count: d ? String(d.gap_flow.open_total) : "…",
        badge: d && d.gap_flow.overdue > 0 ? `${d.gap_flow.overdue} quá hạn SLA` : ""},
      {view: "freshness", label: "Độ tươi", zone: sotZone,
        count: d ? String(d.freshness.total) : "…",
        badge: d && d.freshness.expired > 0 ? `${d.freshness.expired} đã hết hạn` : ""},
      {view: "conflict", label: "Xung đột", zone: sotZone,
        count: conflictTotal, badge: ""},
      {view: "owner-review", label: "Rà soát định kỳ", zone: sotZone,
        count: reviewAgg.state === "ready"
          ? String(reviewAgg.data.aggregates.total) : "…",
        badge: reviewOverdue > 0 ? `${reviewOverdue} quá hạn` : ""},
      {view: "research", label: "Gói nghiên cứu", zone: researchZone,
        count: d ? String(Object.values(d.research_intake.packages_by_state)
          .reduce((sum, item) => sum + item, 0)) : "…",
        badge: d && (d.research_intake.packages_by_state.rejected ?? 0) > 0
          ? `${d.research_intake.packages_by_state.rejected} bị từ chối` : ""},
      {view: "graduation", label: "Nâng cấp", zone: researchZone,
        count: d ? String(d.graduation.proposed) : "…",
        badge: d && d.graduation.submitted > 0
          ? `${d.graduation.submitted} tại cổng` : ""},
    ];
    return rows;
  }, [dash, conflictAgg, reviewAgg, sotZone, researchZone]);

  if (!authReady || !identity) {
    return <main className="gate">
      <header><span className="mark">RT</span><span>RT ROBOTICS / KNOWLEDGE OPS</span></header>
      <section className="gate-content">
        <p className="eyebrow">Bàn điều hành tri thức có kiểm quyền</p>
        <h1>Vận hành tri thức</h1>
        <p className="lede">
          Đăng nhập email công ty để xử lý khoảng trống, độ tươi, xung đột,
          gói nghiên cứu và cổng nâng cấp theo đúng phân quyền.
        </p>
        {authReady
          ? <>
              {/* OIDC must navigate through the same-origin callback. */}
              {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
              <a className="primary" href="/api/auth/login">Đăng nhập công ty</a>
            </>
          : <span role="status">Đang kiểm tra phiên…</span>}
      </section>
    </main>;
  }

  const selectedGap = gapDetail.state === "ready" ? gapDetail.data : null;
  const selectedRecord = researchRecord.state === "ready" ? researchRecord.data : null;
  const selectedProposal = proposal.state === "ready" ? proposal.data : null;
  const selectedPackage = packages.state === "ready"
    ? packages.data.items.find(item => item.package_id === ws.packageId) ?? null
    : null;

  return <main className="ops-workspace">
    <header className="ops-topbar">
      <Link className="brand nav-brand" href="/">
        <span className="mark">RT</span><span>RT / KNOWLEDGE OPS</span>
      </Link>
      <nav aria-label="Không gian làm việc khác" className="ops-nav">
        <Link href="/">Files</Link>
        <Link href="/documents">Documents</Link>
      </nav>
      <div className="identity"><strong>{identity.display_name || identity.email}</strong>
        <button type="button" onClick={() => void logout()}>Đăng xuất</button></div>
      <button className="mobile-control" type="button"
        onClick={() => {setRailOpen(false); setLedgerOpen(true);}}>Hàng đợi</button>
      <button className="mobile-control" type="button"
        onClick={() => {setLedgerOpen(false); setRailOpen(true);}}>Bằng chứng</button>
    </header>

    <nav className={`ops-ledger ${ledgerOpen ? "open" : ""}`} aria-label="Sổ hàng đợi">
      <div className="panel-heading">
        <div><p className="eyebrow">Queue ledger</p><h1>Vận hành tri thức</h1></div>
        <button className="close-mobile" type="button" aria-label="Đóng sổ hàng đợi"
          onClick={() => setLedgerOpen(false)}>×</button>
      </div>
      <ol className="queue-list">
        <li><button type="button"
          aria-current={ws.view === "dashboard" ? "true" : undefined}
          onClick={() => apply({view: "dashboard"})}>
          <strong>Bảng điều hành</strong>
          <small>Số liệu sống, theo phạm vi chính sách</small>
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
        Bảng số liệu bị từ chối · {errorText(dash.error)}</p>}
      {ws.view === "gaps" && <fieldset className="gap-filters">
        <legend>Lọc khoảng trống</legend>
        <label>Trạng thái
          <select value={ws.gapState ?? ""} onChange={event => apply({
            ...ws, gapId: undefined,
            gapState: (event.target.value || undefined) as GapState | undefined,
          }, false)}>
            <option value="">Tất cả</option>
            {GAP_STATES.map(item => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
        <label>Ưu tiên
          <select value={ws.gapPriority ?? ""} onChange={event => apply({
            ...ws, gapId: undefined,
            gapPriority: (event.target.value || undefined) as GapPriority | undefined,
          }, false)}>
            <option value="">Tất cả</option>
            {GAP_PRIORITIES.map(item => <option key={item} value={item}>{item}</option>)}
          </select>
        </label>
      </fieldset>}
    </nav>

    <section className="ops-surface" aria-label="Bàn xử lý">
      {notice && <p role="status" className="ops-notice">{notice}</p>}
      {actionError && <p role="alert" className="surface-error">
        Thao tác bị chặn · {errorText(actionError)}</p>}

      {ws.view === "dashboard" && <div className="ops-dashboard">
        <h2>Bảng điều hành tri thức</h2>
        <Surface load={dash} retry={loadLedger}>{data => <div className="tile-grid">
          <article className="tile"><header><ZoneChip zone={data.coverage.zone_label}/>
            <h3>Độ phủ SOT</h3></header>
            <p className="tile-figure">{data.coverage.total_records}</p>
            <dl>{Object.entries(data.coverage.by_classification).map(([key, value]) =>
              <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}</dl>
          </article>
          <article className="tile"><header><ZoneChip zone={data.freshness.zone_label}/>
            <h3>Độ tươi</h3></header>
            <p className="tile-figure">{data.freshness.total}</p>
            <dl>
              <div><dt>Sắp hết hạn</dt><dd>{data.freshness.expiring}</dd></div>
              <div><dt>Đã hết hạn</dt><dd>{data.freshness.expired}</dd></div>
              <div><dt>Đã giao</dt><dd>{data.freshness.assigned}</dd></div>
              <div><dt>Chưa giao</dt><dd>{data.freshness.unassigned}</dd></div>
            </dl>
          </article>
          <article className="tile"><header><ZoneChip zone={data.gap_flow.zone_label}/>
            <h3>Dòng khoảng trống</h3></header>
            <p className="tile-figure">{data.gap_flow.open_total}</p>
            <dl>
              <div><dt>Đã đóng</dt><dd>{data.gap_flow.closed_total}</dd></div>
              <div><dt>Quá hạn SLA</dt><dd>{data.gap_flow.overdue}</dd></div>
              {Object.entries(data.gap_flow.aging).map(([key, value]) =>
                <div key={key}><dt>{key}</dt><dd>{value}</dd></div>)}
            </dl>
          </article>
          <article className="tile research"><header>
            <ZoneChip zone={data.research_intake.zone_label}/>
            <h3>Tiếp nhận nghiên cứu</h3></header>
            <p className="tile-figure">{data.research_intake.sources_active}
              <small>/{data.research_intake.sources_total} nguồn hoạt động</small></p>
            <dl>
              {Object.entries(data.research_intake.packages_by_state).map(([key, value]) =>
                <div key={key}><dt>Gói {key}</dt><dd>{value}</dd></div>)}
              {Object.entries(data.research_intake.records_by_tier).map(([key, value]) =>
                <div key={`tier-${key}`}><dt>Tier {key}</dt><dd>{value}</dd></div>)}
            </dl>
          </article>
          <article className="tile research"><header>
            <ZoneChip zone={data.graduation.zone_label}/>
            <h3>Phễu nâng cấp</h3></header>
            <p className="tile-figure">{data.graduation.proposed}</p>
            <dl>
              <div><dt>Đã duyệt</dt><dd>{data.graduation.approved}</dd></div>
              <div><dt>Bị từ chối</dt><dd>{data.graduation.rejected}</dd></div>
              <div><dt>Tại cổng phát hành</dt><dd>{data.graduation.submitted}</dd></div>
            </dl>
          </article>
        </div>}</Surface>
      </div>}

      {ws.view === "gaps" && <div className="ops-split">
        <div className="ops-list" aria-label="Danh sách khoảng trống">
          <h2>Khoảng trống tri thức</h2>
          <Surface load={gaps} retry={loadGaps}>{page => page.items.length === 0
            ? <p className="surface-empty">Không có khoảng trống trong phạm vi được cấp quyền.</p>
            : <ol>{page.items.map(gap => <li key={gap.gap_id}><button type="button"
                aria-current={ws.gapId === gap.gap_id ? "true" : undefined}
                onClick={() => apply({...ws, gapId: gap.gap_id})}>
                <span className="row-head"><ZoneChip zone={sotZone}/>
                  <code>{gap.lifecycle}</code><code>{gap.priority}</code></span>
                <strong>{gap.sanitized_summary || gap.sanitized_question}</strong>
                <small>{gap.occurrence_count} lần hỏi · {when(gap.last_seen_at)}</small>
                {slaBadge(gap)}
              </button></li>)}</ol>}
          </Surface>
        </div>
        <div className="ops-detail">
          {!ws.gapId && <p className="surface-empty">Chọn một khoảng trống để xử lý.</p>}
          {ws.gapId && <Surface load={gapDetail} retry={loadGapDetail}>{detail => <>
            <header className="detail-head"><ZoneChip zone={sotZone}/>
              <h3>{detail.gap.sanitized_question}</h3></header>
            <p className="detail-sub">{detail.gap.sanitized_summary}</p>
            <dl className="detail-facts">
              <div><dt>Trạng thái</dt><dd><code>{detail.gap.lifecycle}</code></dd></div>
              <div><dt>Ưu tiên</dt><dd>{detail.gap.priority}</dd></div>
              <div><dt>Số lần hỏi</dt><dd>{detail.gap.occurrence_count}</dd></div>
              <div><dt>Lần đầu</dt><dd>{when(detail.gap.first_seen_at)}</dd></div>
              <div><dt>Gần nhất</dt><dd>{when(detail.gap.last_seen_at)}</dd></div>
              <div><dt>Hạn SLA</dt><dd>{when(detail.gap.due_at)} {slaBadge(detail.gap)}</dd></div>
              <div><dt>Người phụ trách</dt>
                <dd><code>{detail.gap.owner_subject_id ?? "chưa giao"}</code></dd></div>
            </dl>
            <form className="action-form" onSubmit={event => event.preventDefault()}>
              <label>Lý do thao tác
                <input value={reason} onChange={event => setReason(event.target.value)}
                  placeholder="Bắt buộc ghi vết"/></label>
              <label>Giao cho (subject ID)
                <input value={assignee} onChange={event => setAssignee(event.target.value)}
                  placeholder="UUID người phụ trách"/></label>
              <label>Bản ghi SOT đã kích hoạt (version ID)
                <input value={resolvingVersion}
                  onChange={event => setResolvingVersion(event.target.value)}
                  placeholder="UUID phiên bản trả lời"/></label>
              <div className="action-row">
                <button type="button" onClick={() => gapAction("triage", {})}>
                  Nhận xử lý</button>
                <button type="button" disabled={!assignee.trim()}
                  onClick={() => gapAction("assign", {owner_subject_id: assignee.trim()})}>
                  Giao cho</button>
                <button type="button" disabled={!resolvingVersion.trim()}
                  onClick={() => gapAction("answer", {
                    resolving_version_id: resolvingVersion.trim(),
                  })}>Trả lời bằng bản ghi đã phát hành</button>
                <button type="button" className="danger"
                  onClick={() => gapAction("decline", {
                    decline_reason: reason.trim() || "Từ chối qua Knowledge Ops",
                  })}>Từ chối</button>
              </div>
              <p className="form-note">
                Khoảng trống chỉ đóng bằng bản ghi đã qua cổng phát hành SOT
                hoặc một lý do từ chối bất biến.
              </p>
            </form>
            <h4>Lịch sử chuyển trạng thái</h4>
            <ol className="transition-history">{detail.transitions.map(item =>
              <li key={item.transition_id}>
                <code>{item.from_state} → {item.to_state}</code>
                <span>{item.reason}</span>
                <small>{when(item.occurred_at)}</small>
              </li>)}
              {detail.transitions.length === 0
                && <li><span>Chưa có chuyển trạng thái.</span></li>}
            </ol>
          </>}</Surface>}
        </div>
      </div>}

      {queueView && <div className="ops-queue">
        <h2>{queueView === "freshness" ? "Hàng đợi độ tươi"
          : queueView === "conflict" ? "Hàng đợi xung đột" : "Hàng đợi rà soát định kỳ"}</h2>
        <Surface load={queue} retry={loadQueue}>{page => <>
          <p className="queue-meta">
            Tính trực tiếp lúc {when(page.computed_at)} · {page.aggregates.total} mục ·
            đã giao {page.aggregates.assigned} · chưa giao {page.aggregates.unassigned}
          </p>
          <form className="action-form inline" onSubmit={event => event.preventDefault()}>
            <label>Giao cho (subject ID)
              <input value={assignee} onChange={event => setAssignee(event.target.value)}
                placeholder="UUID người phụ trách"/></label>
            <label>Ghi chú
              <input value={reason} onChange={event => setReason(event.target.value)}/></label>
          </form>
          {page.entries.length === 0
            && <p className="surface-empty">Hàng đợi trống trong phạm vi được cấp quyền.</p>}
          <ol className="queue-entries">{page.entries.map(entry => {
            const task = entry.task;
            return <li key={entry.record_version_id}>
              <article>
                <header className="row-head"><ZoneChip zone={sotZone}/>
                  <strong>{entry.record_key}</strong>
                  <span className={`sla-badge ${
                    ["expired", "overdue", "disputed"].includes(entry.status)
                      ? "overdue" : ""}`}>
                    {STATUS_TEXT[entry.status] ?? entry.status}</span>
                </header>
                <small>
                  {entry.classification} · chủ sở hữu <code>{entry.owner_subject_id}</code>
                  {entry.effective_to && <> · hết hạn {when(entry.effective_to)}</>}
                  {entry.review_due_at && <> · hạn rà soát {when(entry.review_due_at)}</>}
                </small>
                {entry.sides.length > 0 && <div className="conflict-sides">
                  {entry.sides.map(side => <article key={side.version_id}>
                    <strong>{side.external ? "Bản thay thế" : "Bản đang hoạt động"}
                      · rev {side.package_revision}</strong>
                    <small>{side.provenance_level} · {side.verification_state}</small>
                    <code title={side.content_sha256}>{side.content_sha256.slice(0, 16)}…</code>
                    <small>Bằng chứng: {side.evidence_refs.join(", ") || "—"}</small>
                  </article>)}
                </div>}
                {task && <small className="task-state">
                  Nhiệm vụ: {task.state} · giao cho <code>{task.assignee_subject_id}</code>
                  {task.due_at && <> · hạn {when(task.due_at)}</>}
                </small>}
                <div className="action-row">
                  <button type="button" disabled={!assignee.trim()}
                    onClick={() => assignQueueEntry(entry)}>Giao cho</button>
                  {task && task.state !== "completed"
                    && <button type="button"
                      onClick={() => completeTask(task.task_id)}>Hoàn tất</button>}
                </div>
              </article>
            </li>;
          })}</ol>
          <p className="form-note">
            Giải quyết nội dung chỉ qua cổng phát hành SOT (thay thế, thu hồi,
            tái chứng thực) — không sửa tại chỗ.
          </p>
        </>}</Surface>
      </div>}

      {ws.view === "research" && <div className="ops-split">
        <div className="ops-list" aria-label="Gói nghiên cứu">
          <h2>Gói nghiên cứu</h2>
          <Surface load={packages} retry={loadPackages}>{page => page.items.length === 0
            ? <p className="surface-empty">Chưa có gói nghiên cứu trong phạm vi được cấp quyền.</p>
            : <ol>{page.items.map(item => <li key={item.package_id}><button type="button"
                aria-current={ws.packageId === item.package_id ? "true" : undefined}
                onClick={() => apply({...ws, packageId: item.package_id, recordId: undefined})}>
                <span className="row-head"><ZoneChip zone={item.zone_label}/>
                  <code>{item.import_state}</code></span>
                <strong>{item.source_key} · {item.snapshot_scope}</strong>
                <small>{item.record_count} bản ghi · {when(item.received_at)}</small>
                {item.rejection_code && <span className="sla-badge overdue">
                  {item.rejection_code}</span>}
              </button></li>)}</ol>}
          </Surface>
        </div>
        <div className="ops-detail">
          {!ws.packageId && <p className="surface-empty">Chọn một gói để xem bản ghi.</p>}
          {ws.packageId && !ws.recordId && <Surface load={records}
            retry={() => ws.packageId && void fetchInto(
              `research/packages/${ws.packageId}/records?limit=50`,
              parseResearchRecordPage, setRecords,
            )}>{page => page.items.length === 0
              ? <p className="surface-empty">Gói chưa có bản ghi đọc được.</p>
              : <ol className="record-list">{page.items.map(item =>
                <li key={item.research_record_id}><button type="button"
                  onClick={() => apply({...ws, recordId: item.research_record_id})}>
                  <span className="row-head"><ZoneChip zone={item.zone_label}/>
                    <code>Tier {item.tier}</code><code>{item.corroboration_state}</code></span>
                  <strong>{item.record_key}</strong>
                  <small>{item.evidence.length} trích dẫn nguyên văn</small>
                </button></li>)}</ol>}
            </Surface>}
          {ws.recordId && <Surface load={researchRecord}>{item => <>
            <header className="detail-head"><ZoneChip zone={item.zone_label}/>
              <h3>{item.record_key}</h3>
              <code>Tier {item.tier}</code>
            </header>
            <p className="detail-sub">
              Nguồn {item.source_key} · phiên bản {item.version_ordinal} ·
              {" "}{item.corroboration_state}
            </p>
            <pre className="record-content">{
              JSON.stringify(item.content, null, 2).slice(0, 2000)
            }</pre>
            <h4>Trích dẫn nguyên văn</h4>
            <ol className="evidence-spans">{item.evidence.map(span =>
              <li key={span.checksum}>
                <blockquote>{span.quoted_text.slice(0, 500)}</blockquote>
                <small>{span.source_url}</small>
                <code title={span.checksum}>{span.checksum.slice(0, 16)}…</code>
              </li>)}</ol>
            {!composerOpen && <button type="button" className="primary"
              onClick={() => {setComposerOpen(true); setTargetKey(item.record_key);}}>
              Đề xuất nâng cấp</button>}
            {composerOpen && <form className="action-form"
              onSubmit={event => {event.preventDefault(); propose(item);}}>
              <h4>Đề xuất nâng cấp thành claim công ty</h4>
              <label>Nội dung claim
                <input value={claimText} required
                  onChange={event => setClaimText(event.target.value)}/></label>
              <label>Khóa bản ghi SOT đích
                <input value={targetKey}
                  onChange={event => setTargetKey(event.target.value)}/></label>
              <label>Phân loại
                <select value={claimClassification}
                  onChange={event => setClaimClassification(event.target.value)}>
                  {["public_internal", "internal", "restricted", "highly_restricted"]
                    .map(item2 => <option key={item2} value={item2}>{item2}</option>)}
                </select></label>
              <label>Căn cứ đề xuất
                <input value={rationale}
                  onChange={event => setRationale(event.target.value)}/></label>
              <div className="action-row">
                <button type="submit" className="primary" disabled={!claimText.trim()}>
                  Đề xuất nâng cấp</button>
                <button type="button" onClick={() => setComposerOpen(false)}>Hủy</button>
              </div>
              <p className="form-note">
                Đề xuất chỉ tạo bản nháp claim; một curator khác quyết định và
                mọi kích hoạt đều qua cổng phát hành SOT.
              </p>
            </form>}
          </>}</Surface>}
        </div>
      </div>}

      {ws.view === "graduation" && <div className="ops-split">
        <div className="ops-list" aria-label="Đề xuất nâng cấp">
          <h2>Cổng nâng cấp</h2>
          <Surface load={proposals} retry={loadProposals}>{page => page.items.length === 0
            ? <p className="surface-empty">Chưa có đề xuất trong phạm vi được cấp quyền.</p>
            : <ol>{page.items.map(item => <li key={item.proposal_id}><button type="button"
                aria-current={ws.proposalId === item.proposal_id ? "true" : undefined}
                onClick={() => apply({...ws, proposalId: item.proposal_id})}>
                <span className="row-head"><ZoneChip zone={researchZone}/>
                  <code>{item.state}</code></span>
                <strong>{item.target_record_key}</strong>
                <small>{item.research_record_ids.length} bản ghi nghiên cứu ·
                  {" "}{when(item.proposed_at)}</small>
              </button></li>)}</ol>}
          </Surface>
        </div>
        <div className="ops-detail">
          {!ws.proposalId && <p className="surface-empty">Chọn một đề xuất để xem xét.</p>}
          {ws.proposalId && <Surface load={proposal} retry={loadProposal}>{item => <>
            <header className="detail-head"><ZoneChip zone={researchZone}/>
              <h3>{item.target_record_key}</h3><code>{item.state}</code>
            </header>
            <GatedCrossing proposal={item}/>
            <div className="grad-compare">
              <section aria-label="Bằng chứng nghiên cứu">
                <h4>Bằng chứng nghiên cứu</h4>
                {evidence.state === "loading" && <p role="status">Đang tải bằng chứng…</p>}
                {evidence.state === "error" && <p role="alert" className="surface-error">
                  Không tải được bằng chứng.</p>}
                {evidence.state === "ready" && <>
                  {evidence.data.missing > 0 && <p className="surface-denied" role="note">
                    {evidence.data.missing} bản ghi bị ẩn theo chính sách — bằng chứng
                    hiển thị không đầy đủ.</p>}
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
              <section aria-label="Claim đề xuất">
                <h4>Claim đề xuất</h4>
                <p className="claim-text">{String(item.claim_draft.claim_text ?? "")}</p>
                <dl className="detail-facts">
                  <div><dt>Khóa đích</dt><dd><code>{item.target_record_key}</code></dd></div>
                  <div><dt>Phân loại</dt>
                    <dd>{String(item.claim_draft.classification ?? "—")}</dd></div>
                  <div><dt>Người đề xuất</dt>
                    <dd><code>{item.proposer_subject_id}</code></dd></div>
                  <div><dt>Căn cứ</dt><dd>{item.rationale}</dd></div>
                  {item.decision_reason && <div><dt>Lý do quyết định</dt>
                    <dd>{item.decision_reason}</dd></div>}
                </dl>
              </section>
            </div>
            {item.state === "proposed" && <form className="action-form"
              onSubmit={event => event.preventDefault()}>
              <label>Lý do quyết định
                <input value={reason} onChange={event => setReason(event.target.value)}/></label>
              <div className="action-row">
                <button type="button" className="primary" onClick={() => decide("approved")}>
                  Đưa vào cổng phát hành</button>
                <button type="button" className="danger" onClick={() => decide("rejected")}>
                  Từ chối</button>
              </div>
              <p className="form-note">
                Phân tách trách nhiệm: người đề xuất không thể tự quyết định;
                phê duyệt chỉ tạo bản nháp trước cổng phát hành SOT, không kích
                hoạt tự động.
              </p>
            </form>}
          </>}</Surface>}
        </div>
      </div>}
    </section>

    <aside className={`ops-rail ${railOpen ? "open" : ""}`} aria-label="Bằng chứng và xuất xứ">
      <div className="panel-heading"><h2>Bằng chứng & xuất xứ</h2>
        <button className="close-mobile" type="button" aria-label="Đóng bằng chứng"
          onClick={() => setRailOpen(false)}>×</button></div>
      {ws.view === "dashboard" && <dl className="rail-facts">
        <div><dt>Vùng tin cậy</dt><dd>
          Mỗi số liệu và bản ghi mang nhãn vùng do máy chủ trả về —
          RESEARCH không bao giờ hiển thị như SOT.</dd></div>
        {dash.state === "ready" && <div><dt>Tính lúc</dt>
          <dd>{when(dash.data.computed_at)}</dd></div>}
      </dl>}
      {ws.view === "gaps" && selectedGap && <dl className="rail-facts">
        <div><dt>Vùng</dt><dd><ZoneChip zone={sotZone}/></dd></div>
        <div><dt>Phân loại</dt><dd>{selectedGap.gap.classification}</dd></div>
        <div><dt>Fingerprint câu hỏi</dt>
          <dd><code title={selectedGap.gap.question_fingerprint}>
            {selectedGap.gap.question_fingerprint.slice(0, 16)}…</code></dd></div>
        <div><dt>Nguồn gốc</dt><dd>{selectedGap.gap.origin}</dd></div>
        <div><dt>Routing</dt><dd><code>{selectedGap.gap.routing_key}</code></dd></div>
        {selectedGap.gap.resolving_version_id && <div><dt>Bản ghi trả lời</dt>
          <dd><code>{selectedGap.gap.resolving_version_id}</code></dd></div>}
        {selectedGap.gap.decline_reason && <div><dt>Lý do từ chối</dt>
          <dd>{selectedGap.gap.decline_reason}</dd></div>}
      </dl>}
      {queueView && queue.state === "ready" && <dl className="rail-facts">
        <div><dt>Vùng</dt><dd><ZoneChip zone={sotZone}/></dd></div>
        <div><dt>Cách tính</dt><dd>
          Thành viên hàng đợi luôn tính trực tiếp từ metadata SOT sống;
          bảng nhiệm vụ chỉ ghi việc giao và hoàn tất.</dd></div>
        <div><dt>Tính lúc</dt><dd>{when(queue.data.computed_at)}</dd></div>
        {Object.entries(queue.data.aggregates.by_status).map(([key, value]) =>
          <div key={key}><dt>{STATUS_TEXT[key] ?? key}</dt><dd>{value}</dd></div>)}
      </dl>}
      {ws.view === "research" && selectedRecord && <dl className="rail-facts">
        <div><dt>Vùng</dt><dd><ZoneChip zone={selectedRecord.zone_label}/></dd></div>
        <div><dt>Tier</dt><dd>{selectedRecord.tier}</dd></div>
        <div><dt>Đối chiếu</dt><dd>{selectedRecord.corroboration_state}</dd></div>
        <div><dt>Fingerprint gói</dt>
          <dd><code title={selectedRecord.package_fingerprint}>
            {selectedRecord.package_fingerprint.slice(0, 16)}…</code></dd></div>
        <div><dt>Checksum nội dung</dt>
          <dd><code title={selectedRecord.content_sha256}>
            {selectedRecord.content_sha256.slice(0, 16)}…</code></dd></div>
        {selectedPackage && <>
          <div><dt>Snapshot</dt><dd>{selectedPackage.snapshot_scope} ·
            {" "}{when(selectedPackage.captured_at)}</dd></div>
          <div><dt>Adapter</dt><dd><code>{selectedPackage.adapter_version}</code></dd></div>
        </>}
        <div><dt>Trích dẫn</dt><dd>{selectedRecord.evidence.length} đoạn nguyên văn
          kèm checksum</dd></div>
      </dl>}
      {ws.view === "research" && !selectedRecord && selectedPackage
        && <dl className="rail-facts">
          <div><dt>Vùng</dt><dd><ZoneChip zone={selectedPackage.zone_label}/></dd></div>
          <div><dt>Fingerprint</dt><dd><code title={selectedPackage.fingerprint}>
            {selectedPackage.fingerprint.slice(0, 16)}…</code></dd></div>
          <div><dt>Snapshot</dt><dd>{selectedPackage.snapshot_scope} ·
            {" "}{when(selectedPackage.captured_at)}</dd></div>
          <div><dt>Trạng thái nhập</dt><dd>{selectedPackage.import_state}
            {selectedPackage.rejection_code && <> · {selectedPackage.rejection_code}</>}
          </dd></div>
        </dl>}
      {ws.view === "graduation" && selectedProposal && <dl className="rail-facts">
        <div><dt>Vùng</dt><dd><ZoneChip zone={researchZone}/></dd></div>
        <div><dt>Trạng thái</dt><dd>{selectedProposal.state}</dd></div>
        {selectedProposal.attestation_hash && <div><dt>Attestation</dt>
          <dd><code title={selectedProposal.attestation_hash}>
            {selectedProposal.attestation_hash.slice(0, 16)}…</code></dd></div>}
        {selectedProposal.publish_package_id && <div><dt>Gói tại cổng phát hành</dt>
          <dd><code>{selectedProposal.publish_package_id}</code></dd></div>}
        {selectedProposal.supersedes_proposal_id && <div><dt>Thay thế đề xuất</dt>
          <dd><code>{selectedProposal.supersedes_proposal_id}</code></dd></div>}
        <div><dt>Dòng dõi</dt><dd>{selectedProposal.research_record_ids.length} bản
          ghi nghiên cứu gắn checksum bằng chứng</dd></div>
      </dl>}
      {((ws.view === "gaps" && !selectedGap)
        || (ws.view === "research" && !selectedRecord && !selectedPackage)
        || (ws.view === "graduation" && !selectedProposal)
        || (queueView && queue.state !== "ready"))
        && <p className="surface-empty">Chọn một mục để xem bằng chứng.</p>}
    </aside>
    {(ledgerOpen || railOpen) && <button className="scrim" type="button"
      aria-label="Đóng bảng điều khiển"
      onClick={() => {setLedgerOpen(false); setRailOpen(false);}}/>}
  </main>;
}
