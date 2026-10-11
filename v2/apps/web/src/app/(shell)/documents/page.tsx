"use client";

/**
 * Documents workspace (TIP-009), living inside the unified shell since
 * TIP-011: the AppShell owns the topbar/nav/`<main>`; this page renders ONE
 * `PageHeader`, the template registry + assembly desk, and the SHARED
 * Evidence Rail (`src/rail`) — locked SOT facts as typed entries, approval
 * timeline as the rail footer.
 */

import React, {useCallback, useEffect, useMemo, useRef, useState} from "react";
import {lockedFieldEvidence} from "../../../documents/evidence";
import {Locator, parseManifest, ViewerManifest} from "../../../files/contracts";
import {FileViewer} from "../../../files/viewers";
import {formatDateTime} from "../../../i18n/format";
import type {MessageKey} from "../../../i18n/messages";
import {useI18n} from "../../../i18n/provider";
import {EvidenceRail} from "../../../rail/EvidenceRail";
import {PageHeader} from "../../../shell/AppShell";

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
  attempt?: number; max_attempts?: number; retryable?: boolean;
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

const ACTIVE_RENDER_STATES = new Set(["pending", "binding", "rendering", "validating"]);
const RENDER_STATE_LABELS: Record<string, MessageKey> = {
  pending: "documents.renderState.pending", binding: "documents.renderState.binding",
  rendering: "documents.renderState.rendering", validating: "documents.renderState.validating",
  completed: "documents.renderState.completed", failed: "documents.renderState.failed",
  cancelled: "documents.renderState.cancelled",
};

export default function DocumentsPage() {
  const {t, locale} = useI18n();
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [templates, setTemplates] = useState<Template[]>([]);
  const [selected, setSelected] = useState<Template | null>(null);
  const [detail, setDetail] = useState<TemplateDetail | null>(null);
  const [parameters, setParameters] = useState<Record<string, string>>({});
  const [binding, setBinding] = useState<BindResult | null>(null);
  const [renderJob, setRenderJob] = useState<RenderStatus | null>(null);
  const [renderActionPending, setRenderActionPending] = useState(false);
  const [generated, setGenerated] = useState<Generated | null>(null);
  const [historyItems, setHistoryItems] = useState<HistoryItem[]>([]);
  const [manifest, setManifest] = useState<ViewerManifest | null>(null);
  const [locator, setLocator] = useState<Locator>({});
  const [error, setError] = useState<MessageKey | "">("");
  const [reason, setReason] = useState("");
  const [ledgerOpen, setLedgerOpen] = useState(false);
  const [railOpen, setRailOpen] = useState(false);
  const poll = useRef<AbortController | null>(null);
  // A delayed mutation must not restore another template's job or busy state.
  const requestContext = useRef(0);

  const loseAccess = useCallback(() => {
    requestContext.current += 1;
    poll.current?.abort();
    setRenderActionPending(false);
    setIdentity(null); setTemplates([]); setSelected(null); setDetail(null);
    setManifest(null); setGenerated(null); setRenderJob(null);
  }, []);

  useEffect(() => {
    fetch("/api/auth/me", {cache: "no-store"})
      .then(async response => setIdentity(response.ok ? await response.json() as Identity : null))
      .catch(() => setIdentity(null)).finally(() => setAuthReady(true));
    return () => {requestContext.current += 1; poll.current?.abort();};
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
    if (!response.ok) return setError("documents.error.registry");
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
    const context = ++requestContext.current;
    poll.current?.abort();
    history.replaceState({}, "", `/documents?template=${encodeURIComponent(selected.version_id)}`);
    Promise.resolve().then(() => {
      if (requestContext.current !== context) return null;
      setRenderActionPending(false);
      setBinding(null); setRenderJob(null); setGenerated(null); setManifest(null);
      setHistoryItems([]); setError("");
      return api(`templates/${selected.template_id}/versions/${selected.version_id}`);
    })
      .then(async response => {
        if (!response || requestContext.current !== context) return null;
        if ([401, 403, 404].includes(response.status)) throw new Error("access");
        if (!response.ok) throw new Error("detail");
        return response.json() as Promise<TemplateDetail>;
      })
      .then(value => {
        if (!value || requestContext.current !== context) return;
        setDetail(value);
        setParameters(Object.fromEntries(
          value.schema.bindings.filter(item => item.source === "user")
            .map(item => [item.field_path, ""]),
        ));
      }).catch(() => {
        if (requestContext.current === context) setError("documents.error.schema");
      });
  }, [selected]);

  const userBindings = useMemo(
    () => detail?.schema.bindings.filter(item => item.source === "user") ?? [],
    [detail],
  );
  const lockedFields = useMemo(
    () => binding?.fields.filter(item => item.source === "locked_fact") ?? [],
    [binding],
  );
  const railEntries = useMemo(
    () => lockedFields.map(lockedFieldEvidence),
    [lockedFields],
  );

  async function bind() {
    if (!selected) return;
    setError("");
    const response = await api(`templates/${selected.version_id}/bind`, {
      method: "POST", body: JSON.stringify({parameters}),
    });
    if (!response.ok) return setError("documents.error.bind");
    setBinding(await response.json() as BindResult);
  }

  async function pollRender(jobId: string, context: number) {
    if (requestContext.current !== context) return;
    poll.current?.abort();
    const controller = new AbortController();
    poll.current = controller;
    const current = () => !controller.signal.aborted && requestContext.current === context;
    try {
      while (current()) {
        await new Promise(resolve => setTimeout(resolve, 650));
        if (!current()) return;
        const response = await api(`documents/render-jobs/${jobId}`, {signal: controller.signal});
        if (!current()) return;
        if ([401, 403].includes(response.status)) return loseAccess();
        if (!response.ok) throw new Error("render_status");
        const status = await response.json() as RenderStatus;
        if (!current()) return;
        setRenderJob(status);
        if (status.state === "completed" && status.version_id && status.generated_file_id) {
          const [viewerResponse, generatedResponse] = await Promise.all([
            fetch(`/api/files/versions/${status.version_id}/viewer-manifest`, {
              cache: "no-store", signal: controller.signal,
            }),
            api(`documents/generated/${status.generated_file_id}`, {signal: controller.signal}),
          ]);
          if (!current()) return;
          const viewer = viewerResponse.ok ? parseManifest(await viewerResponse.json()) : null;
          const generatedDetail = generatedResponse.ok
            ? await generatedResponse.json() as Generated : null;
          if (!current()) return;
          if (viewer) setManifest(viewer);
          if (generatedDetail) setGenerated(generatedDetail);
          if (selected) {
            const historyResponse = await api(
              `documents/history?template_id=${encodeURIComponent(selected.template_id)}`,
              {signal: controller.signal},
            );
            if (historyResponse.ok) {
              const items = (await historyResponse.json() as {items: HistoryItem[]}).items;
              if (current()) setHistoryItems(items);
            }
          }
          return;
        }
        if (["failed", "cancelled"].includes(status.state)) return;
      }
    } catch (failure) {
      if (current()) throw failure;
    }
  }

  function trackRender(jobId: string, context: number) {
    void pollRender(jobId, context).catch(() => {
      if (requestContext.current === context) setError("documents.error.renderLost");
    });
  }

  async function renderDocument() {
    if (!selected || renderActionPending) return;
    const context = requestContext.current;
    setRenderActionPending(true);
    setError(""); setManifest(null); setGenerated(null);
    try {
      const response = await api(`templates/${selected.version_id}/render`, {
        method: "POST",
        body: JSON.stringify({idempotency_key: crypto.randomUUID(), parameters}),
      });
      if (requestContext.current !== context) return;
      if ([401, 403].includes(response.status)) return loseAccess();
      if (!response.ok) return setError("documents.error.render");
      const status = await response.json() as RenderStatus;
      if (requestContext.current !== context) return;
      setRenderJob(status);
      trackRender(status.render_job_id, context);
    } catch {
      if (requestContext.current === context) setError("documents.error.render");
    } finally {
      if (requestContext.current === context) setRenderActionPending(false);
    }
  }

  async function renderAction(action: "retry" | "cancel") {
    if (!renderJob || renderActionPending) return;
    const context = requestContext.current;
    const jobId = renderJob.render_job_id;
    setRenderActionPending(true); setError("");
    try {
      const response = await api(`documents/render-jobs/${jobId}/${action}`, {
        method: "POST",
      });
      if (requestContext.current !== context) return;
      if ([401, 403].includes(response.status)) return loseAccess();
      if (!response.ok) {
        const result = await response.json().catch(() => null) as {error?: {code?: string}} | null;
        if (requestContext.current !== context) return;
        if (result?.error?.code === "render_retry_exhausted") {
          setRenderJob(current => current?.render_job_id === jobId
            ? {...current, retryable: false} : current);
          return setError("documents.error.retryExhausted");
        }
        return setError("documents.error.action");
      }
      const status = await response.json() as RenderStatus;
      if (requestContext.current !== context) return;
      if (status.render_job_id !== jobId) return setError("documents.error.action");
      poll.current?.abort();
      setRenderJob(status);
      if (ACTIVE_RENDER_STATES.has(status.state)) trackRender(status.render_job_id, context);
    } catch {
      if (requestContext.current === context) setError("documents.error.action");
    } finally {
      if (requestContext.current === context) setRenderActionPending(false);
    }
  }

  const renderActive = renderJob !== null && ACTIVE_RENDER_STATES.has(renderJob.state);
  const retryExhausted = renderJob?.attempt !== undefined && renderJob.max_attempts !== undefined
    && renderJob.attempt >= renderJob.max_attempts;
  const retryAllowed = renderJob?.retryable === true && !retryExhausted
    && ["failed", "cancelled"].includes(renderJob.state);
  const renderStateLabel = renderJob
    ? t(RENDER_STATE_LABELS[renderJob.state] ?? "documents.renderState.unknown") : "";

  async function generatedAction(action: string, withReason = false) {
    if (!renderJob?.generated_file_id) return;
    const operation = ["approve", "reject"].includes(action)
      ? `decision/${action}` : action;
    const response = await api(`documents/generated/${renderJob.generated_file_id}/${operation}`, {
      method: "POST",
      body: withReason
        ? JSON.stringify({reason: reason || t("documents.defaultReason")}) : undefined,
    });
    if (!response.ok) return setError("documents.error.action");
    const fresh = await api(`documents/generated/${renderJob.generated_file_id}`);
    if (fresh.ok) setGenerated(await fresh.json() as Generated);
  }

  if (!authReady || !identity) {
    return <>
      <PageHeader eyebrow={t("documents.eyebrow")} title={t("documents.title")}/>
      <section className="placeholder-card">
        {!authReady && <p role="status">{t("shell.sessionChecking")}</p>}
        {authReady && <p className="lede">{t("documents.gate.lede")}</p>}
      </section>
    </>;
  }

  return <div className="document-workspace-embed">
    <PageHeader eyebrow={t("documents.eyebrow")} title={t("documents.title")}
      actions={<div className="page-actions">
        <span className="top-state">
          {renderJob ? `${renderStateLabel} ${renderJob.progress}%` : t("documents.ready")}
        </span>
        <button className="ledger-toggle" type="button"
          onClick={() => {setRailOpen(false); setLedgerOpen(true);}}>
          {t("documents.templatesButton")}
        </button>
        <button className="rail-sheet-toggle" type="button"
          onClick={() => {setLedgerOpen(false); setRailOpen(true);}}>
          {t("documents.railButton")}
        </button>
      </div>}/>
    <div className="doc-layout">
      <aside className={`template-ledger ${ledgerOpen ? "open" : ""}`}
        aria-label={t("documents.registryAria")}>
        <div className="panel-heading"><div>
          <p className="eyebrow">{t("documents.registryEyebrow")}</p>
          <h2>{t("documents.registryTitle")}</h2></div>
          <button className="close-mobile" aria-label={t("shell.closePanels")}
            onClick={() => setLedgerOpen(false)}>×</button></div>
        <ol>{templates.map(item => <li key={item.version_id}><button type="button"
          aria-current={selected?.version_id === item.version_id ? "true" : undefined}
          onClick={() => {
            if (selected?.version_id !== item.version_id) {
              requestContext.current += 1;
              poll.current?.abort();
            }
            setSelected(item); setLedgerOpen(false);
          }}>
          <span>{item.format} · V{item.version_ordinal}</span><strong>{item.display_name}</strong>
          <small>{item.category} · {item.document_class}</small>
        </button></li>)}</ol>
        {!templates.length && <p>{t("documents.registryEmpty")}</p>}
      </aside>
      <section className="assembly-desk" aria-label={t("documents.deskAria")}>
        <div className="assembly-form">
          <p className="eyebrow">{t("documents.assemblyEyebrow")}</p>
          <h2>{selected?.display_name ?? t("documents.pickTemplate")}</h2>
          {userBindings.map(item => <label key={item.field_path}>{item.field_path}
            {item.required && <span aria-label={t("documents.required")}> *</span>}
            <input value={parameters[item.field_path] ?? ""}
              required={item.required}
              onChange={event => setParameters(current => ({
                ...current, [item.field_path]: event.target.value,
              }))}/></label>)}
          <div className="assembly-actions">
            <button type="button" onClick={() => void bind()}>{t("documents.bind")}</button>
            <button className="primary" type="button" disabled={!detail || renderActive || renderActionPending}
              onClick={() => void renderDocument()}>{t("documents.render")}</button>
            {retryAllowed && <button type="button" disabled={renderActionPending}
              onClick={() => void renderAction("retry")}>{t("documents.action.retry")}</button>}
            {renderActive && <button type="button" disabled={renderActionPending}
              onClick={() => void renderAction("cancel")}>{t("documents.action.cancel")}</button>}
          </div>
          {binding && <p role="status" className={binding.valid ? "valid" : "invalid"}>
            {binding.valid ? t("documents.bind.valid") :
              `${t("documents.bind.missing")}: ${binding.missing.join(", ")
                || t("documents.bind.none")} · ${t("documents.bind.blocked")}: ${
                binding.blocked.map(x => x.code).join(", ") || t("documents.bind.none")}`}
          </p>}
          {renderJob && !manifest && <div className="render-progress" aria-live="polite">
            <progress max="100" value={renderJob.progress}/><span>{renderStateLabel}</span>
          </div>}
          {renderJob?.state === "failed" && <p role="status" className="invalid">
            {t(renderJob.error_code === "render_lease_expired"
              ? "documents.error.renderExpired" : "documents.error.renderFailed")}
          </p>}
          {retryExhausted && ["failed", "cancelled"].includes(renderJob?.state ?? "")
            && <p role="status" className="invalid">{t("documents.error.retryExhausted")}</p>}
          {error && <p role="alert" className="invalid">{t(error)}</p>}
        </div>
        <div className="document-preview">
          {!manifest && <div className="viewer-empty">
            <p className="eyebrow">{t("documents.previewEyebrow")}</p>
            <h2>{t("documents.previewEmpty")}</h2></div>}
          {manifest && <><FileViewer manifest={manifest} locator={locator}
            onLocator={setLocator} onAccessLoss={loseAccess}/>
            {selected?.document_class !== "internal" && generated?.lifecycle !== "issued"
              && <div className="draft-watermark" aria-label={t("documents.watermarkAria")}>
                {t("documents.watermark")}</div>}
          </>}
        </div>
      </section>
      <EvidenceRail entries={railEntries} open={railOpen}
        onClose={() => setRailOpen(false)}
        note={<div className="doc-note">
          <h3>{t("documents.lockedSources")}</h3>
          {!lockedFields.length && <p>{t("documents.lockedEmpty")}</p>}
        </div>}
        footer={generated ? <section className="approval-timeline doc-note">
          <h3>{t("documents.rail.version")}</h3>
          <p className={`state-chip ${generated.lifecycle}`}>{generated.lifecycle}</p>
          <div className="checksum-row"><code title={generated.checksum}>{generated.checksum}</code>
            <button type="button" onClick={() => void navigator.clipboard.writeText(generated.checksum)}>
              {t("documents.copy")}
            </button></div>
          {generated.approvals.map(item => <article key={item.approval_id}>
            <strong>{item.decision}</strong><p>{item.reason}</p>
            <small>{item.reviewer_display_name ?? t("documents.reviewerFallback")} · {
              formatDateTime(item.decided_at, locale)}</small>
          </article>)}
          {generated.issuance && <article><strong>{generated.issuance.issue_number}</strong>
            <p>{generated.issuance.state}</p></article>}
          <label>{t("documents.reason")}
            <input value={reason} onChange={event => setReason(event.target.value)}/></label>
          <div className="rail-actions">
            {generated.lifecycle === "draft" && <button onClick={() => void generatedAction("submit")}>
              {t("documents.action.submit")}</button>}
            {generated.lifecycle === "in_review" && <>
              <button onClick={() => void generatedAction("approve", true)}>{t("documents.action.approve")}</button>
              <button onClick={() => void generatedAction("reject", true)}>{t("documents.action.reject")}</button>
            </>}
            {generated.lifecycle === "approved" && <button onClick={() => void generatedAction("issue")}>
              {t("documents.action.issue")}</button>}
            {generated.lifecycle === "issued" && <button onClick={() => void generatedAction("revoke", true)}>
              {t("documents.action.revoke")}</button>}
          </div>
          <h3>{t("documents.rail.history")}</h3>
          <ol className="generated-history">{historyItems.map((item, index) =>
            <li key={item.generated_file_id}>
              <strong>V{historyItems.length - index} · {item.lifecycle}</strong>
              <code title={item.checksum}>{item.checksum.slice(0, 16)}…</code>
              <small>{formatDateTime(item.created_at, locale)}</small>
              <p>{t("documents.paramsChanged")} {
                item.comparison.changed_parameters.join(", ") || "—"}</p>
              <p>{t("documents.sotChanged")} {
                item.comparison.changed_locked_facts.join(", ") || "—"}</p>
              {(item.comparison.template_changed || item.comparison.checksum_changed
                || item.comparison.lifecycle_changed) && <small>
                {item.comparison.template_changed ? "template · " : ""}
                {item.comparison.checksum_changed ? "checksum · " : ""}
                {item.comparison.lifecycle_changed ? t("documents.lifecycleChanged") : ""}
              </small>}
            </li>)}
          </ol>
        </section> : null}/>
    </div>
    {(ledgerOpen || railOpen) && <button className="scrim" aria-label={t("shell.closePanels")}
      onClick={() => {setLedgerOpen(false); setRailOpen(false);}}/>}
  </div>;
}
