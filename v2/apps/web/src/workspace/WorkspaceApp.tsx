"use client";

import {useCallback, useEffect, useRef, useState, type FormEvent} from "react";
import {applyEvent, terminal, uploadError, type Artifact, type Availability, type LiveState, type Message, type Run, type SourceFile, type Workspace, type WorkspaceEvent} from "./contracts";
import {Markdown} from "./Markdown";
import {api, apiRoot} from "./api";
import {ArtifactCreator, ArtifactEditor} from "./ArtifactEditor";
import {LocalResearch, SourcePreview} from "./Sources";
import {ApprovalPrompt, ConnectionPanel, MemoryPanel, SchedulePanel, type ControlView} from "./WorkspaceControls";
import {clearWorkspaceBrowserData, ModelSetup, WorkspaceData, type DeletedWorkspace} from "./WorkspaceSettings";
import {WorkspaceDetails, WorkspaceImporter, type ImportedWorkspace} from "./WorkspaceProjects";
import {ComposerDrafts} from "./composerDrafts";
import {ArtifactDependencies, WorkspaceContext} from "./WorkspaceContext";
import {artifactReference, contextIdentity, emptyContext, WorkspaceContextChoices, type ContextChoices} from "./contextChoices";
import "./workspace.css";
import "./project-continuity.css";
import "./context.css";

const freshLive = (): LiveState => ({cursor: 0, content: "", state: "queued", activities: []});
function storeRun(workspaceId: string, runId?: string) {try {if (runId) localStorage.setItem(`agent-workspace:run:${workspaceId}`, runId); else localStorage.removeItem(`agent-workspace:run:${workspaceId}`);} catch { /* Server history remains the recovery source. */ }}
function safeNavigate() {if (document.querySelector('[data-draft-clear-failed="true"]')) return window.confirm("Browser storage could not clear an older draft. It may reappear after reload. Retry saving before leaving, or leave anyway?"); return !document.querySelector('[data-unsafe-draft="true"]') || window.confirm("This unsaved draft is not stored. Copy it before leaving. Leave and discard these unsaved edits?");}
type UploadItem = {filename: string; status: "queued" | "saved" | "error"; detail?: string};
function fileBase64(file: File): Promise<string> {
  return new Promise((resolve, reject) => {const reader = new FileReader(); reader.onload = () => resolve(String(reader.result).split(",")[1]); reader.onerror = () => reject(new Error("This file could not be read.")); reader.readAsDataURL(file);});
}

export function WorkspaceApp() {
  const [workspaces, setWorkspaces] = useState<Workspace[]>([]);
  const [selected, setSelected] = useState<Workspace | null>(null);
  const [availability, setAvailability] = useState<Availability | null>(null);
  const [messages, setMessages] = useState<Message[]>([]);
  const [files, setFiles] = useState<SourceFile[]>([]);
  const [artifacts, setArtifacts] = useState<Artifact[]>([]);
  const [artifact, setArtifact] = useState<Artifact | null>(null);
  const [draft, setDraft] = useState("");
  const [draftStored, setDraftStored] = useState(true);
  const [contextChoices, setContextChoices] = useState<ContextChoices>(emptyContext);
  const [contextStored, setContextStored] = useState(true);
  const [sourceRefreshToken, setSourceRefreshToken] = useState(0);
  const [workspaceQuery, setWorkspaceQuery] = useState("");
  const [workspaceFilter, setWorkspaceFilter] = useState<"active" | "archived">("active");
  const [importViewToken, setImportViewToken] = useState(0);
  const [name, setName] = useState("");
  const [creating, setCreating] = useState(false);
  const [loading, setLoading] = useState(true);
  const [sending, setSending] = useState(false);
  const [sendingWorkspace, setSendingWorkspace] = useState<string | null>(null);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [connection, setConnection] = useState("");
  const [run, setRun] = useState<Run | null>(null);
  const [live, setLive] = useState<LiveState>(freshLive);
  const [panel, setPanel] = useState(false);
  const [panelView, setPanelView] = useState<"outputs" | "source" | "research" | "setup" | "data" | "import" | "details" | "context" | ControlView>("outputs");
  const [source, setSource] = useState<SourceFile | null>(null);
  const [uploadQueue, setUploadQueue] = useState<UploadItem[]>([]);
  const [newKind, setNewKind] = useState<"document" | "table" | null>(null);
  const [navigation, setNavigation] = useState(false);
  const liveRef = useRef(live);
  const sendLock = useRef(false);
  const uploadLock = useRef(false);
  const pendingCommand = useRef<{workspaceId: string; text: string; contextKey: string; requestId: string} | null>(null);
  const uploadInput = useRef<HTMLInputElement>(null);
  const transcript = useRef<HTMLDivElement>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const nearBottom = useRef(true);
  const selection = useRef("");
  const artifactRequest = useRef(0);
  const deletedWorkspaces = useRef(new Set<string>());
  const composerDrafts = useRef(new ComposerDrafts());
  const projectContexts = useRef(new WorkspaceContextChoices());
  const viewGeneration = useRef(0);
  const active = !!run && !terminal(run.state);
  const sendingCurrent = sending && sendingWorkspace === selected?.id;

  function writeDraft(content: string, workspaceId = selection.current) {
    if (!workspaceId || deletedWorkspaces.current.has(workspaceId)) return 0;
    const value = composerDrafts.current.write(workspaceId, content);
    if (selection.current === workspaceId) {setDraft(value.draft.content); setDraftStored(value.stored);}
    return value.draft.revision;
  }
  function changeContext(value: ContextChoices, workspaceId = selection.current) {
    if (!workspaceId || deletedWorkspaces.current.has(workspaceId)) return;
    const stored = projectContexts.current.save(workspaceId, value);
    if (selection.current === workspaceId) {setContextChoices(value); setContextStored(stored);}
  }

  const refresh = useCallback(async (workspaceId: string) => {
    const [history, sources, outputs] = await Promise.all([
      api<{items: Message[]}>(`/workspaces/${workspaceId}/messages`), api<{items: SourceFile[]}>(`/workspaces/${workspaceId}/files`), api<{items: Artifact[]}>(`/workspaces/${workspaceId}/artifacts`),
    ]);
    if (selection.current !== workspaceId || deletedWorkspaces.current.has(workspaceId)) return;
    setMessages(history.items); setFiles(sources.items); setArtifacts(outputs.items);
    return history.items;
  }, []);

  const choose = useCallback(async (workspace: Workspace) => {
    if (deletedWorkspaces.current.has(workspace.id) || !safeNavigate()) return;
    viewGeneration.current++;
    artifactRequest.current++;
    selection.current = workspace.id;
    setSelected(workspace); setMessages([]); setFiles([]); setArtifacts([]); setArtifact(null); setNewKind(null); setSource(null); setUploadQueue([]); setPanelView("outputs"); setRun(null); setLive(freshLive()); liveRef.current = freshLive(); setError(""); setNavigation(false);
    const savedDraft = composerDrafts.current.load(workspace.id); setDraft(savedDraft.draft.content); setDraftStored(savedDraft.stored);
    setContextChoices(projectContexts.current.load(workspace.id)); setContextStored(projectContexts.current.isStored(workspace.id));
    try {localStorage.setItem("agent-workspace:selected", workspace.id);} catch { /* Selection can still be changed without browser storage. */ }
    try {
      const history = await refresh(workspace.id);
      const lastRun = history?.at(-1)?.run_id;
      let pending = lastRun; try {pending = localStorage.getItem(`agent-workspace:run:${workspace.id}`) ?? lastRun;} catch { /* Recover from saved server history instead. */ }
      if (pending) {
        const snapshot = await api<Run>(`/runs/${pending}`);
        if (selection.current === workspace.id) setRun(snapshot);
      }
    } catch (cause) {if (selection.current === workspace.id) setError(String((cause as Error).message));}
  }, [refresh]);

  const connect = useCallback(async () => {
    setLoading(true); setError("");
    try {
      await api("/session", {});
      const [status, spaces] = await Promise.all([api<Availability>("/status"), api<{items: Workspace[]}>("/workspaces?include_archived=true")]);
      setAvailability(status); setWorkspaces(spaces.items);
      let previous: string | null = null; try {previous = localStorage.getItem("agent-workspace:selected");} catch { /* Storage is optional for connecting. */ }
      const next = spaces.items.find(item => item.id === previous) ?? spaces.items.find(item => !item.archived) ?? spaces.items[0];
      if (next?.archived) setWorkspaceFilter("archived");
      if (next) await choose(next);
    } catch (cause) {setError((cause as Error).message);}
    finally {setLoading(false);}
  }, [choose]);

  useEffect(() => {let mounted = true; queueMicrotask(() => {if (mounted) void connect();}); return () => {mounted = false;};}, [connect]);
  useEffect(() => {liveRef.current = live;}, [live]);
  useEffect(() => {
    if (draftStored) return;
    const guard = (event: BeforeUnloadEvent) => {event.preventDefault(); event.returnValue = "";};
    window.addEventListener("beforeunload", guard); return () => window.removeEventListener("beforeunload", guard);
  }, [draftStored]);
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {if (event.key === "Escape" && safeNavigate()) {viewGeneration.current++; setPanel(false); setNavigation(false); composer.current?.focus();}};
    window.addEventListener("keydown", escape);
    return () => window.removeEventListener("keydown", escape);
  }, []);
  useEffect(() => {
    if (nearBottom.current) transcript.current?.scrollTo({top: transcript.current.scrollHeight, behavior: "instant"});
  }, [messages, live.content, live.activities]);

  useEffect(() => {
    if (!run?.id || terminal(run.state) || !selected) return;
    let disposed = false; let stream: EventSource | undefined; let retry: ReturnType<typeof setTimeout>;
    const runId = run.id; const workspaceId = selected.id;
    const reconcile = async () => {
      const snapshot = await api<Run>(`/runs/${runId}`);
      if (disposed) return;
      setRun(snapshot);
      if (terminal(snapshot.state)) {
        await refresh(workspaceId);
        storeRun(workspaceId);
        setConnection(""); return true;
      }
      return false;
    };
    const subscribe = () => {
      if (disposed) return;
      stream = new EventSource(`${apiRoot}/runs/${runId}/events?after=${liveRef.current.cursor}`);
      stream.onopen = () => {if (!disposed) setConnection("");};
      stream.addEventListener("workspace", (raw: MessageEvent) => {
        if (disposed) return;
        try {
          const event = JSON.parse(raw.data) as WorkspaceEvent;
          if (event.run_id !== runId) return;
          const next = applyEvent(liveRef.current, event); liveRef.current = next; setLive(next);
          if (event.type === "artifact.published") {
            void refresh(workspaceId);
            const artifactId = String(event.data.artifact_id);
            void api<Artifact>(`/artifacts/${artifactId}`).then(result => {if (selection.current === workspaceId && !document.querySelector('[data-unsafe-draft="true"]')) {setArtifact(result); setPanelView("outputs"); setPanel(true);}}).catch(() => {});
          }
          if (terminal(next.state)) {stream?.close(); void reconcile().catch(cause => setError(cause.message));}
        } catch {setError("A live update was unreadable. Reconnect to recover the saved run."); stream?.close();}
      });
      stream.onerror = () => {
        stream?.close(); if (disposed) return;
        setConnection("Reconnecting to the saved run…");
        retry = setTimeout(() => {void reconcile().then(done => {if (!done) subscribe();}).catch(() => {if (!disposed) {setConnection("Connection interrupted. Your run has not been submitted again."); retry = setTimeout(subscribe, 2000);}});}, 1000);
      };
    };
    subscribe();
    return () => {disposed = true; stream?.close(); clearTimeout(retry);};
  }, [run?.id, run?.state, selected, refresh]);

  async function create(event: FormEvent) {
    event.preventDefault(); if (!name.trim()) return;
    try {const item = await api<Workspace>("/workspaces", {name: name.trim()}); setWorkspaces(previous => [...previous, item]); setCreating(false); setName(""); await choose(item); composer.current?.focus();}
    catch (cause) {setError((cause as Error).message);}
  }
  async function submit(event: FormEvent) {
    event.preventDefault(); if (!selected || selected.archived || !draft.trim() || active || sendLock.current || !availability?.available) return;
    const text = draft.trim(); const workspaceId = selected.id;
    const knownRuns = new Set(messages.map(item => item.run_id).filter(Boolean));
    const submittedContext = contextChoices; const contextKey = contextIdentity(submittedContext);
    const previous = pendingCommand.current;
    const requestId = previous?.workspaceId === workspaceId && previous.text === text && previous.contextKey === contextKey ? previous.requestId : crypto.randomUUID();
    pendingCommand.current = {workspaceId, text, contextKey, requestId};
    sendLock.current = true; setSending(true); setSendingWorkspace(workspaceId); const clearedRevision = writeDraft("", workspaceId); setError(""); nearBottom.current = true;
    setMessages(previous => [...previous, {id: requestId, role: "user", content: text}]);
    setLive(freshLive()); liveRef.current = freshLive();
    try {
      const result = await api<{run_id: string; state: string}>("/runs", {workspace_id: workspaceId, message: text, client_request_id: requestId, context: submittedContext});
      if (deletedWorkspaces.current.has(workspaceId)) return;
      storeRun(workspaceId, result.run_id);
      pendingCommand.current = null;
      if (terminal(result.state)) {
        const snapshot = await api<Run>(`/runs/${result.run_id}`);
        await refresh(workspaceId);
        if (selection.current === workspaceId) setRun(snapshot);
        storeRun(workspaceId);
      } else if (selection.current === workspaceId) setRun({id: result.run_id, state: result.state, cancel_requested: false});
    } catch (cause) {
      // A lost POST response is ambiguous. Reconcile saved history first; manual
      // retry of the same text retains its idempotency key instead of a new run.
      try {
        const history = await refresh(workspaceId);
        const last = history?.toReversed().find(item => item.role === "user" && item.content === text && item.run_id && !knownRuns.has(item.run_id));
        if (last?.run_id) {
          const savedContext = await api<ContextChoices & {request_context?: ContextChoices}>(`/runs/${last.run_id}/context`);
          if (contextIdentity(savedContext.request_context ?? savedContext) !== contextKey) throw new Error("A saved request used different context choices. Review it before sending another request.");
          const recovered = await api<Run>(`/runs/${last.run_id}`);
          if (selection.current === workspaceId) setRun(recovered);
          if (!deletedWorkspaces.current.has(workspaceId)) storeRun(workspaceId, last.run_id);
          pendingCommand.current = null;
          return;
        }
      } catch { /* Keep the original uncertainty visible. */ }
      if (!deletedWorkspaces.current.has(workspaceId) && composerDrafts.current.revision(workspaceId) === clearedRevision) writeDraft(text, workspaceId);
      if (selection.current === workspaceId && !deletedWorkspaces.current.has(workspaceId)) {
        setError(`${(cause as Error).message} Sending was not confirmed. Reconnect to check saved work, or retry this same message safely.`);
        setMessages(previous => previous.filter(item => item.id !== requestId));
      }
    }
    finally {sendLock.current = false; setSending(false); setSendingWorkspace(null); if (selection.current === workspaceId) composer.current?.focus();}
  }
  async function upload(incoming: File[]) {
    if (!selected || uploadLock.current) return;
    const workspaceId = selected.id; const valid: {file: File; index: number}[] = []; let total = 0;
    const queue = incoming.map((file, index): UploadItem => {
      const invalid = uploadError(file.name, file.size) ?? (index >= 10 ? "Choose no more than 10 files per batch." : total + file.size > 1000000 ? "A batch can contain at most 1,000,000 bytes." : null);
      if (invalid) return {filename: file.name, status: "error", detail: invalid};
      total += file.size; valid.push({file, index}); return {filename: file.name, status: "queued"};
    });
    setUploadQueue(queue); if (!valid.length) {setError(queue[0]?.detail ?? "No supported files selected."); return;}
    uploadLock.current = true; setUploading(true); setError("");
    try {
      const payload = await Promise.all(valid.map(async ({file}) => ({filename: file.name, content_base64: await fileBase64(file), media_type: file.type || "application/octet-stream"})));
      const result = await api<{accepted: SourceFile[]; errors: {index: number; filename: string; error: string}[]}>(`/workspaces/${workspaceId}/files/batch`, {files: payload});
      if (selection.current === workspaceId) {
        const next = [...queue]; valid.forEach(({index}, localIndex) => {const failure = result.errors.find(item => item.index === localIndex); next[index] = {...next[index], status: failure ? "error" : "saved", detail: failure?.error.replaceAll("_", " ")};}); setUploadQueue(next);
        await refresh(workspaceId);
      }
    } catch (cause) {if (selection.current === workspaceId) {setUploadQueue(queue.map(item => item.status === "queued" ? {...item, status: "error", detail: (cause as Error).message} : item)); setError((cause as Error).message);}}
    finally {uploadLock.current = false; setUploading(false); if (uploadInput.current) uploadInput.current.value = "";}
  }
  async function stop() {
    if (!run) return;
    const workspaceId = selection.current; const runId = run.id;
    setRun({...run, cancel_requested: true});
    try {const snapshot = await api<Run>(`/runs/${runId}/cancel`, {}); if (selection.current === workspaceId && !deletedWorkspaces.current.has(workspaceId)) setRun(snapshot);}
    catch (cause) {if (selection.current === workspaceId) setError(`Stop has not been confirmed. ${(cause as Error).message}`);}
  }
  async function openArtifact(item: Artifact, version = item.version) {
    if (!safeNavigate()) return;
    const request = ++artifactRequest.current;
    const workspaceId = selection.current;
    try {const [result] = await Promise.all([api<Artifact>(`/artifacts/${item.id}?version=${version}`), refresh(workspaceId)]); if (workspaceId === selection.current && request === artifactRequest.current) {setArtifact(result); setNewKind(null); setPanelView("outputs"); setPanel(true);}}
    catch (cause) {if (workspaceId === selection.current && request === artifactRequest.current) setError((cause as Error).message);}
  }
  async function reconcileWorkspaceRun(workspaceId: string) {
    const history = await refresh(workspaceId);
    const lastId = history?.at(-1)?.run_id;
    if (lastId) {
      const snapshot = await api<Run>(`/runs/${lastId}`);
      if (selection.current === workspaceId) {
        storeRun(workspaceId, lastId);
        if (run?.id !== lastId) {setLive(freshLive()); liveRef.current = freshLive();}
        setRun(snapshot);
      }
    }
  }
  function openControl(view: ControlView | "setup" | "data" | "details" | "context") {
    if (!safeNavigate()) return;
    viewGeneration.current++;
    setPanelView(view); setPanel(true); setNavigation(false);
  }
  async function removeWorkspace(result: DeletedWorkspace, artifactIds: string[]) {
    const workspaceId = result.workspace_id;
    deletedWorkspaces.current.add(workspaceId);
    composerDrafts.current.forget(workspaceId);
    projectContexts.current.forget(workspaceId);
    let browserCleared = true;
    try {clearWorkspaceBrowserData(workspaceId, artifactIds);} catch {browserCleared = false;}
    if (pendingCommand.current?.workspaceId === workspaceId) pendingCommand.current = null;
    setWorkspaces(previous => previous.filter(item => item.id !== workspaceId));
    // A late deletion ACK must never discard another workspace's current view.
    if (selection.current !== workspaceId) return;
    selection.current = ""; artifactRequest.current++; viewGeneration.current++;
    setSelected(null); setMessages([]); setFiles([]); setArtifacts([]); setArtifact(null); setSource(null); setNewKind(null); setRun(null); setLive(freshLive()); liveRef.current = freshLive(); setDraft(""); setUploadQueue([]); setConnection(""); setPanel(false); setPanelView("outputs");
    setContextChoices(emptyContext()); setContextStored(true);
    setError(""); setNotice(browserCleared ? "Workspace deleted. Its application data and this browser’s scoped drafts were removed. Audit history, private backups and downloaded exports may remain." : "Workspace deleted from the application. Browser storage was unavailable, so cached drafts could not be cleared. Remove this site’s browser data before sharing this device. Audit history, private backups and downloaded exports may remain.");
  }
  function openImporter() {if (!safeNavigate()) return; setImportViewToken(++viewGeneration.current); setPanelView("import"); setPanel(true); setNavigation(false);}
  async function checkWorkspaces() {const value = await api<{items: Workspace[]}>("/workspaces?include_archived=true"); setWorkspaces(value.items.filter(item => !deletedWorkspaces.current.has(item.id)));}
  async function importedWorkspace(result: ImportedWorkspace, token: number) {
    if (deletedWorkspaces.current.has(result.workspace.id)) return;
    setWorkspaces(previous => previous.some(item => item.id === result.workspace.id) ? previous : [...previous, result.workspace]);
    if (token !== viewGeneration.current) return;
    setWorkspaceFilter("active"); setWorkspaceQuery(""); await choose(result.workspace); setPanel(false); setNotice("Snapshot imported into a new workspace. Saved content was restored; permissions and running jobs were not.");
  }
  function changedWorkspace(value: Workspace) {
    if (deletedWorkspaces.current.has(value.id)) return;
    setWorkspaces(previous => previous.map(item => item.id === value.id && (item.revision ?? 0) <= (value.revision ?? 0) ? value : item));
    if (selection.current === value.id) {setSelected(previous => previous && (previous.revision ?? 0) <= (value.revision ?? 0) ? value : previous); setWorkspaceFilter(value.archived ? "archived" : "active");}
  }
  const visibleWorkspaces = workspaces.filter(item => !!item.archived === (workspaceFilter === "archived") && item.name.toLocaleLowerCase().includes(workspaceQuery.trim().toLocaleLowerCase()));
  const panelTitle = panelView === "context" ? "Project context" : panelView === "import" ? "Import workspace" : panelView === "details" ? "Workspace details" : panelView === "setup" ? "Model & setup" : panelView === "data" ? "Workspace data" : panelView === "source" ? "Source file" : panelView === "research" ? "Local research" : panelView === "memory" ? "Memory" : panelView === "connections" ? "Connections" : panelView === "schedules" ? "Schedules" : "Outputs";
  const status = loading ? "Connecting…" : availability?.test_mode ? "Simulation · no model calls · fixture:brief / table / patch / research / mcp-read / mcp-effect" : availability?.available ? availability.model ?? "Model ready" : "Model unavailable";
  return <div className="agent-workspace" data-navigation={navigation} data-panel={panel}>
    <a className="aw-skip" href="#aw-composer">Skip to message</a>
    <aside className="aw-sidebar" aria-label="Workspace navigation">
      <div className="aw-brand"><span aria-hidden="true">◈</span> Workspace <button className="aw-mobile" onClick={() => setNavigation(false)} aria-label="Close navigation">×</button></div>
      <button className="aw-new" onClick={() => {setCreating(true); setNavigation(true);}} disabled={loading}>＋ New workspace</button>
      {creating && <form className="aw-create" onSubmit={create}><label htmlFor="aw-name">Workspace name</label><input id="aw-name" autoFocus maxLength={80} value={name} onChange={event => setName(event.target.value)} placeholder="e.g. Field notes"/><div><button type="submit" disabled={!name.trim()}>Create workspace</button><button type="button" onClick={() => setCreating(false)}>Cancel</button></div></form>}
      <button className="aw-import-open" disabled={loading} onClick={openImporter}>Import workspace</button>
      <nav aria-label="Your workspaces"><h2>Your workspaces</h2><label className="aw-visually-hidden" htmlFor="aw-workspace-search">Find a workspace</label><input className="aw-workspace-search" id="aw-workspace-search" type="search" placeholder="Find a workspace" value={workspaceQuery} onChange={event => setWorkspaceQuery(event.target.value)}/><div className="aw-project-filter" aria-label="Workspace list"><button aria-pressed={workspaceFilter === "active"} onClick={() => setWorkspaceFilter("active")}>Active</button><button aria-pressed={workspaceFilter === "archived"} onClick={() => setWorkspaceFilter("archived")}>Archived</button></div>{visibleWorkspaces.map(item => <button key={item.id} aria-current={selected?.id === item.id ? "page" : undefined} onClick={() => void choose(item)}><span aria-hidden="true">▤</span> {item.name}</button>)}{!visibleWorkspaces.length && <p className="aw-muted">{workspaceQuery ? "No workspace matches that name." : workspaceFilter === "archived" ? "Archived projects stay available here." : "A workspace keeps your conversation, files, and drafts together."}</p>}</nav>
      <section className="aw-sources"><div className="aw-section-title"><h2>Source files</h2><button onClick={() => uploadInput.current?.click()} disabled={!selected || uploading} aria-label="Upload source file">＋</button></div>
        <input ref={uploadInput} className="aw-file-input" type="file" multiple accept=".txt,.md,.csv,.docx,.xlsx,.pdf" aria-label="Source file" onChange={event => {const incoming = Array.from(event.target.files ?? []); if (incoming.length) void upload(incoming);}}/>
        {files.length ? <ul>{files.map(file => <li key={file.id}><button className="aw-source-link" onClick={() => {if (!safeNavigate()) return; setSource(file); setPanelView("source"); setPanel(true); setNavigation(false);}}><span aria-hidden="true">▱</span><span>{file.filename}<small>{Math.max(1, Math.round(file.bytes / 1000))} KB{file.provenance?.provenance === "offline_fixture" ? " · Offline fixture" : ""}</small></span></button></li>)}</ul> : <p className="aw-muted">Add TXT, Markdown, CSV, DOCX, XLSX, or text PDF. Up to 256,000 bytes per file, 10 files per batch. Images, scans, macros, and formulas are not evaluated.</p>}
        {!!uploadQueue.length && <ul className="aw-upload-queue" aria-label="Upload results" aria-live="polite">{uploadQueue.map((item, index) => <li key={index}><span>{item.filename}</span><small>{item.status === "saved" ? "Saved" : item.status === "queued" ? "Uploading…" : `Not saved: ${item.detail}`}</small></li>)}</ul>}
        {uploading && <p role="status">Saving source files…</p>}
        <button className="aw-research-open" disabled={!selected} onClick={() => {if (!safeNavigate()) return; setPanelView("research"); setPanel(true); setNavigation(false);}}>Search local fixtures</button>
      </section>
      <section className="aw-workspace-controls" aria-label="Workspace controls"><button disabled={!selected || loading} aria-pressed={panel && panelView === "memory"} onClick={() => openControl("memory")}>Memory</button>{availability?.test_mode && (["connections", "schedules"] as const).map(view => <button key={view} disabled={!selected || loading} aria-pressed={panel && panelView === view} onClick={() => openControl(view)}>{view === "connections" ? "Connections" : "Schedules"}</button>)}<button aria-pressed={panel && panelView === "setup"} onClick={() => openControl("setup")}>Model & setup</button><button disabled={!selected || loading} aria-pressed={panel && panelView === "data"} onClick={() => openControl("data")}>Workspace data</button></section>
      <div className="aw-sidebar-foot">Local workspace<br/><small>Shell and live external tools are off. Fixture actions and schedules are simulations.</small></div>
    </aside>
    {navigation && <button className="aw-scrim" aria-label="Close navigation" onClick={() => setNavigation(false)}/>}
    <main className="aw-main">
      <header className="aw-header"><button className="aw-mobile" aria-label="Open navigation" disabled={loading} onClick={() => setNavigation(true)}>☰</button><h1>{selected?.name ?? "Agent Workspace"}</h1>{selected && <button className="aw-project-menu" onClick={() => openControl("details")} aria-label="Workspace details">•••</button>}<button className="aw-panel-toggle" aria-expanded={panel && panelView === "outputs"} onClick={() => {if (!safeNavigate()) return; viewGeneration.current++; setPanelView("outputs"); setPanel(value => panelView !== "outputs" || !value);}}>Outputs <span aria-hidden="true">{panel ? "›" : "‹"}</span></button></header>
      <div className={`aw-availability${availability?.test_mode ? " aw-simulation" : ""}`} role="status"><span className="aw-dot" aria-hidden="true"/>{status}{!loading && !availability?.available && <span> · {availability?.reason ?? "Start the workspace service to connect."}</span>}</div>
      {error && <div className="aw-error" role="alert"><p>{error}</p><button onClick={() => void connect()}>Reconnect</button><button onClick={() => setError("")} aria-label="Dismiss error">×</button></div>}
      {notice && <div className="aw-error" role="status"><p>{notice}</p><button onClick={() => setNotice("")} aria-label="Dismiss notification">×</button></div>}
      {selected?.archived && <div className="aw-archive-note" role="status">Archived workspace. Saved files and outputs remain available. <button onClick={() => openControl("details")}>Restore to send new requests</button></div>}
      <div className="aw-transcript" ref={transcript} onScroll={event => {const element = event.currentTarget; nearBottom.current = element.scrollHeight - element.scrollTop - element.clientHeight < 100;}}>
        <div className="aw-measure">
          {!messages.length && !sendingCurrent && <div className="aw-empty"><div className="aw-empty-mark" aria-hidden="true">◈</div><h2>A place to think and make.</h2><p>{availability?.test_mode ? "This is a scripted local integration test, not an AI assistant. Add a source file and use the fixture commands to test saved drafts and revisions." : "Bring a source file, ask a question, or turn your notes into a working draft. Your conversation and outputs stay together."}</p>{!selected ? <button onClick={() => {setCreating(true); setNavigation(true);}}>Create your first workspace</button> : <div className="aw-suggestions"><button onClick={() => uploadInput.current?.click()}>Add a source file</button><button onClick={() => {writeDraft(availability?.test_mode ? "fixture:create" : "Create a concise Markdown brief from my source files."); composer.current?.focus();}}>{availability?.test_mode ? "Test draft creation" : "Create a brief from my files"}</button></div>}</div>}
          {messages.map(message => <article key={message.id} className={`aw-message aw-${message.role}`} aria-label={message.role === "user" ? "Your message" : "Assistant message"}><div className="aw-message-label">{message.role === "user" ? "You" : "Assistant"}</div><Markdown content={message.content}/></article>)}
          {(active || sendingCurrent) && <article className="aw-message aw-assistant" aria-label="Assistant response in progress"><div className="aw-message-label">Assistant <span>{run?.cancel_requested ? "Stop requested" : live.state === "waiting_approval" || run?.state === "waiting_approval" ? "Waiting for your review" : live.content ? "Writing…" : "Working…"}</span></div>{live.content ? <Markdown content={live.content}/> : <p className="aw-muted">{live.state === "waiting_approval" || run?.state === "waiting_approval" ? "Review the exact simulated action below. No action is approved by the conversation alone." : live.activities.at(-1) ?? "Starting your request…"}</p>}</article>}
          {run && terminal(run.state) && run.state !== "completed" && <p className="aw-run-note" role="status">{run.state === "cancelled" ? "Stopped. Saved drafts remain available." : `Run ${run.state}. ${run.error ?? "Check the activity panel before trying again."}`}</p>}
        </div>
      </div>
      <div className="aw-compose-wrap">
        {selected && run && active && availability?.test_mode && <ApprovalPrompt key={`${selected.id}:${run.id}`} workspaceId={selected.id} runId={run.id} onResolved={() => void reconcileWorkspaceRun(selected.id).catch(cause => setError(cause.message))}/>}
        <form className="aw-composer" onSubmit={submit} data-unsafe-draft={!draftStored || undefined} data-draft-clear-failed={!draftStored && !draft || undefined}>
          {selected && <div className="aw-context-summary"><button type="button" className="aw-context-open" aria-pressed={panel && panelView === "context"} onClick={() => openControl("context")}>Project context</button><span>{contextChoices.references.length ? `${contextChoices.references.length} selected reference(s)` : "Automatic selection"}{contextChoices.target ? ` · Continue from version ${contextChoices.target.version}` : ""}</span></div>}
          <label className="aw-visually-hidden" htmlFor="aw-composer">Message</label>
          <textarea id="aw-composer" ref={composer} rows={3} maxLength={16000} value={draft} onChange={event => writeDraft(event.target.value)} placeholder={selected ? "Ask anything, or describe what you want to make…" : "Create a workspace to start…"} disabled={!selected} onKeyDown={event => {if (event.key === "Enter" && !event.shiftKey && !event.nativeEvent.isComposing) {event.preventDefault(); event.currentTarget.form?.requestSubmit();}}}/>
          <div className="aw-composer-bottom"><button type="button" className="aw-attach" onClick={() => uploadInput.current?.click()} disabled={!selected || uploading} aria-label="Attach source file">＋ <span>Add file</span></button><span className="aw-input-hint">Enter to send · Shift + Enter for a new line</span>{active ? <button type="button" className="aw-send" onClick={() => void stop()} disabled={run?.cancel_requested}>{run?.cancel_requested ? "Stop requested" : "Stop"}</button> : <button className="aw-send" type="submit" disabled={!selected || selected.archived || !draft.trim() || !availability?.available || sending}>Send <span aria-hidden="true">↑</span></button>}</div>
        </form>
        {!draftStored && <p className="aw-draft-warning" role="status">{draft ? "This draft is kept in this tab only because browser storage is unavailable. Copy it before closing or reloading." : "Browser storage could not clear an older draft. It may reappear after reload; saved server work is unchanged."} <button className="aw-text-action" onClick={() => writeDraft(draft)}>Retry draft storage</button></p>}
        {!contextStored && <p className="aw-draft-warning" role="status">Context choices are kept in this tab only. Check them again after reload. <button className="aw-text-action" onClick={() => changeContext(contextChoices)}>Retry saving context choices</button></p>}
        <p className="aw-compose-note" role="status">{connection || (availability?.test_mode ? "Simulation uses a deterministic test model. Outputs are not AI quality evidence." : "Review important details in generated drafts.")}</p>
      </div>
    </main>
    {panel && <aside className="aw-panel" aria-label="Outputs and activity"><div className="aw-panel-head"><h2>{panelTitle}</h2><button onClick={() => {if (safeNavigate()) {viewGeneration.current++; setPanel(false);}}} aria-label="Close outputs">×</button></div>
      {panelView === "import" && <WorkspaceImporter key={importViewToken} viewToken={importViewToken} onImported={importedWorkspace} onCheck={checkWorkspaces}/>}
      {panelView === "details" && selected && <WorkspaceDetails key={selected.id} workspace={selected} active={active || sendingCurrent} onChanged={changedWorkspace}/>}
      {panelView === "context" && selected && <WorkspaceContext key={selected.id} workspaceId={selected.id} files={files} artifacts={artifacts} choices={contextChoices} message={draft} runId={run?.id} archived={selected.archived} onChoices={value => changeContext(value, selected.id)} onSourceReplaced={() => setSourceRefreshToken(value => value + 1)}/>}
      {panelView === "setup" && <ModelSetup onReadiness={setAvailability}/>}
      {panelView === "data" && selected && <WorkspaceData key={selected.id} workspace={selected} active={active || sendingCurrent || uploading} onDeleted={removeWorkspace} onRecover={() => {if (availability?.test_mode) openControl("connections"); else {setPanelView("outputs"); setPanel(true);}}}/>}
      {panelView === "memory" && selected && <MemoryPanel key={selected.id} workspaceId={selected.id}/>}
      {panelView === "connections" && selected && <ConnectionPanel key={selected.id} workspaceId={selected.id} onPrepare={command => {writeDraft(command); setPanel(false); composer.current?.focus();}}/>}
      {panelView === "schedules" && selected && <SchedulePanel key={selected.id} workspaceId={selected.id} onDispatched={() => void reconcileWorkspaceRun(selected.id).catch(cause => setError(cause.message))}/>}
      {panelView === "source" && source && <SourcePreview key={source.id} file={source}/>}
      {panelView === "research" && selected && <LocalResearch key={selected.id} workspaceId={selected.id} onImported={async file => {const workspaceId = selected.id; await refresh(workspaceId); if (selection.current === workspaceId) {setSource(file); setPanelView("source");}}}/>}
      {panelView === "outputs" && <><div className="aw-output-create">{(["document", "table"] as const).map(kind => <button key={kind} disabled={!selected} onClick={() => {if (safeNavigate()) setNewKind(kind);}}>＋ New {kind}</button>)}</div><div className="aw-output-list">{artifacts.length ? artifacts.map(item => <button key={item.id} aria-current={!newKind && artifact?.id === item.id ? "true" : undefined} onClick={() => void openArtifact(item)}><strong>{item.title || item.filename}</strong><small>{item.kind === "table" ? "Table · CSV" : "Markdown"} · Version {item.version}</small></button>) : <p className="aw-muted">Drafts you create appear here. Open, revise, and download them without leaving the conversation.</p>}</div>
      {newKind && selected ? <ArtifactCreator key={`${selected.id}:${newKind}`} workspaceId={selected.id} kind={newKind} onCreated={async result => {const workspaceId = selected.id; await refresh(workspaceId); if (selection.current === workspaceId) {setArtifact(result); setNewKind(null);}}} onCancel={() => {if (safeNavigate()) setNewKind(null);}}/> : artifact && <div className="aw-output-detail" key={`${artifact.id}:${artifact.version}`}><ArtifactEditor artifact={artifact} latestVersion={artifacts.find(item => item.id === artifact.id)?.version ?? artifact.version} allowChatRevision={!availability?.test_mode && !selected?.archived} onOpen={version => void openArtifact(artifact, version)} onConflict={async () => {if (selected) await refresh(selected.id);}} onSaved={async result => {const workspaceId = selected?.id; if (!workspaceId) return; await refresh(workspaceId); if (selection.current === workspaceId) setArtifact(result);}} onRevise={() => {changeContext({...contextChoices, target: artifactReference(artifact)}); writeDraft(`Revise "${artifact.title || artifact.filename}" (version ${artifact.version}): `); composer.current?.focus();}}/>
        <button className="aw-context-continue" disabled={selected?.archived || active || sendingCurrent} onClick={() => {if (!safeNavigate()) return; changeContext({...contextChoices, target: artifactReference(artifact)}); setPanelView("context"); composer.current?.focus();}}>Continue from this version</button><ArtifactDependencies artifact={artifact} refreshToken={sourceRefreshToken}/></div>}
      <section className="aw-activity" aria-label="Run activity"><h2>Activity</h2>{live.activities.length ? <ol>{live.activities.map((activity, index) => <li key={index}>{activity}</li>)}</ol> : <p className="aw-muted">Tool progress appears here while a request is running.</p>}{run?.usage && <p className="aw-muted">{run.usage.requests} model request(s), {run.usage.input_tokens + run.usage.output_tokens} tokens. Cost: {run.usage.cost_usd === null ? "unknown" : `$${run.usage.cost_usd}`}.</p>}</section></>}
    </aside>}
  </div>;
}
