"use client";

import {useEffect, useRef, useState} from "react";
import {api} from "./api";
import type {Workspace} from "./contracts";

export type ImportPreview = {confirmation_token: string; archive_sha256: string; expires_at: number; name: string; include_memory: boolean; counts: Record<string, number>; source_workspace: {name: string}; omissions: string[]};
export type ImportedWorkspace = {workspace: Workspace; imported: true; lineage: {archive_sha256: string}; omissions: string[]};
const ZIP_LIMIT = 20 * 1024 * 1024;
type ImportPayload = {archive_base64: string; name: string; include_memory: boolean};

export function WorkspaceImporter({viewToken, onImported, onCheck}: {viewToken: number; onImported: (result: ImportedWorkspace, viewToken: number) => Promise<void>; onCheck: () => Promise<void>}) {
  const [archive, setArchive] = useState(""); const [filename, setFilename] = useState(""); const [name, setName] = useState("Imported workspace"); const [memory, setMemory] = useState(false);
  const [preview, setPreview] = useState<ImportPreview | null>(null); const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const [uncertain, setUncertain] = useState(false);
  const generation = useRef(0); const lock = useRef(false); const requestId = useRef(crypto.randomUUID()); const prepared = useRef<ImportPayload | null>(null);
  useEffect(() => () => {generation.current++;}, []);
  function invalidate() {setPreview(null); prepared.current = null; requestId.current = crypto.randomUUID(); setError(""); setUncertain(false);}
  async function select(file?: File) {
    if (!file || lock.current) return;
    invalidate(); setArchive(""); setFilename(file.name);
    if (!/\.zip$/i.test(file.name) || file.size > ZIP_LIMIT || !file.size) {setError("Choose a Workspace ZIP no larger than 20 MiB. Nothing was imported."); return;}
    const current = ++generation.current; lock.current = true; setBusy(true);
    try {
      const content = await new Promise<string>((resolve, reject) => {const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(",")[1]); reader.onerror = () => reject(new Error("The selected ZIP could not be read. Nothing was imported.")); reader.readAsDataURL(file);});
      if (current === generation.current) {setArchive(content); setName(file.name.replace(/\.zip$/i, "").slice(0, 120) || "Imported workspace");}
    } catch (cause) {if (current === generation.current) setError((cause as Error).message);} finally {lock.current = false; if (current === generation.current) setBusy(false);}
  }
  async function review() {
    if (!archive || !name.trim() || lock.current) return;
    const payload = {archive_base64: archive, name: name.trim(), include_memory: memory}; const current = generation.current; lock.current = true; setBusy(true); setError("");
    try {
      const value = await api<ImportPreview>("/imports/preview", payload);
      if (current === generation.current) {
        if (value.name !== payload.name || value.include_memory !== payload.include_memory || !value.confirmation_token || !/^[a-f0-9]{64}$/.test(value.archive_sha256)) throw new Error("The import preview did not match these choices. Nothing was imported.");
        prepared.current = payload; requestId.current = crypto.randomUUID(); setPreview(value); setUncertain(false);
      }
    } catch (cause) {if (current === generation.current) setError((cause as Error).message);} finally {lock.current = false; if (current === generation.current) setBusy(false);}
  }
  async function commit() {
    if (!preview || !prepared.current || lock.current) return;
    const current = generation.current; const expectedDigest = preview.archive_sha256; lock.current = true; setBusy(true); setError("");
    try {
      const result = await api<ImportedWorkspace>("/imports/commit", {...prepared.current, confirmation_token: preview.confirmation_token, request_id: requestId.current});
      if (result.imported !== true || result.lineage?.archive_sha256 !== expectedDigest || !result.workspace?.id) throw new Error("The import response could not be verified. Check your workspace list before importing again.");
      // Root receives the receipt even after navigation, but its view token
      // prevents a late ACK from replacing another project's current draft.
      await onImported(result, viewToken);
    } catch (cause) {if (current === generation.current) {setUncertain(true); setError(`Import was not confirmed. ${(cause as Error).message} Check your workspaces first. Retrying this confirmation keeps the same request ID and exact choices.`);}}
    finally {lock.current = false; if (current === generation.current) setBusy(false);}
  }
  return <section className="aw-controls aw-project-import" aria-label="Import workspace snapshot">
    <h3>Bring a workspace with you</h3><p className="aw-muted">Restore saved content as a new workspace. Your existing projects stay unchanged.</p>
    <details className="aw-import-choices" open={!preview} data-ready={!!preview || undefined}><summary>Change import choices</summary><form className="aw-control-form" onSubmit={event => {event.preventDefault(); void review();}}>
      <label htmlFor="aw-import-file">Workspace ZIP</label><input id="aw-import-file" type="file" accept=".zip,application/zip" disabled={busy} onChange={event => void select(event.target.files?.[0])}/>
      {filename && <p className="aw-muted">Selected: {filename}</p>}
      <label htmlFor="aw-import-name">New workspace name</label><input id="aw-import-name" maxLength={120} value={name} readOnly={busy} onChange={event => {setName(event.target.value); invalidate();}}/>
      <label className="aw-check-label"><input type="checkbox" checked={memory} disabled={busy} onChange={event => {setMemory(event.target.checked); invalidate();}}/> Include explicitly saved memory from this snapshot</label>
      <p className="aw-muted">Memory is off by default. Enable it only to restore those saved notes.</p>
      <button disabled={busy || !archive || !name.trim()} type="submit">{busy && !preview ? "Checking snapshot…" : "Preview import"}</button>
    </form></details>
    {error && <p className="aw-inline-error" role="alert">{error}</p>}
    {preview && <section className="aw-import-preview" aria-label="Snapshot import preview">
      <h3>Ready to create “{preview.name}”</h3><p>From “{preview.source_workspace.name}”. {preview.counts.files} files, {preview.counts.artifacts} outputs, {preview.counts.versions} versions and {preview.counts.messages} messages.</p>
      <p>Memory: {preview.include_memory ? `${preview.counts.memory_selected ?? preview.counts.memory} saved notes selected by you` : `off (${preview.counts.memory} saved notes omitted)`}.</p>
      <p className="aw-muted">Creates a new workspace; the original stays unchanged. Permissions and running tasks are not restored.</p>
      <div className="aw-control-actions"><button disabled={busy} onClick={() => void commit()}>{busy ? "Creating workspace…" : "Create imported workspace"}</button></div>
      <details className="aw-import-omissions"><summary>What is not restored</summary><ul>{preview.omissions.map((item,index)=><li key={index}>{item}</li>)}</ul><p className="aw-muted">This restores saved content, not a running agent. The preview expires after five minutes.</p></details>
      {uncertain && <button className="aw-text-action" disabled={busy} onClick={() => void onCheck().catch(cause => setError((cause as Error).message))}>Check workspace list</button>}
    </section>}
  </section>;
}

export function WorkspaceDetails({workspace, active, onChanged}: {workspace: Workspace; active: boolean; onChanged: (value: Workspace) => void}) {
  const [name, setName] = useState(workspace.name); const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const [notice, setNotice] = useState("");
  const generation = useRef(0); const lock = useRef(false); const pending = useRef<{request_id: string; expected_revision: number; name?: string; archived?: boolean} | null>(null);
  useEffect(() => () => {generation.current++;}, []);
  async function change(values: {name?: string; archived?: boolean}) {
    if (lock.current || !workspace.revision) return;
    const same = pending.current && pending.current.expected_revision === workspace.revision && pending.current.name === values.name && pending.current.archived === values.archived;
    const payload = same ? pending.current! : {request_id: crypto.randomUUID(), expected_revision: workspace.revision, ...values}; pending.current = payload;
    const current = generation.current; lock.current = true; setBusy(true); setError(""); setNotice("");
    try {const result = await api<Workspace>(`/workspaces/${workspace.id}/metadata`, payload); if (result.id !== workspace.id) throw new Error("The update did not match this workspace."); onChanged(result); if (current === generation.current) {setName(result.name); setNotice(values.archived === undefined ? "Workspace renamed." : values.archived ? "Workspace archived. Saved content remains available." : "Workspace restored to active projects.");}}
    catch (cause) {if (current === generation.current) setError((cause as Error).message);} finally {lock.current = false; if (current === generation.current) setBusy(false);}
  }
  return <section className="aw-controls" aria-label="Workspace details"><h3>Project details</h3><form className="aw-control-form" onSubmit={event => {event.preventDefault(); void change({name: name.trim()});}}><label htmlFor="aw-rename">Workspace name</label><input id="aw-rename" maxLength={120} value={name} readOnly={busy} onChange={event => setName(event.target.value)}/><button disabled={busy || !workspace.revision || !name.trim() || name.trim() === workspace.name}>Save workspace name</button></form><h3>{workspace.archived ? "Archived project" : "Archive project"}</h3><p className="aw-muted">Archiving organizes your project list. It does not delete files, revoke permissions or cancel work. Saved outputs remain editable; restore the workspace before sending new requests.</p>{active && <p className="aw-control-notice">Stop the active run and reconcile uncertain actions before archiving.</p>}<div className="aw-control-actions"><button disabled={busy || active || !workspace.revision} onClick={() => void change({archived: !workspace.archived})}>{workspace.archived ? "Restore workspace" : "Archive workspace"}</button></div>{error && <p className="aw-inline-error" role="alert">{error}</p>}{notice && <p role="status" className="aw-muted">{notice}</p>}</section>;
}
