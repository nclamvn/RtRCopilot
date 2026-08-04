"use client";

import React, {FormEvent, useCallback, useEffect, useState} from "react";
import {
  JobHealth, parseJobHealth, parseResearchSource, parseResearchSources, parseSettingVersions,
  parsePilotReadiness, parseSettings, parseSubject, parseSubjects, PilotReadiness,
  ResearchSource, SettingValue, SettingView, SettingVersion, SubjectAccount,
} from "../../../admin/contracts";
import {formatDateTime} from "../../../i18n/format";
import {MessageKey} from "../../../i18n/messages";
import {useI18n} from "../../../i18n/provider";
import {IDLE, Load, Surface, TypedError, errorText, parseTypedError} from "../../../shared/surface";
import {PageHeader} from "../../../shell/AppShell";

type Identity = {user_id: string; email: string; display_name: string; roles: string[]};
type View = "health" | "corpus" | "subjects" | "sources" | "settings" | "gaps";
type Notice = {kind: "success" | "error"; text: string};

const VIEWS: ReadonlyArray<{id: View; label: MessageKey}> = [
  {id: "health", label: "admin.nav.health"}, {id: "corpus", label: "admin.nav.corpus"},
  {id: "subjects", label: "admin.nav.subjects"},
  {id: "sources", label: "admin.nav.sources"}, {id: "settings", label: "admin.nav.settings"},
  {id: "gaps", label: "admin.nav.gaps"},
];
const api = (path: string, init?: RequestInit) => fetch(`/api/governance/admin/${path}`, {
  cache: "no-store", ...init, headers: {"content-type": "application/json", ...(init?.headers ?? {})},
});

export default function AdminPage() {
  const {t, locale} = useI18n();
  const [identity, setIdentity] = useState<Identity | null>(null);
  const [authReady, setAuthReady] = useState(false);
  const [view, setView] = useState<View>("health");
  const [health, setHealth] = useState<Load<JobHealth>>(IDLE);
  const [pilot, setPilot] = useState<Load<PilotReadiness>>(IDLE);
  const [subjects, setSubjects] = useState<Load<SubjectAccount[]>>(IDLE);
  const [sources, setSources] = useState<Load<ResearchSource[]>>(IDLE);
  const [settings, setSettings] = useState<Load<SettingView[]>>(IDLE);
  const [versions, setVersions] = useState<Load<SettingVersion[]>>(IDLE);
  const [selectedSubject, setSelectedSubject] = useState("");
  const [selectedSource, setSelectedSource] = useState("");
  const [selectedSetting, setSelectedSetting] = useState("");
  const [notice, setNotice] = useState<Notice | null>(null);
  const [busy, setBusy] = useState(false);

  const loseAccess = useCallback(() => {
    setIdentity(null); setHealth(IDLE); setPilot(IDLE); setSubjects(IDLE); setSources(IDLE); setSettings(IDLE);
    setVersions(IDLE); setNotice(null);
  }, []);
  const load = useCallback(async <T,>(path: string, parser: (value: unknown) => T, setter: (value: Load<T>) => void) => {
    setter({state: "loading"});
    try {
      const response = await api(path); if (response.status === 401) return loseAccess();
      const body: unknown = await response.json().catch(() => null);
      if (response.status === 403) return setter({state: "denied", error: parseTypedError(body)});
      if (!response.ok) return setter({state: "error", error: parseTypedError(body)});
      setter({state: "ready", data: parser(body)});
    } catch { setter({state: "error", error: {code: "contract_violation", message: "", requestId: ""}}); }
  }, [loseAccess]);
  const mutate = useCallback(async <T,>(path: string, method: "POST" | "PUT" | "PATCH", payload: unknown, parser: (value: unknown) => T) => {
    setBusy(true); setNotice(null);
    try {
      const response = await api(path, {method, body: JSON.stringify(payload)});
      if (response.status === 401) { loseAccess(); return null; }
      const body: unknown = await response.json().catch(() => null);
      if (!response.ok) throw parseTypedError(body);
      const result = parser(body); setNotice({kind: "success", text: t("admin.notice.saved")}); return result;
    } catch (error) {
      const typed: TypedError = error && typeof error === "object" && "code" in error
        ? error as TypedError : {code: "contract_violation", message: "", requestId: ""};
      setNotice({kind: "error", text: `${t("surface.error")} · ${errorText(typed)}`}); return null;
    } finally { setBusy(false); }
  }, [loseAccess, t]);

  useEffect(() => {
    fetch("/api/auth/me", {cache: "no-store"}).then(async response => {
      setIdentity(response.ok ? await response.json() as Identity : null);
    }).catch(() => setIdentity(null)).finally(() => setAuthReady(true));
  }, []);
  const refreshAll = useCallback(() => {
    void load("jobs/health", parseJobHealth, setHealth);
    void load("pilot-readiness", parsePilotReadiness, setPilot);
    void load("subjects?limit=200", parseSubjects, setSubjects);
    void load("research-sources", parseResearchSources, setSources);
    void load("settings", parseSettings, setSettings);
  }, [load]);
  useEffect(() => {
    if (!identity) return;
    const timer = setTimeout(refreshAll, 0);
    return () => clearTimeout(timer);
  }, [identity, refreshAll]);

  const selectedSubjectData = subjects.state === "ready"
    ? subjects.data.find(item => item.user_id === selectedSubject) ?? null : null;
  const selectedSourceData = sources.state === "ready"
    ? sources.data.find(item => item.source_id === selectedSource) ?? null : null;
  const selectedSettingData = settings.state === "ready"
    ? settings.data.find(item => item.setting_key === selectedSetting) ?? null : null;

  if (!authReady) return <><PageHeader eyebrow={t("admin.eyebrow")} title={t("admin.title")}/><p role="status">{t("surface.loading")}</p></>;
  if (!identity) return <><PageHeader eyebrow={t("admin.eyebrow")} title={t("admin.title")}/><section className="admin-access" role="status"><span>AUTH / 401</span><h2>{t("admin.auth.title")}</h2><p>{t("admin.auth.body")}</p></section></>;

  const denied = health.state === "denied" ? health : null;
  return <>
    <PageHeader eyebrow={t("admin.eyebrow")} title={t("admin.title")}/>
    <section className="admin-boundary" aria-label={t("admin.boundary.label")}>
      <div><span className="admin-live-dot" aria-hidden="true"/><strong>{t("admin.boundary.control")}</strong></div>
      <p>{t("admin.boundary.body")}</p>
      <a href="/api/status" target="_blank" rel="noreferrer">{t("admin.boundary.status")}</a>
    </section>
    {denied ? <Surface load={denied}>{() => null}</Surface> : <div className="admin-workspace">
      <nav className="admin-spine" aria-label={t("admin.nav.label")}>
        <p>{t("admin.nav.kicker")}</p>
        {VIEWS.map((item, index) => <button key={item.id} type="button"
          className={view === item.id ? "active" : ""} aria-current={view === item.id ? "page" : undefined}
          onClick={() => {setView(item.id); setNotice(null);}}>
          <span>{String(index + 1).padStart(2, "0")}</span>{t(item.label)}
        </button>)}
        <footer><strong>{identity.display_name}</strong><small>{identity.email}</small></footer>
      </nav>
      <main className="admin-surface">
        {notice && <div role={notice.kind === "error" ? "alert" : "status"} className={`admin-notice ${notice.kind}`}>{notice.text}</div>}
        {view === "health" && <HealthPanel load={health} locale={locale} refresh={() => void load("jobs/health", parseJobHealth, setHealth)} t={t}/>}
        {view === "corpus" && <PilotPanel load={pilot} refresh={() => void load("pilot-readiness", parsePilotReadiness, setPilot)} t={t}/>}
        {view === "subjects" && <SubjectsPanel load={subjects} selected={selectedSubjectData} setSelected={setSelectedSubject}
          busy={busy} t={t} onSubmit={async payload => {
            if (!selectedSubjectData) return; const updated = await mutate(`subjects/${selectedSubjectData.user_id}/bindings`, "POST", payload, parseSubject);
            if (updated) setSubjects(current => current.state === "ready" ? {state: "ready", data: current.data.map(item => item.user_id === updated.user_id ? updated : item)} : current);
          }}/>
        }
        {view === "sources" && <SourcesPanel load={sources} selected={selectedSourceData} setSelected={setSelectedSource} busy={busy} t={t}
          onCreate={async payload => {const created = await mutate("research-sources", "POST", payload, parseResearchSource); if (created) {setSources(current => current.state === "ready" ? {state: "ready", data: [...current.data, created]} : current); setSelectedSource(created.source_id);}}}
          onUpdate={async payload => {if (!selectedSourceData) return; const updated = await mutate(`research-sources/${selectedSourceData.source_id}`, "PATCH", payload, parseResearchSource); if (updated) setSources(current => current.state === "ready" ? {state: "ready", data: current.data.map(item => item.source_id === updated.source_id ? updated : item)} : current);}}/>}
        {view === "settings" && <SettingsPanel load={settings} versions={versions} selected={selectedSettingData} setSelected={key => {setSelectedSetting(key); setVersions(IDLE); if (key) void load(`settings/${encodeURIComponent(key)}/versions`, parseSettingVersions, setVersions);}} busy={busy} t={t}
          onSubmit={async payload => {if (!selectedSettingData) return; const result = await mutate(`settings/${encodeURIComponent(selectedSettingData.setting_key)}`, "PUT", payload, () => true); if (result) {void load("settings", parseSettings, setSettings); void load(`settings/${encodeURIComponent(selectedSettingData.setting_key)}/versions`, parseSettingVersions, setVersions);}}}/>}
        {view === "gaps" && <GapPanel busy={busy} t={t} onSubmit={async (id, payload) => {await mutate(`gaps/${id}/priority`, "POST", payload, () => true);}}/>}
      </main>
    </div>}
  </>;
}

type T = (key: MessageKey) => string;
function PanelTitle({index, title, body}: {index: string; title: string; body: string}) {
  return <header className="admin-panel-title"><span>{index}</span><div><h2>{title}</h2><p>{body}</p></div></header>;
}
function HealthPanel({load, locale, refresh, t}: {load: Load<JobHealth>; locale: "vi" | "en"; refresh: () => void; t: T}) {
  return <section><PanelTitle index="01" title={t("admin.health.title")} body={t("admin.health.body")}/><Surface load={load} retry={refresh}>{data => <>
    <div className="admin-health-meta"><span>{t("admin.health.computed")}</span><strong>{formatDateTime(data.computed_at, locale)}</strong><button type="button" onClick={refresh}>{t("surface.retry")}</button></div>
    <div className="admin-ledger">{data.families.map(family => {const failures = family.recent_failures.length; return <article key={family.family} className={failures ? "risk" : "healthy"}>
      <header><div><span>{family.family.toUpperCase()}</span><h3>{family.family}</h3></div><b>{failures ? t("admin.health.attention") : t("admin.health.healthy")}</b></header>
      <dl><div><dt>{t("admin.health.jobs")}</dt><dd>{Object.entries(family.job_counts).map(([key, count]) => `${key} ${count}`).join(" · ") || "—"}</dd></div><div><dt>{t("admin.health.outbox")}</dt><dd>{Object.entries(family.outbox_counts).map(([key, count]) => `${key} ${count}`).join(" · ") || "—"}</dd></div></dl>
      {failures > 0 && <ul>{family.recent_failures.map(item => <li key={item.job_id}><code>{item.error_code ?? item.status}</code><span>{item.kind}</span></li>)}</ul>}
    </article>;})}</div></>}</Surface></section>;
}
function PilotPanel({load, refresh, t}: {load: Load<PilotReadiness>; refresh: () => void; t: T}) {
  return <section><PanelTitle index="02" title={t("admin.corpus.title")} body={t("admin.corpus.body")}/><Surface load={load} retry={refresh}>{data => <>
    <div className="admin-health-meta"><span>{t("admin.health.computed")}</span><strong>{data.computed_at}</strong><button type="button" onClick={refresh}>{t("surface.retry")}</button></div>
    <div className="admin-ledger pilot-summary">
      <PilotCard label="SOT" value={`${data.sot.strict_records} / ${data.sot.active_records}`} detail={`${data.sot.caveated_records} ${t("admin.corpus.caveated")} · ${data.sot.placeholder_owner_records} ${t("admin.corpus.placeholderOwners")}`}/>
      <PilotCard label="FILES" value={String(data.files.representative_versions)} detail={Object.entries(data.files.viewer_families).map(([key, value]) => `${key} ${value}`).join(" · ") || "—"}/>
      <PilotCard label="TEMPLATES" value={`${data.templates.approved_templates} / ${data.templates.templates}`} detail={`${data.templates.locked_bindings} ${t("admin.corpus.locked")}`}/>
      <PilotCard label="RESEARCH" value={String(data.research.records)} detail={Object.entries(data.research.corroboration).map(([key, value]) => `${key} ${value}`).join(" · ") || "—"}/>
    </div>
    <div className="pilot-gates" aria-label={t("admin.corpus.gates")}>
      {data.gates.map(gate => <article key={gate.gate_key} className={gate.state}>
        <header><code>{gate.gate_key}</code><b>{gate.state.toUpperCase()}</b></header>
        <p>{gate.detail}</p><strong>{gate.actual} / {gate.target}</strong>
      </article>)}
    </div>
    <p className="admin-warning">{t("admin.corpus.boundary")}</p>
  </>}</Surface></section>;
}
function PilotCard({label, value, detail}: {label: string; value: string; detail: string}) {
  return <article><header><div><span>{label}</span><h3>{label}</h3></div></header><p className="tile-figure">{value}</p><small>{detail}</small></article>;
}
function SubjectsPanel({load, selected, setSelected, busy, onSubmit, t}: {load: Load<SubjectAccount[]>; selected: SubjectAccount | null; setSelected: (id: string) => void; busy: boolean; onSubmit: (payload: unknown) => Promise<void>; t: T}) {
  return <section><PanelTitle index="03" title={t("admin.subjects.title")} body={t("admin.subjects.body")}/><div className="admin-split"><Surface load={load} empty={t("admin.empty")}>
    {data => <div className="admin-list">{data.map(item => <button type="button" key={item.user_id} className={selected?.user_id === item.user_id ? "selected" : ""} onClick={() => setSelected(item.user_id)}><strong>{item.display_name}</strong><span>{item.email ?? item.user_id}</span><small>{[...item.roles, ...item.groups].join(" · ") || t("admin.subjects.unbound")}</small></button>)}</div>}
  </Surface><div className="admin-editor">{selected ? <BindingForm subject={selected} busy={busy} onSubmit={onSubmit} t={t}/> : <p className="surface-empty">{t("admin.select.subject")}</p>}</div></div></section>;
}
function BindingForm({subject, busy, onSubmit, t}: {subject: SubjectAccount; busy: boolean; onSubmit: (payload: unknown) => Promise<void>; t: T}) {
  const submit = (event: FormEvent<HTMLFormElement>) => {event.preventDefault(); const data = new FormData(event.currentTarget); void onSubmit({binding: data.get("binding"), key: data.get("key"), operation: data.get("operation"), reason: data.get("reason")});};
  return <form onSubmit={submit}><h3>{subject.display_name}</h3><p className="admin-version">security v{subject.security_version}</p><label>{t("admin.binding.kind")}<select name="binding"><option value="role">role</option><option value="group">group</option></select></label><label>{t("admin.binding.operation")}<select name="operation"><option value="assign">{t("admin.binding.assign")}</option><option value="unassign">{t("admin.binding.unassign")}</option></select></label><label>{t("admin.binding.key")}<input name="key" required maxLength={128}/></label><Reason t={t}/><button disabled={busy}>{t("admin.action.apply")}</button><p className="admin-warning">{t("admin.binding.warning")}</p></form>;
}
function SourcesPanel({load, selected, setSelected, busy, onCreate, onUpdate, t}: {load: Load<ResearchSource[]>; selected: ResearchSource | null; setSelected: (id: string) => void; busy: boolean; onCreate: (payload: unknown) => Promise<void>; onUpdate: (payload: unknown) => Promise<void>; t: T}) {
  return <section><PanelTitle index="04" title={t("admin.sources.title")} body={t("admin.sources.body")}/><div className="admin-split"><Surface load={load} empty={t("admin.empty")}>{data => <div className="admin-list">{data.map(item => <button type="button" key={item.source_id} className={selected?.source_id === item.source_id ? "selected" : ""} onClick={() => setSelected(item.source_id)}><strong>{item.display_name}</strong><span>{item.stable_key}</span><small>{item.lifecycle} · {item.classification}</small></button>)}</div>}</Surface><div className="admin-editor"><SourceForm source={selected} busy={busy} onSubmit={selected ? onUpdate : onCreate} t={t}/></div></div></section>;
}
function SourceForm({source, busy, onSubmit, t}: {source: ResearchSource | null; busy: boolean; onSubmit: (payload: unknown) => Promise<void>; t: T}) {
  const submit = (event: FormEvent<HTMLFormElement>) => {event.preventDefault(); const d = new FormData(event.currentTarget); const common = {display_name: d.get("display_name"), description: d.get("description"), owner_subject_id: d.get("owner_subject_id"), classification: d.get("classification"), lifecycle: d.get("lifecycle")}; void onSubmit(source ? {...common, reason: d.get("reason")} : {...common, stable_key: d.get("stable_key"), origin: d.get("origin")});};
  return <form key={source?.source_id ?? "new"} onSubmit={submit}><h3>{source ? t("admin.sources.edit") : t("admin.sources.create")}</h3>{!source && <><label>{t("admin.sources.key")}<input name="stable_key" required pattern="[a-z0-9][a-z0-9._-]+"/></label><label>{t("admin.sources.origin")}<select name="origin"><option>manual</option><option>refinery</option><option>partner</option></select></label></>}<label>{t("admin.sources.name")}<input name="display_name" required defaultValue={source?.display_name}/></label><label>{t("admin.sources.description")}<textarea name="description" defaultValue={source?.description}/></label><label>{t("admin.sources.owner")}<input name="owner_subject_id" required defaultValue={source?.owner_subject_id}/></label><label>{t("admin.sources.classification")}<select name="classification" defaultValue={source?.classification ?? "internal"}><option>public_internal</option><option>internal</option><option>restricted</option><option>highly_restricted</option></select></label><label>{t("admin.sources.lifecycle")}<select name="lifecycle" defaultValue={source?.lifecycle ?? "active"}><option>active</option><option>suspended</option><option>retired</option></select></label>{source && <Reason t={t}/>}<button disabled={busy}>{source ? t("admin.action.apply") : t("admin.action.register")}</button></form>;
}
function SettingsPanel({load, versions, selected, setSelected, busy, onSubmit, t}: {load: Load<SettingView[]>; versions: Load<SettingVersion[]>; selected: SettingView | null; setSelected: (key: string) => void; busy: boolean; onSubmit: (payload: unknown) => Promise<void>; t: T}) {
  return <section><PanelTitle index="05" title={t("admin.settings.title")} body={t("admin.settings.body")}/><div className="admin-split"><Surface load={load} empty={t("admin.empty")}>{data => <div className="admin-list">{data.map(item => <button type="button" key={item.setting_key} className={selected?.setting_key === item.setting_key ? "selected" : ""} onClick={() => setSelected(item.setting_key)}><strong>{item.setting_key}</strong><span>{String(item.value)}</span><small>{item.value_type} · v{item.version}</small></button>)}</div>}</Surface><div className="admin-editor">{selected ? <SettingForm setting={selected} versions={versions} busy={busy} onSubmit={onSubmit} t={t}/> : <p className="surface-empty">{t("admin.select.setting")}</p>}</div></div></section>;
}
function SettingForm({setting, versions, busy, onSubmit, t}: {setting: SettingView; versions: Load<SettingVersion[]>; busy: boolean; onSubmit: (payload: unknown) => Promise<void>; t: T}) {
  const submit = (event: FormEvent<HTMLFormElement>) => {event.preventDefault(); const d = new FormData(event.currentTarget); const raw = String(d.get("value")); let next: SettingValue = raw; if (setting.value_type === "boolean") next = raw === "true"; else if (setting.value_type !== "string") next = Number(raw); void onSubmit({value: next, reason: d.get("reason")});};
  return <><form key={`${setting.setting_key}-${setting.version}`} onSubmit={submit}><h3>{setting.setting_key}</h3><p>{setting.description}</p><label>{t("admin.settings.value")}{setting.value_type === "boolean" ? <select name="value" defaultValue={String(setting.value)}><option value="true">true</option><option value="false">false</option></select> : <input name="value" required type={setting.value_type === "string" ? "text" : "number"} step={setting.value_type === "decimal" ? "any" : "1"} min={setting.minimum ?? undefined} max={setting.maximum ?? undefined} defaultValue={String(setting.value)}/>}</label><Reason t={t}/><button disabled={busy}>{t("admin.action.apply")}</button></form><div className="admin-history"><h3>{t("admin.settings.history")}</h3><Surface load={versions} empty={t("admin.empty")}>{data => <ol>{data.map(item => <li key={item.setting_id}><b>v{item.version}</b><span>{String(item.value)}</span><small>{item.reason}</small></li>)}</ol>}</Surface></div></>;
}
function GapPanel({busy, onSubmit, t}: {busy: boolean; onSubmit: (id: string, payload: unknown) => Promise<void>; t: T}) {
  const submit = (event: FormEvent<HTMLFormElement>) => {event.preventDefault(); const d = new FormData(event.currentTarget); void onSubmit(String(d.get("gap_id")), {priority: d.get("priority"), reason: d.get("reason")});};
  return <section><PanelTitle index="06" title={t("admin.gaps.title")} body={t("admin.gaps.body")}/><div className="admin-editor standalone"><form onSubmit={submit}><label>{t("admin.gaps.id")}<input name="gap_id" required pattern="[0-9a-fA-F-]{36}"/></label><label>{t("admin.gaps.priority")}<select name="priority"><option>low</option><option>normal</option><option>high</option><option>urgent</option></select></label><Reason t={t}/><button disabled={busy}>{t("admin.action.apply")}</button><p className="admin-warning">{t("admin.gaps.warning")}</p></form></div></section>;
}
function Reason({t}: {t: T}) { return <label>{t("admin.reason")}<textarea name="reason" required maxLength={2000}/><small>{t("admin.reason.help")}</small></label>; }
