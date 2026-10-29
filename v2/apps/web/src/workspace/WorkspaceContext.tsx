"use client";

import {useEffect, useRef, useState, type FormEvent} from "react";
import {api} from "./api";
import type {Artifact, SourceFile} from "./contracts";
import {artifactReference, contextIdentity, emptyContext, referenceKey, type ContextChoices, type ContextReference} from "./contextChoices";

type Brief = {revision: number; goal: string; decisions: string; remaining: string; source?: string};
type Selection = ContextReference & {label: string; content?: string; has_more?: boolean; total_characters?: number};
type ContextSnapshot = {status?: string; reason?: string; mode: string; selections: Selection[]; references: ContextReference[]; target: ContextReference | null; omissions: string[]; context_bytes: number; limit_bytes: number; digest: string; coverage: string; current_changes?: {old_file_id: string; new_file_id: string}[]; read_ledger?: {kind: string; id: string; offset?: number; end?: number}[]};
type SearchMatch = ContextReference & {label: string; snippet: string};
type Dependencies = {status: string; upstream_status?: string; dependencies: (ContextReference & {label: string; stale: boolean; replacement_id?: string})[]; stale: boolean; reasons: string[]; coverage: string};
const blankBrief = (): Brief => ({revision: 0, goal: "", decisions: "", remaining: ""});
const errorText = (error: unknown) => error instanceof Error ? error.message : "This request could not finish. Saved work is unchanged.";

export function WorkspaceContext({workspaceId, files, artifacts, choices, message, runId, archived = false, onChoices, onSourceReplaced}: {
  workspaceId: string; files: SourceFile[]; artifacts: Artifact[]; choices: ContextChoices; message: string; runId?: string; archived?: boolean;
  onChoices: (value: ContextChoices) => void; onSourceReplaced: () => void;
}) {
  const [brief, setBrief] = useState<Brief>(blankBrief);
  const [loadedBrief, setLoadedBrief] = useState<Brief | null>(null);
  const [query, setQuery] = useState("");
  const [matches, setMatches] = useState<SearchMatch[]>([]);
  const [searched, setSearched] = useState(false);
  const [searchTruncated, setSearchTruncated] = useState(false);
  const [snapshot, setSnapshot] = useState<ContextSnapshot | null>(null);
  const [snapshotBinding, setSnapshotBinding] = useState("");
  const [snapshotKind, setSnapshotKind] = useState<"preview" | "run">("preview");
  const [oldFile, setOldFile] = useState(""); const [newFile, setNewFile] = useState("");
  const [error, setError] = useState(""); const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false); const [loading, setLoading] = useState(true);
  const mounted = useRef(true); const lock = useRef(false); const previewSequence = useRef(0); const searchSequence = useRef(0);
  const briefRequest = useRef<{identity: string; requestId: string} | null>(null);
  const replacementRequest = useRef<{identity: string; requestId: string} | null>(null);
  const dirty = !!loadedBrief && (brief.goal !== loadedBrief.goal || brief.decisions !== loadedBrief.decisions || brief.remaining !== loadedBrief.remaining);
  const choicesKey = contextIdentity(choices);
  const previewBinding = `preview:${message}:${choicesKey}`;
  const displayedSnapshot = snapshotBinding === (snapshotKind === "run" ? `run:${runId}` : previewBinding) ? snapshot : null;
  const snapshotUnavailable = displayedSnapshot && (displayedSnapshot.status === "unavailable" || !Number.isFinite(displayedSnapshot.context_bytes) || !Number.isFinite(displayedSnapshot.limit_bytes) || !Array.isArray(displayedSnapshot.selections));
  useEffect(() => {
    mounted.current = true;
    void api<Brief>(`/workspaces/${workspaceId}/brief`).then(value => {if (mounted.current) {setBrief(value); setLoadedBrief(value);}})
      .catch(cause => {if (mounted.current) setError(errorText(cause));}).finally(() => {if (mounted.current) setLoading(false);});
    return () => {mounted.current = false;};
  }, [workspaceId]);
  useEffect(() => {previewSequence.current++;}, [message, choicesKey]);
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => {event.preventDefault(); event.returnValue = "";};
    window.addEventListener("beforeunload", warn); return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  function choose(reference: ContextReference) {
    const exists = choices.references.some(item => referenceKey(item) === referenceKey(reference));
    if (!exists && choices.references.length >= 20) {setError("Select at most 20 references. Clear a selection before adding another."); return;}
    onChoices({...choices, references: exists ? choices.references.filter(item => referenceKey(item) !== referenceKey(reference)) : [...choices.references, reference]});
  }
  async function saveBrief(event: FormEvent) {
    event.preventDefault(); if (lock.current || !loadedBrief) return;
    lock.current = true; setBusy(true); setError(""); setNotice("");
    const fields = {goal: brief.goal, decisions: brief.decisions, remaining: brief.remaining, expected_revision: brief.revision};
    const identity = JSON.stringify(fields);
    if (briefRequest.current?.identity !== identity) briefRequest.current = {identity, requestId: crypto.randomUUID()};
    try {
      const result = await api<Brief>(`/workspaces/${workspaceId}/brief`, {...fields, request_id: briefRequest.current.requestId});
      if (mounted.current) {setBrief(result); setLoadedBrief(result); setNotice("Project brief saved. These are your notes, not agent-verified facts."); setSnapshot(null); previewSequence.current++;}
    } catch (cause) {if (mounted.current) setError(errorText(cause));}
    finally {lock.current = false; if (mounted.current) setBusy(false);}
  }
  async function reloadBrief() {
    if (lock.current) return;
    if (dirty && !window.confirm("Discard unsaved brief edits and load the current saved brief?")) return;
    lock.current = true; setBusy(true);
    // Invalidate before dispatch so an older preview cannot win a slow reload.
    previewSequence.current++; setSnapshot(null);
    try {const result = await api<Brief>(`/workspaces/${workspaceId}/brief`); if (mounted.current) {setBrief(result); setLoadedBrief(result); setError(""); briefRequest.current = null; previewSequence.current++; setSnapshot(null);}}
    catch (cause) {if (mounted.current) setError(errorText(cause));}
    finally {lock.current = false; if (mounted.current) setBusy(false);}
  }
  async function search(event: FormEvent) {
    event.preventDefault(); if (!query.trim()) return;
    const seq = ++searchSequence.current; setError("");
    try {const result = await api<{items: SearchMatch[]; truncated: boolean}>(`/workspaces/${workspaceId}/search?q=${encodeURIComponent(query.trim())}`);
      if (mounted.current && seq === searchSequence.current) {setMatches(result.items); setSearchTruncated(result.truncated); setSearched(true);}}
    catch (cause) {if (mounted.current && seq === searchSequence.current) setError(errorText(cause));}
  }
  async function inspect(actual: boolean) {
    const seq = ++previewSequence.current; setError("");
    try {
      const value = actual && runId ? await api<ContextSnapshot>(`/runs/${runId}/context`)
        : await api<ContextSnapshot>(`/workspaces/${workspaceId}/context-preview`, {message, ...choices});
      if (mounted.current && seq === previewSequence.current) {setSnapshot(value); setSnapshotKind(actual ? "run" : "preview"); setSnapshotBinding(actual ? `run:${runId}` : previewBinding);}
    } catch (cause) {if (mounted.current && seq === previewSequence.current) setError(errorText(cause));}
  }
  async function replaceSource() {
    if (lock.current || !oldFile || !newFile || oldFile === newFile) return;
    lock.current = true; setBusy(true); setError(""); setNotice("");
    const identity = JSON.stringify([oldFile, newFile]);
    if (replacementRequest.current?.identity !== identity) replacementRequest.current = {identity, requestId: crypto.randomUUID()};
    try {
      await api(`/workspaces/${workspaceId}/source-replacements`, {old_file_id: oldFile, new_file_id: newFile, request_id: replacementRequest.current.requestId});
      if (mounted.current) {setNotice("Source replacement recorded. Both originals are retained. Related outputs may need review; no content was updated automatically."); setOldFile(""); setNewFile(""); previewSequence.current++; setSnapshot(null); onSourceReplaced();}
    } catch (cause) {if (mounted.current) setError(errorText(cause));}
    finally {lock.current = false; if (mounted.current) setBusy(false);}
  }
  const label = (reference: ContextReference) => reference.kind === "file" ? files.find(file => file.id === reference.id)?.filename ?? "Unavailable source"
    : `${artifacts.find(artifact => artifact.id === reference.id)?.title ?? "Unavailable output"} · Version ${reference.version ?? "current"}`;
  return <section className="aw-context" aria-label="Project context" data-unsafe-draft={dirty || undefined}>
    <p className="aw-muted">Choose what this request should use. Empty selection uses bounded local matching, not a full reading of the project.</p>
    {error && <p className="aw-inline-error" role="alert">{error}</p>}{notice && <p className="aw-context-notice" role="status">{notice}</p>}
    <div className="aw-context-selection"><h3>For the next request</h3>
      {choices.target && <div className="aw-context-target"><strong>Continue from {label(choices.target)}</strong><button onClick={() => onChoices({...choices, target: null, review_edits: false})}>Remove output target</button><label><input type="checkbox" checked={!!choices.review_edits} disabled={archived} onChange={event => onChoices({...choices, review_edits: event.target.checked})}/> Review agent edits before saving</label><p className="aw-muted">Optional: edits become a proposal, not a saved version. Ordinary chat and reading are unchanged.</p></div>}
      {choices.references.length ? <ul>{choices.references.map(reference => <li key={referenceKey(reference)}><span>{label(reference)}</span><button onClick={() => choose(reference)} aria-label={`Remove ${label(reference)} from context`}>×</button></li>)}</ul> : <p className="aw-muted">Automatic selection</p>}
      {(choices.references.length > 0 || choices.target) && <button className="aw-text-action" onClick={() => onChoices(emptyContext())}>Clear context choices</button>}
      <details><summary>Add project sources ({files.length}) and outputs ({artifacts.length})</summary><div className="aw-context-options">
        {files.map(file => <label key={file.id}><input type="checkbox" checked={choices.references.some(item => item.kind === "file" && item.id === file.id)} onChange={() => choose({kind: "file", id: file.id})}/><span>{file.filename}</span></label>)}
        {artifacts.map(artifact => <label key={artifact.id}><input type="checkbox" checked={choices.references.some(item => referenceKey(item) === referenceKey(artifactReference(artifact)))} onChange={() => choose(artifactReference(artifact))}/><span>{artifact.title || artifact.filename} · Version {artifact.version}</span></label>)}
        {!files.length && !artifacts.length && <p className="aw-muted">Add a source or save an output to select it here.</p>}
      </div></details>
      <div className="aw-context-actions"><button onClick={() => void inspect(false)} disabled={!message.trim() || busy}>Preview request context</button>{runId && <button onClick={() => void inspect(true)}>Inspect saved run context</button>}</div>
      {dirty && <p className="aw-muted">Unsaved brief edits are not included. Save them before previewing or sending.</p>}
    </div>
    {displayedSnapshot && snapshotUnavailable && <section className="aw-context-snapshot" aria-label="Saved run context"><h3>Saved context is unavailable</h3><p className="aw-muted">The context may have been cleared after a project brief or memory change, may not be captured yet, or may belong to an older run. Saved messages and outputs are unchanged. A missing snapshot is not proof that no source was used.</p>{displayedSnapshot.omissions?.length > 0 && <ul aria-label="Context omissions">{displayedSnapshot.omissions.map((item, index) => <li key={index}>{item}</li>)}</ul>}</section>}
    {displayedSnapshot && !snapshotUnavailable && <section className="aw-context-snapshot" aria-label={snapshotKind === "run" ? "Saved run context" : "Context preview"}><h3>{snapshotKind === "run" ? "Context used by this run" : "Request context preview"}</h3><p>{displayedSnapshot.context_bytes.toLocaleString()} / {displayedSnapshot.limit_bytes.toLocaleString()} bytes · {displayedSnapshot.mode === "explicit" ? "Selected references" : "Automatic selection"}</p><p className="aw-muted">{displayedSnapshot.coverage}. Source links do not certify semantic completeness.</p>
      <p className="aw-muted">Initial request input only. System instructions, later tool results and token counts are separate.</p>
      {!!displayedSnapshot.current_changes?.length && <div className="aw-context-notice" role="status"><strong>Sources changed after this input was captured</strong><ul>{displayedSnapshot.current_changes.map((change, index) => <li key={index}>{displayedSnapshot.selections.find(item => item.id === change.old_file_id)?.label ?? "A selected source"} has a recorded replacement: {files.find(file => file.id === change.new_file_id)?.filename ?? "new source"}.</li>)}</ul><p>This is a current annotation. The saved input and its fingerprint have not been rewritten; review the output before reuse.</p></div>}
      {!!displayedSnapshot.omissions.length && <ul className="aw-context-omissions" aria-label="Context omissions">{displayedSnapshot.omissions.map((item, index) => <li key={index}>{item}</li>)}</ul>}
      {displayedSnapshot.selections.map((item, index) => <details key={`${referenceKey(item)}:${index}`}><summary>{item.label}{item.version ? ` · Version ${item.version}` : ""}{item.has_more ? " · Excerpt only" : ""}</summary><pre>{item.content ?? "Content not included in this view."}</pre></details>)}
      {snapshotKind === "run" && <p className="aw-muted">{displayedSnapshot.read_ledger?.length ?? 0} recorded read range(s). This snapshot is not a resumable execution or a grant of permission.</p>}
      <details><summary>Context fingerprint</summary><code className="aw-context-digest">{displayedSnapshot.digest}</code></details>
    </section>}
    <form className="aw-context-search" onSubmit={search}><label htmlFor="aw-context-query">Find in this project</label><div><input id="aw-context-query" type="search" maxLength={500} value={query} onChange={event => {setQuery(event.target.value); searchSequence.current++; setSearched(false); setMatches([]);}} placeholder="Search source and output text"/><button disabled={!query.trim()}>Search project</button></div></form>
    {searched && <section aria-label="Project search results">{matches.length ? <ul className="aw-context-matches">{matches.map(match => <li key={referenceKey(match)}><strong>{match.label}{match.version ? ` · Version ${match.version}` : ""}</strong><p>{match.snippet}</p><button onClick={() => choose({kind: match.kind, id: match.id, ...(match.version ? {version: match.version} : {})})}>{choices.references.some(item => referenceKey(item) === referenceKey(match)) ? "Remove from request" : "Use for next request"}</button></li>)}</ul> : <p className="aw-muted">No local text matches. Try another word or choose a source directly.</p>}{searchTruncated && <p className="aw-muted">Results are limited. Refine your search to find more relevant matches.</p>}</section>}
    <details className="aw-project-brief"><summary>Project brief{dirty ? " · Unsaved changes" : ""}</summary><p className="aw-muted">Your editable handover. These notes are not automatically inferred or verified by the agent. Saving changes stops requests using the previous brief and clears their reusable context; saved messages and outputs remain.</p><form onSubmit={saveBrief}>
      {([ ["goal", "Goal"], ["decisions", "Decisions"], ["remaining", "Remaining work"] ] as const).map(([field, title]) => <label key={field} htmlFor={`aw-brief-${field}`}>{title}<textarea id={`aw-brief-${field}`} rows={3} maxLength={4000} disabled={loading || busy || archived} value={brief[field]} onChange={event => setBrief(value => ({...value, [field]: event.target.value}))}/></label>)}
      <div className="aw-context-actions"><button disabled={loading || busy || archived || !dirty}>Save project brief</button><button type="button" disabled={busy} onClick={() => void reloadBrief()}>Load current brief</button></div>
    </form></details>
    <details className="aw-source-replacement"><summary>Record a source replacement</summary><p className="aw-muted">Upload the new file first, then link the old and new originals. This records your choice, not a verification of either source. Existing outputs stay unchanged.</p>
      <label htmlFor="aw-old-source">Previous source<select id="aw-old-source" value={oldFile} onChange={event => setOldFile(event.target.value)} disabled={busy}><option value="">Choose previous source</option>{files.map(file => <option key={file.id} value={file.id}>{file.filename}</option>)}</select></label>
      <label htmlFor="aw-new-source">Replacement source<select id="aw-new-source" value={newFile} onChange={event => setNewFile(event.target.value)} disabled={busy}><option value="">Choose replacement source</option>{files.filter(file => file.id !== oldFile).map(file => <option key={file.id} value={file.id}>{file.filename}</option>)}</select></label>
      <button onClick={() => void replaceSource()} disabled={busy || archived || !oldFile || !newFile || oldFile === newFile}>Record replacement</button>
    </details>
  </section>;
}

export function ArtifactDependencies({artifact, refreshToken = 0}: {artifact: Artifact; refreshToken?: number}) {
  const [value, setValue] = useState<Dependencies | null>(null); const [error, setError] = useState("");
  useEffect(() => {let disposed = false;
    void api<Dependencies>(`/artifacts/${artifact.id}/dependencies?version=${artifact.version}`).then(result => {if (!disposed) {setValue(result); setError("");}}).catch(cause => {if (!disposed) setError(errorText(cause));});
    return () => {disposed = true;};
  }, [artifact.id, artifact.version, refreshToken]);
  return <section className="aw-artifact-dependencies" aria-label="Output source freshness"><h3>Source freshness</h3>{error ? <p role="status">Source links could not be loaded. Freshness is unknown.</p> : !value ? <p className="aw-muted">Loading recorded source links…</p> : <>
    <p className={value.stale ? "aw-context-notice" : "aw-muted"}>{value.status === "unknown" ? "Source lineage is unknown for this version." : value.stale ? "A recorded source or output has changed. Review before reusing this version." : value.upstream_status === "unknown" ? "Recorded links are unchanged; earlier source lineage is unknown." : "No change detected in recorded dependencies."}</p>
    {!!value.reasons.length && <ul>{value.reasons.map((reason, index) => <li key={index}>{reason}</li>)}</ul>}
    {!!value.dependencies.length && <details><summary>Recorded dependencies ({value.dependencies.length})</summary><ul>{value.dependencies.map((item, index) => <li key={`${referenceKey(item)}:${index}`}>{item.label}{item.version ? ` · Version ${item.version}` : ""}{item.stale ? " · Changed" : ""}</li>)}</ul></details>}
    <p className="aw-muted">{value.coverage || "Recorded reads are not proof of semantic completeness."}</p>
  </>}</section>;
}
