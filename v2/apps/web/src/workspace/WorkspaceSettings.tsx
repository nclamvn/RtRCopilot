"use client";

import {useEffect, useRef, useState} from "react";
import {api, apiRoot, checkedResponse} from "./api";
import type {Availability, Workspace} from "./contracts";

export type Readiness = Availability & {provider: {configured: boolean; endpoint: string | null; external_processing: boolean; storage: boolean; transport: string; requires_restart: boolean}; setup_command: string; capabilities?: Record<string, unknown>};
export type DeletePreview = {workspace_id: string; name: string; confirmation_token: string; artifact_ids?: string[]; counts: Record<string, number>; blocked_reason: string | null; retained: string[]};
export type DeletedWorkspace = {deleted: true; workspace_id: string; retained: string[]};

// Exact workspace keys only. Legacy artifact drafts have no workspace metadata,
// so the owner-checked server preview supplies their artifact IDs.
export function clearWorkspaceBrowserData(workspaceId: string, artifactIds: string[]) {
  localStorage.removeItem(`agent-workspace:run:${workspaceId}`);
  if (localStorage.getItem("agent-workspace:selected") === workspaceId) localStorage.removeItem("agent-workspace:selected");
  for (const kind of ["document", "table"]) localStorage.removeItem(`agent-workspace:new-draft:${workspaceId}:${kind}`);
  for (const id of artifactIds) localStorage.removeItem(`agent-workspace:artifact-draft:${id}`);
}

export function ModelSetup({onReadiness}: {onReadiness: (value: Availability) => void}) {
  const [readiness, setReadiness] = useState<Readiness | null>(null);
  const [error, setError] = useState(""); const [notice, setNotice] = useState("");
  const generation = useRef(0);
  async function refresh() {
    const current = ++generation.current; setError("");
    try {const result = await api<Readiness>("/readiness"); if (current === generation.current) {setReadiness(result); onReadiness(result);}}
    catch (cause) {if (current === generation.current) setError((cause as Error).message);}
  }
  useEffect(() => {let mounted = true; queueMicrotask(() => {if (mounted) void refresh();}); return () => {mounted = false; generation.current++;};}, []); // eslint-disable-line react-hooks/exhaustive-deps
  return <section className="aw-controls aw-settings" aria-label="Model setup">
    <h3>{readiness?.test_mode ? "Simulation, not a live AI" : readiness?.available ? "Model ready" : "Set up your local agent"}</h3>
    <p className="aw-muted">Readiness checks configuration only. They do not contact a provider or certify answer quality.</p>
    {error && <p className="aw-inline-error" role="alert">{error}</p>}
    {readiness && <><dl className="aw-settings-facts"><div><dt>Mode</dt><dd>{readiness.test_mode ? "Deterministic local simulation" : "Real model"}</dd></div><div><dt>Model</dt><dd>{readiness.model ?? "Not configured"}</dd></div><div><dt>Endpoint</dt><dd>{readiness.provider.endpoint ?? "Not configured"}</dd></div><div><dt>Credentials</dt><dd>{readiness.provider.configured ? "Configured on the server" : "Missing or incomplete"}</dd></div><div><dt>External processing</dt><dd>{readiness.provider.external_processing ? "Explicitly enabled" : "Not enabled"}</dd></div><div><dt>Provider storage</dt><dd>{readiness.provider.storage ? "Enabled" : "Disabled by the application"}</dd></div></dl>
      {readiness.test_mode && <p className="aw-control-notice">Fixture commands test the software. They are not real AI responses or evidence of AI quality.</p>}
      {!readiness.available && <p className="aw-control-notice">{readiness.reason ?? "The model is not ready."} {readiness.recovery}</p>}
      <h3>Configure in your terminal</h3><p className="aw-muted">Run this from the repository’s v2/apps/workspace directory after installing its local environment. The local CLI asks for the key privately. Never paste a key into chat or this browser. Changing a profile requires draining active work and restarting the local runtime.</p>
      <pre className="aw-setup-command">{readiness.setup_command}</pre><button className="aw-text-action" onClick={() => {void navigator.clipboard.writeText(readiness.setup_command).then(() => setNotice("Command copied. Run it in your local terminal."), () => setNotice("Copy the displayed command into your local terminal."));}}>Copy setup command</button>
    </>}
    <div className="aw-control-actions"><button onClick={() => void refresh()}>Check readiness again</button></div>{notice && <p className="aw-muted" role="status">{notice}</p>}
  </section>;
}

export function WorkspaceData({workspace, active, onDeleted, onRecover}: {workspace: Workspace; active: boolean; onDeleted: (result: DeletedWorkspace, artifactIds: string[]) => Promise<void>; onRecover: () => void}) {
  const [preview, setPreview] = useState<DeletePreview | null>(null);
  const [confirmName, setConfirmName] = useState(""); const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const [notice, setNotice] = useState("");
  const generation = useRef(0); const lock = useRef(false); const requestId = useRef(crypto.randomUUID());
  useEffect(() => () => {generation.current++;}, []);
  async function download() {
    if (lock.current) return; const current = generation.current; lock.current = true; setBusy(true); setError("");
    try {
      const response = await checkedResponse(await fetch(`${apiRoot}/workspaces/${workspace.id}/export`, {cache: "no-store"}));
      const blob = await response.blob(); if (current !== generation.current) return;
      const url = URL.createObjectURL(blob); const link = document.createElement("a"); link.href = url; link.download = `workspace-${workspace.id}.zip`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000);
      setNotice("Downloaded a consistent snapshot of saved data. Unsaved browser drafts are not included.");
    } catch (cause) {if (current === generation.current) setError((cause as Error).message);} finally {lock.current = false; if (current === generation.current) setBusy(false);}
  }
  async function prepare() {
    if (lock.current) return; const current = generation.current; lock.current = true; setBusy(true); setError("");
    try {const result = await api<DeletePreview>(`/workspaces/${workspace.id}/delete-preview`); if (current === generation.current) {if (result.workspace_id !== workspace.id || result.name !== workspace.name) throw new Error("The deletion preview does not match this workspace. Nothing was requested for deletion."); setPreview(result); setConfirmName(""); requestId.current = crypto.randomUUID();}}
    catch (cause) {if (current === generation.current) setError((cause as Error).message);} finally {lock.current = false; if (current === generation.current) setBusy(false);}
  }
  async function remove() {
    if (!preview || confirmName !== preview.name || preview.blocked_reason || active || lock.current) return;
    const current = generation.current; lock.current = true; setBusy(true); setError("");
    try {const result = await api<DeletedWorkspace>(`/workspaces/${workspace.id}/delete`, {confirm_name: confirmName, confirmation_token: preview.confirmation_token, request_id: requestId.current});
      // Cleanup and root fencing still run after navigation: a late ACK must not
      // leave deleted private drafts behind or replace another selected workspace.
      if (result.deleted && result.workspace_id === workspace.id) await onDeleted(result, preview.artifact_ids ?? []);
    } catch (cause) {if (current === generation.current) setError(`Deletion was not confirmed. ${(cause as Error).message} Reconnect to check whether the workspace still exists; a repeated confirmation keeps the same request ID.`);} finally {lock.current = false; if (current === generation.current) setBusy(false);}
  }
  const blocked = active || !!preview?.blocked_reason;
  return <section className="aw-controls aw-settings" aria-label="Workspace data">
    <h3>Your saved data</h3><p className="aw-muted">Export source originals, artifact versions, conversation and saved memory as a ZIP with a manifest. Credentials and session secrets are excluded.</p>
    <div className="aw-control-actions"><button disabled={busy} onClick={() => void download()}>Download workspace ZIP</button></div>
    {notice && <p className="aw-muted" role="status">{notice}</p>}{error && <p className="aw-inline-error" role="alert">{error}</p>}
    <div className="aw-data-danger"><h3>Delete this workspace</h3><p className="aw-muted">Permanently remove application data for “{workspace.name}”. Other workspaces stay unchanged. Download an export first if you need a copy.</p>
      {!preview && <button className="aw-text-action" disabled={busy} onClick={() => void prepare()}>Review workspace deletion</button>}
      {preview && <div aria-label="Confirm workspace deletion" className="aw-confirm">
        <p>This removes {Object.entries(preview.counts).map(([kind, count]) => `${count} ${kind}`).join(", ")}.</p>
        <p>Not erased: {preview.retained.join(", ")}. This is not a forensic or provider-erasure guarantee.</p>
        {blocked ? <><p role="status">Deletion is blocked while a run is active or an action outcome is unsettled. Stop the run and reconcile any uncertain receipt before reviewing deletion again.</p><div className="aw-control-actions"><button onClick={onRecover}>Review activity and recovery</button></div></> : <><label className="aw-editor-label" htmlFor="aw-delete-name">Type {preview.name} to confirm</label><input id="aw-delete-name" autoComplete="off" value={confirmName} readOnly={busy} onChange={event => setConfirmName(event.target.value)}/><div className="aw-control-actions"><button disabled={busy || confirmName !== preview.name} onClick={() => void remove()}>Permanently delete workspace</button></div></>}
        <button className="aw-text-action" disabled={busy} onClick={() => void prepare()}>Refresh deletion preview</button>{" · "}
        <button className="aw-text-action" disabled={busy} onClick={() => {setPreview(null); setConfirmName("");}}>Keep workspace</button>
      </div>}
    </div>
  </section>;
}
