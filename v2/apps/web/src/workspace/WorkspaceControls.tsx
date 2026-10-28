"use client";

import {useCallback, useEffect, useRef, useState, type FormEvent} from "react";
import {api} from "./api";

export type ControlView = "memory" | "connections" | "schedules";
type MemoryEntry = {id: string; content: string; version: number; source: "user"};
type Memories = {items: MemoryEntry[]; revision: number};
type Schedule = {id: string; message: string; due_at: number; state: "pending" | "paused" | "cancelled" | "dispatched"; version: number; run_id: string | null; error: string | null};
type ScheduleList = {clock: number; items: Schedule[]};
type Connection = {fixture: boolean; enabled: boolean; revision: number; external: boolean; tools: {name: string; effect: boolean}[]};
export type Approval = {id: string; run_id: string; workspace_id: string; status: string; tool: string; arguments: {note: string; artifact_id?: string; expected_version?: number}; args_digest: string; policy_revision: number; expires_at: number};
type Effect = {id: string; run_id: string; status: string; tool: string; arguments: {note: string}; receipt?: Record<string, unknown>; error?: string};

/** A generation belongs to a mounted workspace. Late responses never repopulate another one. */
function useLocalResource<T>(path: string, poll = false) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState("");
  const generation = useRef({value: 0, loading: 0});
  const refresh = useCallback(async (force = true) => {
    const guard = generation.current;
    if (guard.loading && !force) return;
    guard.loading++;
    const request = ++guard.value;
    try {const result = await api<T>(path); if (request === guard.value) {setData(result); setError("");}}
    catch (cause) {if (request === guard.value) setError((cause as Error).message);}
    finally {guard.loading--;}
  }, [path]);
  useEffect(() => {const guard = generation.current; let alive = true; queueMicrotask(() => {if (alive) void refresh();}); const timer = poll ? setInterval(() => void refresh(false), 1500) : undefined; return () => {alive = false; guard.value++; clearInterval(timer);};}, [refresh, poll]);
  return {data, error, refresh};
}

function ErrorNote({text}: {text: string}) {return text ? <p className="aw-inline-error" role="alert">{text}</p> : null;}

export function MemoryPanel({workspaceId}: {workspaceId: string}) {
  const path = `/workspaces/${workspaceId}/memory`;
  const {data, error: loadError, refresh} = useLocalResource<Memories>(path);
  const [content, setContent] = useState("");
  const [editing, setEditing] = useState<MemoryEntry | null>(null);
  const [removing, setRemoving] = useState<MemoryEntry | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const alive = useRef(true);
  const lock = useRef(false);
  const request = useRef<{body: string; id: string} | null>(null);
  useEffect(() => {alive.current = true; return () => {alive.current = false;};}, []);
  async function mutate(route: string, body: Record<string, unknown>, done: () => void) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(""); setNotice("");
    const key = JSON.stringify([route, body]);
    if (request.current?.body !== key) request.current = {body: key, id: crypto.randomUUID()};
    try {await api(route, {...body, request_id: request.current.id}); if (alive.current) {request.current = null; done(); await refresh();}}
    catch (cause) {if (alive.current) {setError((cause as Error).message); await refresh();}}
    finally {lock.current = false; if (alive.current) setBusy(false);}
  }
  function save(event: FormEvent) {
    event.preventDefault(); if (!content.trim()) return;
    void mutate(editing ? `${path}/${editing.id}/edit` : path, {...(editing ? {expected_version: editing.version} : {}), content}, () => {setContent(""); setEditing(null); setNotice("Memory saved for this workspace.");});
  }
  return <section className="aw-controls" aria-label="Workspace memory" data-unsafe-draft={!!content.trim() && content !== editing?.content}>
    <p className="aw-muted">Only what you choose to save. Memory belongs to this workspace, not every conversation.</p>
    <ErrorNote text={error || loadError}/>{notice && <p role="status" className="aw-control-notice">{notice}</p>}
    <form onSubmit={save} className="aw-control-form"><label htmlFor="aw-memory-content">{editing ? "Edit remembered note" : "Remembered note"}</label><textarea id="aw-memory-content" value={content} maxLength={4000} readOnly={busy} onChange={event => {if (!lock.current) setContent(event.target.value);}} placeholder="A preference or detail you want available in this workspace"/>
      <div className="aw-control-actions"><button disabled={busy || !content.trim()} type="submit">{editing ? "Save memory changes" : "Save memory"}</button>{editing && <button type="button" disabled={busy} onClick={() => {setEditing(null); setContent(""); setError("");}}>Cancel edit</button>}</div>
    </form>
    {!data && !loadError && <p role="status" className="aw-muted">Loading memory…</p>}
    {data?.items.length === 0 && <p className="aw-muted">No saved memories. Add only what should carry into later work.</p>}
    <ul className="aw-control-list" aria-label="Saved memories">{data?.items.map(item => <li key={item.id}><p className="aw-control-prose">{item.content}</p><small>User-saved · Version {item.version}</small>
      <div className="aw-control-actions"><button disabled={busy} onClick={() => {setEditing(item); setContent(item.content); setRemoving(null); setError("");}}>Edit memory</button><button disabled={busy} onClick={() => setRemoving(item)}>Delete memory</button></div>
      {removing?.id === item.id && <div className="aw-confirm" role="group" aria-label="Confirm memory deletion"><p>Delete this saved memory? Future reads will not use it. Existing messages and files are not erased.</p><div className="aw-control-actions"><button disabled={busy} onClick={() => void mutate(`${path}/${item.id}/delete`, {expected_version: item.version}, () => {setRemoving(null); if (editing?.id === item.id) {setEditing(null); setContent("");} setNotice("Memory deleted. It will not be restored from a cached note.");})}>Confirm delete memory</button><button disabled={busy} onClick={() => setRemoving(null)}>Keep memory</button></div></div>}
    </li>)}</ul>
  </section>;
}

export function ApprovalPrompt({workspaceId, runId, onResolved}: {workspaceId: string; runId: string; onResolved: () => void}) {
  const {data, error: loadError, refresh} = useLocalResource<{items: Approval[]}>(`/workspaces/${workspaceId}/approvals`, true);
  const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const lock = useRef(false); const alive = useRef(true);
  const command = useRef<{key: string; id: string} | null>(null);
  useEffect(() => {alive.current = true; return () => {alive.current = false;};}, []);
  const approval = data?.items.find(item => item.run_id === runId && item.status === "pending");
  async function resolve(decision: "approve" | "reject") {
    if (!approval || lock.current) return;
    lock.current = true; setBusy(true); setError("");
    const key = `${approval.id}:${decision}`; if (command.current?.key !== key) command.current = {key, id: crypto.randomUUID()};
    try {await api(`/approvals/${approval.id}/resolve`, {decision, request_id: command.current.id}); if (alive.current) {command.current = null; await refresh(); onResolved();}}
    catch (cause) {if (alive.current) {setError((cause as Error).message); await refresh();}}
    finally {lock.current = false; if (alive.current) setBusy(false);}
  }
  if (!approval) return loadError ? <ErrorNote text={loadError}/> : null;
  return <section className="aw-approval" aria-label="Pending action approval">
    <h2>Review a simulated action</h2><p className="aw-muted">Local fixture only. No real recipient or external account is connected.</p>
    <p className="aw-control-prose">{approval.arguments.note}</p>
    {approval.arguments.artifact_id && <p className="aw-muted">Bound to saved artifact reference, version {approval.arguments.expected_version}. Approval applies only to this exact version. File contents are not attached.</p>}
    <p className="aw-muted">Tool: {approval.tool}. Expires {new Date(approval.expires_at * 1000).toLocaleTimeString()}.</p>
    <ErrorNote text={error}/><div className="aw-control-actions"><button disabled={busy} onClick={() => void resolve("approve")}>Approve simulated action</button><button disabled={busy} onClick={() => void resolve("reject")}>Reject action</button></div>
  </section>;
}

export function ConnectionPanel({workspaceId, onPrepare}: {workspaceId: string; onPrepare: (command: string) => void}) {
  const path = `/workspaces/${workspaceId}/connection`;
  const {data, error: loadError, refresh} = useLocalResource<Connection>(path);
  const approvals = useLocalResource<{items: Approval[]}>(`/workspaces/${workspaceId}/approvals`, true);
  const effects = useLocalResource<{items: Effect[]}>(`/workspaces/${workspaceId}/effects`, true);
  const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const [notice, setNotice] = useState("");
  const lock = useRef(false); const alive = useRef(true); const command = useRef<{key: string; id: string} | null>(null);
  useEffect(() => {alive.current = true; return () => {alive.current = false;};}, []);
  async function change(route: string, body: Record<string, unknown>, message: string) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError("");
    const key = JSON.stringify([route, body]); if (command.current?.key !== key) command.current = {key, id: crypto.randomUUID()};
    try {await api(route, {...body, request_id: command.current.id}); if (alive.current) {command.current = null; setNotice(message); await Promise.all([refresh(), effects.refresh(), approvals.refresh()]);}}
    catch (cause) {if (alive.current) {setError((cause as Error).message); await refresh();}}
    finally {lock.current = false; if (alive.current) setBusy(false);}
  }
  return <section className="aw-controls" aria-label="Workspace connections">
    <h3>Local MCP fixture</h3><p className="aw-muted">A fixed local test server, not a live service. Grant once for permitted reads. Every simulated send still requires review.</p>
    <ErrorNote text={error || loadError || approvals.error || effects.error}/>{notice && <p className="aw-control-notice" role="status">{notice}</p>}
    {data && <><p className="aw-connection-state">{data.enabled ? "Permission granted for this workspace" : "Not connected"}</p><div className="aw-control-actions"><button disabled={busy} onClick={() => void change(path, {enabled: !data.enabled, expected_revision: data.revision}, data.enabled ? "Permission revoked. Pending actions cannot use the old grant." : "Local fixture permission granted.")}>{data.enabled ? "Revoke fixture permission" : "Grant fixture permission"}</button></div>
      <ul className="aw-tool-list">{data.tools.map(tool => <li key={tool.name}><strong>{tool.name}</strong><span>{tool.effect ? "Simulated action; review required" : "Read only; no repeated approval"}</span></li>)}</ul>
      {data.enabled && <div className="aw-control-actions"><button onClick={() => onPrepare("fixture:mcp-read")}>Prepare read test</button><button onClick={() => onPrepare("fixture:mcp-effect")}>Prepare action test</button></div>}</>}
    <h3>Action history</h3><ul className="aw-control-list" aria-label="Action history">{effects.data?.items.map(effect => <li key={effect.id}><p className="aw-control-prose">{effect.arguments.note}</p><p className="aw-effect-state">{effect.status === "completed" ? "Receipt confirmed" : effect.status === "uncertain" ? "Outcome unknown; reconcile before doing anything else" : "Dispatch recorded"}</p>{effect.error && <p className="aw-muted">{effect.error.replaceAll("_", " ")}</p>}{effect.receipt && <p className="aw-muted">A receipt is saved for this simulated action.</p>}{effect.status === "uncertain" && <button className="aw-text-action" disabled={busy} onClick={() => void change(`/effects/${effect.id}/reconcile`, {}, "Receipt lookup complete. No action was replayed.")}>Reconcile receipt</button>}</li>)}</ul>
    {effects.data?.items.length === 0 && <p className="aw-muted">No simulated actions have been dispatched.</p>}
    {!!approvals.data?.items.length && <details className="aw-approval-history"><summary>Approval history</summary><ul className="aw-control-list">{approvals.data.items.map(item => <li key={item.id}><p>{item.arguments.note}</p><small>{item.status.replaceAll("_", " ")}</small></li>)}</ul></details>}
  </section>;
}

export function SchedulePanel({workspaceId, onDispatched}: {workspaceId: string; onDispatched: () => void}) {
  const path = `/workspaces/${workspaceId}/schedules`;
  const {data, error: loadError, refresh} = useLocalResource<ScheduleList>(path);
  const [message, setMessage] = useState(""); const [due, setDue] = useState("60"); const [target, setTarget] = useState("60");
  const [busy, setBusy] = useState(false); const [error, setError] = useState(""); const [notice, setNotice] = useState("");
  const lock = useRef(false); const alive = useRef(true); const command = useRef<{key: string; id: string} | null>(null);
  useEffect(() => {alive.current = true; return () => {alive.current = false;};}, []);
  async function mutate(route: string, body: Record<string, unknown>, done: () => void) {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(""); setNotice("");
    const key = JSON.stringify([route, body]); if (command.current?.key !== key) command.current = {key, id: crypto.randomUUID()};
    try {const result = await api<{blocked?: {id: string; error: string}[]}>(route, {...body, request_id: command.current.id}); if (alive.current) {command.current = null; done(); if (result.blocked?.length) setNotice("A due task could not start. It remains pending; check its status before advancing again."); await refresh(); onDispatched();}}
    catch (cause) {if (alive.current) {setError((cause as Error).message); await refresh();}}
    finally {lock.current = false; if (alive.current) setBusy(false);}
  }
  return <section className="aw-controls" aria-label="Workspace schedules" data-unsafe-draft={!!message.trim()}>
    <p className="aw-muted">Manual-clock simulation only. Nothing runs in the background or at a real-world time.</p><p className="aw-clock" role="status">Simulation clock: {data?.clock ?? 0} s</p>
    <ErrorNote text={error || loadError}/>{notice && <p className="aw-control-notice" role="status">{notice}</p>}
    <form className="aw-control-form" onSubmit={event => {event.preventDefault(); if (message.trim()) void mutate(path, {message: message.trim(), due_at: Number(due)}, () => {setMessage(""); setNotice("One-time task saved. Advance the simulation clock to make it due.");});}}>
      <label htmlFor="aw-schedule-message">One-time task</label><textarea id="aw-schedule-message" maxLength={16000} value={message} readOnly={busy} onChange={event => {if (!lock.current) setMessage(event.target.value);}} placeholder="For local testing: fixture:chat"/>
      <label htmlFor="aw-schedule-due">Due at simulation second</label><input id="aw-schedule-due" type="number" min={0} max={31536000} step="any" value={due} readOnly={busy} onChange={event => setDue(event.target.value)}/>
      <div className="aw-control-actions"><button type="submit" disabled={busy || !message.trim() || !due || !Number.isFinite(Number(due)) || Number(due) < 0 || Number(due) > 31536000}>Save one-time task</button></div>
    </form>
    <form className="aw-control-form aw-clock-form" onSubmit={event => {event.preventDefault(); void mutate(`/workspaces/${workspaceId}/clock/tick`, {target: Number(target)}, () => setNotice("Simulation clock advanced. Each eligible task is claimed once."));}}><label htmlFor="aw-clock-target">Advance clock to second</label><div><input id="aw-clock-target" type="number" min={data?.clock ?? 0} max={31536000} step="any" readOnly={busy} value={target} onChange={event => setTarget(event.target.value)}/><button disabled={busy || !target || !Number.isFinite(Number(target)) || Number(target) < (data?.clock ?? 0) || Number(target) > 31536000}>Advance simulation clock</button></div></form>
    <ul className="aw-control-list" aria-label="Scheduled tasks">{data?.items.map(item => <li key={item.id}><p className="aw-control-prose">{item.message}</p><small>Due at {item.due_at} s · {item.state}</small>{item.error && <p className="aw-muted">{item.error === "workspace_busy" ? "Waiting: another run is active. Advance the clock again after it finishes." : item.error.replaceAll("_", " ")}</p>}{item.run_id && <p className="aw-muted">Saved run created. No repeat dispatch on the next tick.</p>}
      <div className="aw-control-actions">{item.state === "pending" && <button disabled={busy} onClick={() => void mutate(`${path}/${item.id}/action`, {action: "pause", expected_version: item.version}, () => setNotice("Task paused."))}>Pause task</button>}{item.state === "paused" && <button disabled={busy} onClick={() => void mutate(`${path}/${item.id}/action`, {action: "resume", expected_version: item.version}, () => setNotice("Task resumed. It still needs a manual clock advance."))}>Resume task</button>}{["pending", "paused"].includes(item.state) && <button disabled={busy} onClick={() => void mutate(`${path}/${item.id}/action`, {action: "cancel", expected_version: item.version}, () => setNotice("Task cancelled. It will not dispatch."))}>Cancel task</button>}</div></li>)}</ul>
    {data?.items.length === 0 && <p className="aw-muted">No scheduled tasks. Create a one-time local test above.</p>}
  </section>;
}
