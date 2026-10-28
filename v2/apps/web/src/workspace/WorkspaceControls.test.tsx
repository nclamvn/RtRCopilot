// @vitest-environment jsdom
import React from "react";
import "@testing-library/jest-dom/vitest";
import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {afterEach, beforeEach, expect, test, vi} from "vitest";
import {ApprovalPrompt, ConnectionPanel, MemoryPanel, SchedulePanel} from "./WorkspaceControls";
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status, headers: {"content-type": "application/json"}});
const memory = {id: "note-one", content: "User preference 24750 Việt Nam", version: 1, source: "user"};
const approval = {id: "a-one", run_id: "r-one", workspace_id: "w-one", status: "pending", tool: "send_note", arguments: {note: "<script>not executable</script> Keep 24750", artifact_id: "artifact-one", expected_version: 2}, expires_at: 1999999999};
beforeEach(() => {vi.stubGlobal("React", React);});
afterEach(() => {cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks();});

test("UI-only explicit memory edits use revision and lock pending input, not automatic model writes", async () => {
  let finish: ((r: Response) => void) | undefined;
  const fetcher = vi.fn(async (_url: string, init?: RequestInit) => init?.method === "POST" ? new Promise<Response>(resolve => {finish = resolve;}) : json({items: [memory], revision: 1}));
  vi.stubGlobal("fetch", fetcher); render(<MemoryPanel workspaceId="w-one"/>); await screen.findByText(memory.content);
  fireEvent.click(screen.getByRole("button", {name: "Edit memory"})); fireEvent.change(screen.getByLabelText("Edit remembered note"), {target: {value: "Revised 24750 Việt Nam"}}); fireEvent.click(screen.getByRole("button", {name: "Save memory changes"}));
  expect(screen.getByLabelText("Edit remembered note")).toHaveAttribute("readonly"); fireEvent.change(screen.getByLabelText("Edit remembered note"), {target: {value: "Must not replace pending save"}}); expect(screen.getByLabelText("Edit remembered note")).toHaveValue("Revised 24750 Việt Nam");
  const posts = fetcher.mock.calls.filter(([, init]) => init?.method === "POST"); expect(posts).toHaveLength(1); expect(posts[0][0]).toBe("/api/workspace/workspaces/w-one/memory/note-one/edit"); expect(JSON.parse(posts[0][1]!.body as string)).toMatchObject({expected_version: 1, content: "Revised 24750 Việt Nam"});
  finish!(json({...memory, version: 2})); await screen.findByText("Memory saved for this workspace."); expect(fetcher.mock.calls.some(([url]) => url.endsWith("/runs"))).toBe(false);
});

test("UI-only late memory response from a closed workspace cannot disclose it in another workspace", async () => {
  let finish: ((r: Response) => void) | undefined;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.includes("w-one") ? new Promise<Response>(resolve => {finish = resolve;}) : json({items: [], revision: 0})));
  const first = render(<MemoryPanel workspaceId="w-one"/>); await waitFor(() => expect(finish).toBeTypeOf("function")); first.unmount(); render(<MemoryPanel workspaceId="w-two"/>); await screen.findByText(/No saved memories/);
  finish!(json({items: [memory], revision: 1})); await new Promise(resolve => setTimeout(resolve, 0)); expect(screen.queryByText(memory.content)).not.toBeInTheDocument();
});

test("UI-only memory deletion is explicit and version-bound, no invisible automatic deletion", async () => {
  const fetcher = vi.fn(async (_url: string, init?: RequestInit) => init?.method === "POST" ? json({deleted: true}) : json({items: [memory], revision: 1})); vi.stubGlobal("fetch", fetcher); render(<MemoryPanel workspaceId="w-one"/>); await screen.findByText(memory.content);
  fireEvent.click(screen.getByRole("button", {name: "Delete memory"})); expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0);
  fireEvent.click(screen.getByRole("button", {name: "Confirm delete memory"})); await screen.findByText(/Memory deleted/); const posts = fetcher.mock.calls.filter(([, init]) => init?.method === "POST"); expect(posts).toHaveLength(1); expect(JSON.parse(posts[0][1]!.body as string)).toMatchObject({expected_version: 1});
});

test("UI-only approval renders untrusted preview as text and only sends a server decision", async () => {
  const fetcher = vi.fn(async (_url: string, init?: RequestInit) => init?.method === "POST" ? json({...approval, status: "approved"}) : json({items: [approval]})); vi.stubGlobal("fetch", fetcher); const resolved = vi.fn(); render(<ApprovalPrompt workspaceId="w-one" runId="r-one" onResolved={resolved}/>);
  await screen.findByText(approval.arguments.note); expect(screen.getByText(/File contents are not attached/)).toBeVisible(); expect(document.querySelector("script")).toBeNull(); fireEvent.click(screen.getByRole("button", {name: "Approve simulated action"})); await waitFor(() => expect(resolved).toHaveBeenCalledTimes(1)); const post = fetcher.mock.calls.find(([, init]) => init?.method === "POST")!; expect(post[0]).toBe("/api/workspace/approvals/a-one/resolve"); const body = JSON.parse(post[1]!.body as string); expect(Object.keys(body).sort()).toEqual(["decision", "request_id"]); expect(body.decision).toBe("approve"); expect(body.approved).toBeUndefined();
});

test("UI-only connection read test is prepared only after one explicit permission grant", async () => {
  let granted = false; const prepared = vi.fn(); const fetcher = vi.fn(async (url: string, init?: RequestInit) => {if (init?.method === "POST") {granted = true; return json({enabled: true, revision: 1});} return url.endsWith("/connection") ? json({fixture: true, enabled: granted, revision: granted ? 1 : 0, external: false, tools: [{name: "read_status", effect: false}, {name: "send_note", effect: true}]}) : json({items: []});}); vi.stubGlobal("fetch", fetcher); render(<ConnectionPanel workspaceId="w-one" onPrepare={prepared}/>);
  await screen.findByText("Not connected"); expect(screen.queryByRole("button", {name: "Prepare read test"})).not.toBeInTheDocument(); fireEvent.click(screen.getByRole("button", {name: "Grant fixture permission"})); await screen.findByText("Permission granted for this workspace"); fireEvent.click(screen.getByRole("button", {name: "Prepare read test"})); expect(prepared).toHaveBeenCalledWith("fixture:mcp-read"); expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
});

test("UI-only manual schedules do not auto-tick; paused tasks have explicit resume/cancel", async () => {
  const fetcher = vi.fn(async (_url: string, init?: RequestInit) => init?.method === "POST" ? json({clock: 60, blocked: []}) : json({clock: 0, items: [{id: "s-one", message: "fixture:chat", due_at: 60, state: "paused", version: 2, run_id: null, error: null}]})); vi.stubGlobal("fetch", fetcher); const dispatched = vi.fn(); render(<SchedulePanel workspaceId="w-one" onDispatched={dispatched}/>); await screen.findByText("fixture:chat"); expect(fetcher.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(0); expect(screen.getByRole("button", {name: "Resume task"})).toBeVisible(); fireEvent.click(screen.getByRole("button", {name: "Advance simulation clock"})); await waitFor(() => expect(dispatched).toHaveBeenCalledTimes(1)); const post = fetcher.mock.calls.find(([, init]) => init?.method === "POST")!; expect(post[0]).toBe("/api/workspace/workspaces/w-one/clock/tick"); expect(JSON.parse(post[1]!.body as string)).toMatchObject({target: 60});
});

test("UI-only an unknown effect exposes reconciliation, not a retry or a second send", async () => {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {
    if (init?.method === "POST") return json({id: "e-one", status: "uncertain"});
    if (url.endsWith("/connection")) return json({fixture: true, enabled: true, revision: 1, external: false, tools: []});
    if (url.endsWith("/effects")) return json({items: [{id: "e-one", run_id: "r-one", status: "uncertain", tool: "send_note", arguments: {note: "Synthetic note 91230"}}]});
    return json({items: []});
  }); vi.stubGlobal("fetch", fetcher); render(<ConnectionPanel workspaceId="w-one" onPrepare={vi.fn()}/>);
  await screen.findByText("Outcome unknown; reconcile before doing anything else"); expect(screen.queryByRole("button", {name: /retry|send again/i})).not.toBeInTheDocument(); fireEvent.click(screen.getByRole("button", {name: "Reconcile receipt"})); await screen.findByText("Receipt lookup complete. No action was replayed.");
  const posts = fetcher.mock.calls.filter(([, init]) => init?.method === "POST"); expect(posts).toHaveLength(1); expect(posts[0][0]).toBe("/api/workspace/effects/e-one/reconcile"); expect(Object.keys(JSON.parse(posts[0][1]!.body as string))).toEqual(["request_id"]);
});
