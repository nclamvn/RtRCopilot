"use client";

import React, {useCallback, useEffect, useMemo, useRef, useState} from "react";
import Link from "next/link";
import {Locator, parseManifest, ViewerManifest} from "../../files/contracts";
import {FileViewer} from "../../files/viewers";

type Identity = {user_id: string; email: string; display_name: string; roles: string[]};
type Template = {
  template_id: string; version_id: string; display_name: string; stable_key: string;
  category: string; classification: string; document_class: string; format: string;
  version_ordinal: number; status: string; owner_display_name?: string | null;
};
type Binding = {
  field_path: string; field_type: string; source: "user" | "locked_fact" | "derived";
  required: boolean; record_key?: string | null;
};
type TemplateDetail = {template_id: string; version_id: string; status: string; schema: {bindings: Binding[]}};
type BoundField = {
  field_path: string; source: string; value: unknown; record_key?: string | null;
  record_checksum?: string | null; evidence_checksum?: string | null;
  provenance_level?: string | null; freshness_state?: string | null;
};
type BindResult = {valid: boolean; fields: BoundField[]; missing: string[]; blocked: Array<{field: string; code: string}>};
type RenderStatus = {
  render_job_id: string; state: string; progress: number; generated_file_id?: string | null;
  version_id?: string | null; checksum?: string | null; error_code?: string | null;
};
type Generated = {
  lifecycle: string; checksum: string; created_at: string; approvals: Array<{
    approval_id: string; decision: string; reviewer_display_name?: string | null;
    reason: string; decided_at: string;
  }>; issuance?: {issue_number: string; state: string; at: string} | null;
};
type HistoryItem = {
  generated_file_id: string; template_version_id: string; lifecycle: string;
  checksum: string; created_at: string; parameters: Record<string, unknown>;
  locked_snapshots: Record<string, Record<string, unknown>>;
  comparison: {
    changed_parameters: string[]; changed_locked_facts: string[];
    template_changed: boolean; checksum_changed: boolean; lifecycle_changed: boolean;
  };
};

const api = (path: string, init?: RequestInit) => fetch(`/api/document-os/${path}`, {
  cache: "no-store", ...init,
  headers: {"content-type": "application/json", ...(init?.headers ?? {})},
});

export default function DocumentsPage() {
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [selected, setSelected] = useState<Template | null>(null);
  const [detail, setDetail] = useState<TemplateDetail | null>(null);
  const [parameters, setParameters] = useState<Record<string, string>>({});
  const [binding, setBinding] = useState<BindResult | null>(null);
  const [renderJob, setRenderJob] = useState<RenderStatus | null>(null);
  const [generated, setGenerated] = useState<Generated | null>(null);
  const [historyItems, setHistoryItems] = useState<HistoryItem[]>([]);
  const [manifest, setManifest] = useState<ViewerManifest | null>(null);
  const [locator, setLocator] = useState<Locator>({});
  const [error, setError] = useState("");
  const [reason, setReason] = useState("");
  const [ledgerOpen, setLedgerOpen] = useState(false);
  const [railOpen, setRailOpen] = useState(false);
  const poll = useRef<AbortController | null>(null);

  const loseAccess = useCallback(() => {
    poll.current?.abort();
    setIdentity(null); setTemplates([]); setSelected(null); setDetail(null);
    setManifest(null); setGenerated(null); setRenderJob(null);
  }, []);

  useEffect(() => {
    fetch("/api/auth/me", {cache: "no-store"})
      .then(async response => setIdentity(response.ok ? await response.json() as Identity : null))
      .catch(() => setIdentity(null)).finally(() => setAuthReady(true));
    return () => poll.current?.abort();
  }, []);
  useEffect(() => {
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setLedgerOpen(false);
        setRailOpen(false);
      }
    };
    addEventListener("keydown", close);
    return () => removeEventListener("keydown", close);
  }, []);

  const loadTemplates = useCallback(async () => {
    const response = await api("templates?limit=50");
    if ([401, 403].includes(response.status)) return loseAccess();
    if (!response.ok) return setError("Không tải được registry mẫu.");
    const page = await response.json() as {items: Template[]};
    setTemplates(page.items);
    const requested = new URLSearchParams(location.search).get("template");
    setSelected(current => current ?? page.items.find(item => item.version_id === requested) ?? page.items[0] ?? null);
  }, [loseAccess]);

  useEffect(() => {
    if (!identity) return;
    const timer = setTimeout(() => void loadTemplates(), 0);
    return () => clearTimeout(timer);
  }, [identity, loadTemplates]);
  useEffect(() => {
    if (!selected) return;
    history.replaceState({}, "", `/documents?template=${encodeURIComponent(selected.version_id)}`);
    Promise.resolve().then(() => {
      setBinding(null); setRenderJob(null); setGenerated(null); setManifest(null);
      setHistoryItems([]); setError("");
      return api(`templates/${selected.template_id}/versions/${selected.version_id}`);
    })
      .then(async response => {
        if ([401, 403, 404].includes(response.status)) throw new Error("access");
        if (!response.ok) throw new Error("detail");
        return response.json() as Promise<TemplateDetail>;
      })
      .then(value => {
        setDetail(value);
        setParameters(Object.fromEntries(
          value.schema.bindings.filter(item => item.source === "user")
            .map(item => [item.field_path, ""]),
        ));
      }).catch(() => setError("Không thể mở schema mẫu."));
  }, [selected]);

  const userBindings = useMemo(
    () => detail?.schema.bindings.filter(item => item.source === "user") ?? [],
    [detail],
  );
  const lockedFields = binding?.fields.filter(item => item.source === "locked_fact") ?? [];

  async function bind() {
    if (!selected) return;
    setError("");
    const response = await api(`templates/${selected.version_id}/bind`, {
      method: "POST", body: JSON.stringify({parameters}),
    });
    if (!response.ok) return setError("Thông tin chưa hợp lệ hoặc nguồn SOT chưa sẵn sàng.");
    setBinding(await response.json() as BindResult);
  }

  async function pollRender(jobId: string) {
    poll.current?.abort();
    const controller = new AbortController();
    poll.current = controller;
    while (!controller.signal.aborted) {
      await new Promise(resolve => setTimeout(resolve, 650));
      const response = await api(`documents/render-jobs/${jobId}`, {signal: controller.signal});
      if ([401, 403].includes(response.status)) return loseAccess();
      if (!response.ok) throw new Error("render_status");
      const status = await response.json() as RenderStatus;
      setRenderJob(status);
      if (status.state === "completed" && status.version_id && status.generated_file_id) {
        const [viewerResponse, generatedResponse] = await Promise.all([
          fetch(`/api/files/versions/${status.version_id}/viewer-manifest`, {cache: "no-store"}),
          api(`documents/generated/${status.generated_file_id}`),
        ]);
        if (viewerResponse.ok) setManifest(parseManifest(await viewerResponse.json()));
        if (generatedResponse.ok) setGenerated(await generatedResponse.json() as Generated);
        if (selected) {
          const historyResponse = await api(
            `documents/history?template_id=${encodeURIComponent(selected.template_id)}`,
          );
          if (historyResponse.ok) {
            setHistoryItems((await historyResponse.json() as {items: HistoryItem[]}).items);
          }
        }
        return;
      }
      if (["failed", "cancelled"].includes(status.state)) return;
    }
  }

  async function renderDocument() {
    if (!selected) return;
    setError(""); setManifest(null); setGenerated(null);
    const response = await api(`templates/${selected.version_id}/render`, {
      method: "POST",
      body: JSON.stringify({idempotency_key: crypto.randomUUID(), parameters}),
    });
    if (!response.ok) return setError("Không thể khởi tạo bản dựng.");
    const status = await response.json() as RenderStatus;
    setRenderJob(status);
    try { await pollRender(status.render_job_id); } catch {
      setError("Mất kết nối khi theo dõi bản dựng.");
    }
  }

  async function generatedAction(action: string, withReason = false) {
    if (!renderJob?.generated_file_id) return;
    const operation = ["approve", "reject"].includes(action)
      ? `decision/${action}` : action;
    const response = await api(`documents/generated/${renderJob.generated_file_id}/${operation}`, {
      method: "POST", body: withReason ? JSON.stringify({reason: reason || "Đã kiểm tra"}) : undefined,
    });
    if (!response.ok) return setError("Thao tác không được phép ở trạng thái hiện tại.");
    const fresh = await api(`documents/generated/${renderJob.generated_file_id}`);
    if (fresh.ok) setGenerated(await fresh.json() as Generated);
  }

  if (!authReady || !identity) return <main className="gate">
    <header><span className="mark">RT</span><span>RT ROBOTICS / DOCUMENTS</span></header>
    <section className="gate-content"><p className="eyebrow">Document Operating System</p>
      <h1>Documents</h1><p className="lede">Đăng nhập email công ty để dùng mẫu và dữ liệu SOT được phân quyền.</p>
      {authReady
        ? <>
            {/* OIDC must navigate through the same-origin callback. */}
            {/* eslint-disable-next-line @next/next/no-html-link-for-pages */}
            <a className="primary" href="/api/auth/login">Đăng nhập công ty</a>
          </>
        : <span role="status">Đang kiểm tra phiên…</span>}
    </section>
  </main>;

  return <main className="document-workspace">
    <header className="document-topbar">
      <Link className="brand nav-brand" href="/"><span className="mark">RT</span><span>RT / DOCUMENTS</span></Link>
      <div><strong>{identity.display_name || identity.email}</strong>
        <span className="top-state">{renderJob ? `${renderJob.state} ${renderJob.progress}%` : "Sẵn sàng"}</span></div>
      <button type="button" onClick={() => {setRailOpen(false); setLedgerOpen(true);}}>Mẫu</button>
      <button type="button" onClick={() => {setLedgerOpen(false); setRailOpen(true);}}>SOT / duyệt</button>
    </header>
    <aside className={`template-ledger ${ledgerOpen ? "open" : ""}`} aria-label="Template registry">
      <div className="panel-heading"><div><p className="eyebrow">Governed registry</p><h1>Mẫu đã duyệt</h1></div>
        <button className="close-mobile" onClick={() => setLedgerOpen(false)}>×</button></div>
      <ol>{templates.map(item => <li key={item.version_id}><button type="button"
        aria-current={selected?.version_id === item.version_id ? "true" : undefined}
        onClick={() => {setSelected(item); setLedgerOpen(false);}}>
        <span>{item.format} · V{item.version_ordinal}</span><strong>{item.display_name}</strong>
        <small>{item.category} · {item.document_class}</small>
      </button></li>)}</ol>
      {!templates.length && <p>Không có mẫu được cấp quyền.</p>}
    </aside>
    <section className="assembly-desk" aria-label="Structured assembly desk">
      <div className="assembly-form">
        <p className="eyebrow">Structured assembly</p>
        <h2>{selected?.display_name ?? "Chọn mẫu"}</h2>
        {userBindings.map(item => <label key={item.field_path}>{item.field_path}
          {item.required && <span aria-label="bắt buộc"> *</span>}
          <input value={parameters[item.field_path] ?? ""}
            required={item.required}
            onChange={event => setParameters(current => ({
              ...current, [item.field_path]: event.target.value,
            }))}/></label>)}
        <div className="assembly-actions">
          <button type="button" onClick={() => void bind()}>Kiểm tra dữ liệu</button>
          <button className="primary" type="button" disabled={!detail}
            onClick={() => void renderDocument()}>Tạo bản xem</button>
        </div>
        {binding && <p role="status" className={binding.valid ? "valid" : "invalid"}>
          {binding.valid ? "Dữ liệu hợp lệ và đã khóa nguồn." :
            `Thiếu: ${binding.missing.join(", ") || "không"} · Chặn: ${binding.blocked.map(x => x.code).join(", ") || "không"}`}
        </p>}
        {renderJob && !manifest && <div className="render-progress" aria-live="polite">
          <progress max="100" value={renderJob.progress}/><span>{renderJob.state}</span>
        </div>}
        {error && <p role="alert" className="invalid">{error}</p>}
      </div>
      <div className="document-preview">
        {!manifest && <div className="viewer-empty"><p className="eyebrow">TIP-008 safe viewer</p>
          <h2>Bản xem thật xuất hiện tại đây</h2></div>}
        {manifest && <><FileViewer manifest={manifest} locator={locator}
          onLocator={setLocator} onAccessLoss={loseAccess}/>
          {selected?.document_class !== "internal" && generated?.lifecycle !== "issued"
            && <div className="draft-watermark" aria-label="Trạng thái bản nháp">DRAFT · CHƯA PHÁT HÀNH</div>}
        </>}
      </div>
    </section>
    <aside className={`document-rail ${railOpen ? "open" : ""}`} aria-label="Fact and approval rail">
      <div className="panel-heading"><h2>SOT & Approval</h2>
        <button className="close-mobile" onClick={() => setRailOpen(false)}>×</button></div>
      <h3>Nguồn đã khóa</h3>
      {lockedFields.map(item => <article key={item.field_path}>
        <strong>{item.field_path}</strong><p>{String(item.value ?? "")}</p>
        <code>{item.record_key}<br/>{item.record_checksum?.slice(0, 16)}…</code>
        <small>{item.provenance_level} · {item.freshness_state}</small>
      </article>)}
      {!lockedFields.length && <p>Kiểm tra dữ liệu để xem bằng chứng khóa.</p>}
      {generated && <section className="approval-timeline">
        <h3>Phiên bản & trạng thái</h3>
        <p className={`state-chip ${generated.lifecycle}`}>{generated.lifecycle}</p>
        <div className="checksum-row"><code title={generated.checksum}>{generated.checksum}</code>
          <button type="button" onClick={() => void navigator.clipboard.writeText(generated.checksum)}>
            Sao chép
          </button></div>
        {generated.approvals.map(item => <article key={item.approval_id}>
          <strong>{item.decision}</strong><p>{item.reason}</p>
          <small>{item.reviewer_display_name ?? "Reviewer"} · {new Date(item.decided_at).toLocaleString("vi-VN")}</small>
        </article>)}
        {generated.issuance && <article><strong>{generated.issuance.issue_number}</strong>
          <p>{generated.issuance.state}</p></article>}
        <label>Lý do<input value={reason} onChange={event => setReason(event.target.value)}/></label>
        <div className="rail-actions">
          {generated.lifecycle === "draft" && <button onClick={() => void generatedAction("submit")}>Gửi duyệt</button>}
          {generated.lifecycle === "in_review" && <>
            <button onClick={() => void generatedAction("approve", true)}>Duyệt</button>
            <button onClick={() => void generatedAction("reject", true)}>Từ chối</button>
          </>}
          {generated.lifecycle === "approved" && <button onClick={() => void generatedAction("issue")}>Phát hành</button>}
          {generated.lifecycle === "issued" && <button onClick={() => void generatedAction("revoke", true)}>Thu hồi</button>}
        </div>
        <h3>Lịch sử & so sánh</h3>
        <ol className="generated-history">{historyItems.map((item, index) =>
          <li key={item.generated_file_id}>
            <strong>V{historyItems.length - index} · {item.lifecycle}</strong>
            <code title={item.checksum}>{item.checksum.slice(0, 16)}…</code>
            <small>{new Date(item.created_at).toLocaleString("vi-VN")}</small>
            <p>Tham số đổi: {item.comparison.changed_parameters.join(", ") || "—"}</p>
            <p>SOT đổi: {item.comparison.changed_locked_facts.join(", ") || "—"}</p>
            {(item.comparison.template_changed || item.comparison.checksum_changed
              || item.comparison.lifecycle_changed) && <small>
              {item.comparison.template_changed ? "template · " : ""}
              {item.comparison.checksum_changed ? "checksum · " : ""}
              {item.comparison.lifecycle_changed ? "trạng thái" : ""}
            </small>}
          </li>)}
        </ol>
      </section>}
    </aside>
    {(ledgerOpen || railOpen) && <button className="scrim" aria-label="Đóng bảng"
      onClick={() => {setLedgerOpen(false); setRailOpen(false);}}/>}
  </main>;
}
