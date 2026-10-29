"use client";

import {useEffect, useId, useRef, useState} from "react";
import {api, apiRoot, checkedResponse, WorkspaceApiError} from "./api";
import {parseCsv, type Artifact, type ArtifactVersion} from "./contracts";
import {Markdown} from "./Markdown";
import {FocusedDocument, TableGrid} from "./FocusedEditor";
import {boundHistory, checkText, type EditBuffers} from "./editing";

type Draft = {content: string; baseVersion: number; requestId: string; past?: string[]; future?: string[]; buffers?: EditBuffers};
const keyFor = (id: string) => `agent-workspace:artifact-draft:${id}`;
function readDraft(id: string): Draft | null {
  try {const value = JSON.parse(localStorage.getItem(keyFor(id)) ?? "null"); if (typeof value?.content !== "string" || !Number.isInteger(value.baseVersion) || typeof value?.requestId !== "string") return null; checkText(value.content); const focus = value.buffers?.focus; const buffers: EditBuffers = {}; if (typeof value.buffers?.paste === "string") {checkText(value.buffers.paste); if (value.buffers.paste) buffers.paste = value.buffers.paste;} if (focus && typeof focus.replacement === "string" && typeof focus.region?.source === "string" && Number.isSafeInteger(focus.region.start) && Number.isSafeInteger(focus.region.end)) {checkText(focus.replacement); buffers.focus = focus;} return {...value, buffers: Object.keys(buffers).length ? buffers : undefined, past: boundHistory(Array.isArray(value.past) ? value.past.filter((item: unknown) => typeof item === "string") : []), future: boundHistory(Array.isArray(value.future) ? value.future.filter((item: unknown) => typeof item === "string") : [])};} catch {return null;}
}
export function ArtifactCreator({workspaceId, kind, onCreated, onCancel}: {workspaceId: string; kind: "document" | "table"; onCreated: (item: Artifact) => Promise<void>; onCancel: () => void}) {
  const storageKey = `agent-workspace:new-draft:${workspaceId}:${kind}`;
  const [initial] = useState(() => {try {return JSON.parse(localStorage.getItem(storageKey) ?? "{}");} catch {return {};}});
  const [title, setTitle] = useState<string>(initial.title ?? "");
  const [content, setContent] = useState<string>(initial.content ?? "");
  const [error, setError] = useState(""); const [unsafe, setUnsafe] = useState(false); const [busy, setBusy] = useState(false);
  const requestId = useRef(initial.requestId ?? crypto.randomUUID()); const lock = useRef(false);
  function change(nextTitle: string, nextContent: string) {
    if (lock.current) return;
    setTitle(nextTitle); setContent(nextContent); requestId.current = crypto.randomUUID();
    try {localStorage.setItem(storageKey, JSON.stringify({title: nextTitle, content: nextContent, requestId: requestId.current})); setUnsafe(false);}
    catch {setUnsafe(true); setError("Browser draft storage is full. Copy your work before leaving.");}
  }
  useEffect(() => {
    if (!title && !content) return;
    const guard = (event: BeforeUnloadEvent) => {event.preventDefault();}; window.addEventListener("beforeunload", guard); return () => window.removeEventListener("beforeunload", guard);
  }, [title, content]);
  async function create() {
    if (lock.current || !title.trim() || !content.trim()) return;
    lock.current = true; setBusy(true); setError("");
    const submittedId = requestId.current;
    try {const item = await api<Artifact>(`/workspaces/${workspaceId}/artifacts`, {title: title.trim(), kind, content, request_id: submittedId});
      try {if (JSON.parse(localStorage.getItem(storageKey) ?? "null")?.requestId === submittedId) localStorage.removeItem(storageKey);} catch { /* A newer browser draft must not be discarded. */ }
      await onCreated(item);}
    catch (cause) {setError((cause as Error).message);} finally {lock.current = false; setBusy(false);}
  }
  return <section className="aw-artifact aw-creator" aria-label={`New ${kind}`} data-unsafe-draft={unsafe}><h3>New {kind}</h3><p className="aw-muted">Write or paste your own {kind === "table" ? "CSV data" : "Markdown text"}. No model is called. This draft stays in this browser until saved.</p><label className="aw-editor-label" htmlFor="aw-new-title">Title</label><input id="aw-new-title" value={title} maxLength={160} readOnly={busy} onChange={event => change(event.target.value, content)}/><label className="aw-editor-label" htmlFor="aw-new-content">{kind === "table" ? "CSV content" : "Markdown content"}</label><textarea id="aw-new-content" value={content} readOnly={busy} onChange={event => change(title, event.target.value)} spellCheck={false}/>{error && <p role="alert" className="aw-inline-error">{error}</p>}<div className="aw-editor-actions"><button onClick={() => void create()} disabled={busy || !title.trim() || !content.trim()}>Save first version</button><button onClick={onCancel}>Close draft</button></div></section>;
}
export function ArtifactEditor({artifact, latestVersion, onOpen, onSaved, onRevise, onConflict, allowChatRevision = true}: {artifact: Artifact; latestVersion: number; onOpen: (version: number) => void; onSaved: (artifact: Artifact) => Promise<void>; onRevise: () => void; onConflict?: () => Promise<void>; allowChatRevision?: boolean}) {
  const editorId = useId();
  const [tab, setTab] = useState("preview");
  const [mode, setMode] = useState(() => artifact.kind === "table" ? "grid" : readDraft(artifact.id)?.buffers?.focus ? "focus" : "raw");
  const [previewPage, setPreviewPage] = useState(0), [previewColumnPage, setPreviewColumnPage] = useState(0);
  const [draft, setDraft] = useState<Draft | null>(() => readDraft(artifact.id));
  const lastStored = useRef(draft?.requestId ?? null); const lastEdit = useRef<{group: string; at: number} | null>(null);
  const [versions, setVersions] = useState<ArtifactVersion[]>([]);
  const [from, setFrom] = useState(Math.max(1, artifact.version - 1));
  const [diff, setDiff] = useState("");
  const [format, setFormat] = useState(artifact.kind === "table" ? "csv" : "md");
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [unsafe, setUnsafe] = useState(false);
  const lock = useRef(false);
  const content = draft?.content ?? artifact.content ?? "";
  const dirty = !!draft;
  const stale = artifact.version !== latestVersion || !!draft && draft.baseVersion !== latestVersion;
  const draftRef = useRef(draft); useEffect(() => {draftRef.current = draft;}, [draft]);
  useEffect(() => {
    const changed = (event: StorageEvent) => {if (event.key === keyFor(artifact.id) && draftRef.current && event.newValue !== JSON.stringify(draftRef.current)) {setUnsafe(true); setError("Another tab changed this browser draft. Your work stays in this tab. Copy it before leaving; the other tab's draft was not replaced.");}};
    window.addEventListener("storage", changed); return () => window.removeEventListener("storage", changed);
  }, [artifact.id]);
  useEffect(() => {
    let disposed = false;
    void api<{items: ArtifactVersion[]}>(`/artifacts/${artifact.id}/versions`).then(result => {if (!disposed) setVersions(result.items);}).catch(cause => {if (!disposed) setError(cause.message);});
    return () => {disposed = true;};
  }, [artifact.id, artifact.version]);
  useEffect(() => {
    if (!dirty) return;
    const guard = (event: BeforeUnloadEvent) => {event.preventDefault();};
    window.addEventListener("beforeunload", guard);
    return () => window.removeEventListener("beforeunload", guard);
  }, [dirty]);
  useEffect(() => {
    if (tab !== "changes") return;
    let disposed = false;
    void api<{diff: string}>(`/artifacts/${artifact.id}/diff?from_version=${from}&to_version=${artifact.version}`).then(result => {if (!disposed) setDiff(result.diff);}).catch(cause => {if (!disposed) setError(cause.message);});
    return () => {disposed = true;};
  }, [artifact.id, artifact.version, from, tab]);
  function persist(next: Draft) {
    // Persist before changing selection or closing the panel. If browser storage
    // is full, keep the draft in memory and explicitly require safe navigation.
    try {const other = readDraft(artifact.id); if (other && other.requestId !== lastStored.current) {setUnsafe(true); setError("Another tab changed this browser draft. Your work stays in this tab. Copy it before leaving; the other tab's draft was not replaced."); setDraft(next); return;} localStorage.setItem(keyFor(artifact.id), JSON.stringify(next)); lastStored.current = next.requestId; setNotice(""); setUnsafe(false); setError("");}
    catch {setUnsafe(true); setError("Browser draft storage is full or unavailable. Keep this panel open and copy your edits before leaving. Editing again retries draft storage.");}
    setDraft(next);
  }
  function change(value: string, direction?: "undo" | "redo", group?: string, appliedBuffer = false) {
    if (lock.current || stale) return;
    try {checkText(value);} catch (cause) {setError((cause as Error).message); return;}
    const now = Date.now(), coalesce = !!group && lastEdit.current?.group === group && now - lastEdit.current.at < 600;
    lastEdit.current = group && !direction ? {group, at: now} : null;
    persist({content: value, baseVersion: draft?.baseVersion ?? artifact.version, requestId: crypto.randomUUID(), buffers: appliedBuffer ? undefined : draft?.buffers, past: direction === "undo" ? draft?.past?.slice(0, -1) : coalesce ? draft?.past : boundHistory([...(draft?.past ?? []), content]), future: direction === "redo" ? draft?.future?.slice(0, -1) : direction === "undo" ? boundHistory([...(draft?.future ?? []), content]) : []});
  }
  function buffers(value: EditBuffers) {
    if (lock.current || stale) return;
    lastEdit.current = null;
    try {checkText(value.focus?.replacement ?? ""); checkText(value.paste ?? "");} catch (cause) {setError((cause as Error).message); return;}
    const normalized = {...(value.focus ? {focus: value.focus} : {}), ...(value.paste ? {paste: value.paste} : {})};
    persist({content, baseVersion: draft?.baseVersion ?? artifact.version, requestId: crypto.randomUUID(), past: draft?.past, future: draft?.future, buffers: Object.keys(normalized).length ? normalized : undefined});
  }
  async function save() {
    if (!draft || lock.current || stale || draft.buffers) return;
    lock.current = true; setBusy(true); setError("");
    try {
      const saved = await api<Artifact>(`/artifacts/${artifact.id}/revisions`, {expected_version: draft.baseVersion, content: draft.content, request_id: draft.requestId});
      if (readDraft(artifact.id)?.requestId === draft.requestId) {localStorage.removeItem(keyFor(artifact.id)); lastStored.current = null;}
      setDraft(null); setNotice(`Saved version ${saved.version}.`);
      await onSaved(saved);
    } catch (cause) {setError((cause as Error).message); if (cause instanceof WorkspaceApiError && cause.status === 409) await onConflict?.().catch(() => {});}
    finally {lock.current = false; setBusy(false);}
  }
  async function download() {
    setError(""); setBusy(true);
    try {
      const response = await checkedResponse(await fetch(`${apiRoot}/artifacts/${artifact.id}/download?version=${artifact.version}&format=${format}`, {cache: "no-store"}));
      const blob = await response.blob(); const url = URL.createObjectURL(blob);
      const link = document.createElement("a"); link.href = url; link.download = artifact.filename.replace(/\.[^.]+$/, `.${format}`); link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice(`Downloaded saved version ${artifact.version}. Unsaved edits are not exported.`);
    } catch (cause) {setError(`Export failed. ${(cause as Error).message}`);}
    finally {setBusy(false);}
  }
  const rows = artifact.kind === "table" ? parseCsv(artifact.content ?? "") : [];
  return <section className="aw-artifact" aria-label="Artifact preview" data-unsafe-draft={unsafe}>
    <div className="aw-artifact-head"><span>{artifact.kind === "table" ? "Table · CSV" : "Document · Markdown"}</span><label>Version <select aria-label="Artifact version" value={artifact.version} onChange={event => onOpen(Number(event.target.value))}>{Array.from({length: latestVersion}, (_, i) => i + 1).map(version => <option key={version} value={version}>{version}</option>)}</select></label></div>
    <div className="aw-tabs" role="tablist" aria-label="Artifact view">{["preview", "edit", "changes"].map(value => <button key={value} id={`${editorId}-tab-${value}`} role="tab" aria-selected={tab === value} aria-controls={`${editorId}-panel`} onClick={() => setTab(value)}>{value[0].toUpperCase() + value.slice(1)}</button>)}</div>
    {dirty && <p className="aw-draft-note" role="status">Unsaved draft based on version {draft.baseVersion}. Kept in this browser when you switch or reload.</p>}
    {stale && <p className="aw-draft-note">This is not the current editable version. Version {latestVersion} is current. Your saved versions and draft are unchanged. <button onClick={() => onOpen(latestVersion)}>Open current version</button></p>}
    {error && <p className="aw-inline-error" role="alert">{error}</p>}
    {notice && <p className="aw-muted" role="status">{notice}</p>}
    <div id={`${editorId}-panel`} role="tabpanel" aria-labelledby={`${editorId}-tab-${tab}`} className="aw-artifact-content">
      {tab === "preview" && (artifact.kind === "table" ? <><div className="aw-grid-pages" aria-label="Saved table preview pages"><button disabled={previewPage === 0} onClick={() => setPreviewPage(previewPage - 1)}>Previous preview rows</button><span>Saved data rows {Math.min(1 + previewPage * 20, rows.length - 1)}–{Math.min((previewPage + 1) * 20, rows.length - 1)} of {rows.length - 1}</span><button disabled={(previewPage + 1) * 20 >= rows.length - 1} onClick={() => setPreviewPage(previewPage + 1)}>Next preview rows</button><button disabled={previewColumnPage === 0} onClick={() => setPreviewColumnPage(previewColumnPage - 1)}>Previous preview columns</button><span>Columns {previewColumnPage * 8 + 1}–{Math.min((previewColumnPage + 1) * 8, rows[0]?.length ?? 0)} of {rows[0]?.length ?? 0}</span><button disabled={(previewColumnPage + 1) * 8 >= (rows[0]?.length ?? 0)} onClick={() => setPreviewColumnPage(previewColumnPage + 1)}>Next preview columns</button></div><div className="aw-table"><table><thead><tr>{rows[0]?.slice(previewColumnPage * 8, (previewColumnPage + 1) * 8).map((cell, i) => <th key={i} scope="col">{cell}</th>)}</tr></thead><tbody>{rows.slice(1 + previewPage * 20, 1 + (previewPage + 1) * 20).map((row, i) => <tr key={i}>{row.slice(previewColumnPage * 8, (previewColumnPage + 1) * 8).map((cell, j) => <td key={j}>{cell}</td>)}</tr>)}</tbody></table></div></> : <Markdown content={artifact.content ?? ""}/>)}
      {tab === "edit" && <><div className="aw-edit-tools"><button aria-pressed={mode !== "raw"} onClick={() => setMode(artifact.kind === "table" ? "grid" : "focus")}>{artifact.kind === "table" ? "Cell grid" : "Focused edit"}</button><button aria-pressed={mode === "raw"} onClick={() => setMode("raw")}>Raw {artifact.kind === "table" ? "CSV" : "Markdown"}</button><button disabled={stale || busy || !draft?.past?.length} onClick={() => change(draft!.past!.at(-1)!, "undo")}>Undo draft</button><button disabled={stale || busy || !draft?.future?.length} onClick={() => change(draft!.future!.at(-1)!, "redo")}>Redo draft</button></div>
      {mode === "raw" ? <><label className="aw-editor-label" htmlFor={`${editorId}-text`}>Edit {artifact.kind === "table" ? "CSV" : "Markdown"} text</label><textarea id={`${editorId}-text`} value={content} readOnly={stale || busy} spellCheck={false} onChange={event => change(event.target.value, undefined, "raw")}/></> : artifact.kind === "table" ? <TableGrid content={content} disabled={stale || busy} buffers={draft?.buffers} onBuffers={buffers} onChange={(value, group, appliedBuffer) => change(value, undefined, group, appliedBuffer)} onError={setError}/> : <FocusedDocument content={content} disabled={stale || busy} buffers={draft?.buffers} onBuffers={buffers} onChange={value => change(value, undefined, undefined, true)} onError={setError}/>}
      {mode === "raw" && artifact.kind !== "table" && <details><summary>Live draft preview</summary><div className="aw-draft-preview" aria-label="Document draft preview"><Markdown content={content}/></div></details>}
      {draft?.buffers && <p className="aw-muted">Apply or clear your replacement / paste area before saving the draft.</p>}
      <div className="aw-editor-actions"><button onClick={() => void save()} disabled={!dirty || busy || stale || !!draft?.buffers}>Save new version</button>{dirty && <button disabled={busy} onClick={() => {if (window.confirm("Discard this unsaved draft? Saved versions will not change.")) {localStorage.removeItem(keyFor(artifact.id)); setDraft(null); setError("");}}}>Discard draft</button>}</div></>}
      {tab === "changes" && <><label className="aw-editor-label">Compare version <select aria-label="Compare from version" value={from} onChange={event => setFrom(Number(event.target.value))}>{Array.from({length: latestVersion}, (_, i) => i + 1).map(value => <option key={value}>{value}</option>)}</select> with version {artifact.version}</label><pre className="aw-diff">{diff || "No text changes."}</pre><details><summary>Version history ({versions.length})</summary><ul className="aw-version-history">{versions.map(item => <li key={item.version}><button onClick={() => onOpen(item.version)}>Version {item.version}</button><span>{item.characters} characters · {item.run_id ? "Agent draft" : "Manual edit"}</span></li>)}</ul></details></>}
    </div>
    <div className="aw-artifact-actions"><label className="aw-export-format">Export <select aria-label="Export format" value={format} onChange={event => setFormat(event.target.value)}>{(artifact.kind === "table" ? ["csv", "xlsx"] : ["md", "docx", "pdf"]).map(value => <option key={value} value={value}>{value.toUpperCase()}</option>)}</select></label><a href={`${apiRoot}/artifacts/${artifact.id}/download?version=${artifact.version}&format=${format}`} download aria-disabled={busy} onClick={event => {event.preventDefault(); if (!busy) void download();}}>Download</a>{allowChatRevision && <button onClick={onRevise} disabled={stale || busy}>Revise in chat</button>}</div>
    {artifact.kind === "table" && <p className="aw-muted aw-export-note">CSV export escapes formula-like cells for spreadsheet safety. Canonical draft and XLSX values are unchanged.</p>}
  </section>;
}
