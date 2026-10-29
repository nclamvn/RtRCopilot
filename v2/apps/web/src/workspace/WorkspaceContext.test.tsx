// @vitest-environment jsdom
import React from "react";
import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import {afterEach, beforeEach, expect, test, vi} from "vitest";
import {ArtifactDependencies, WorkspaceContext} from "./WorkspaceContext";
import {emptyContext} from "./contextChoices";
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status, headers: {"content-type": "application/json"}});
const brief = {revision: 0, goal: "", decisions: "", remaining: ""};
const props = () => ({workspaceId: "alpha", files: [{id: "f-old", filename: "old.csv", bytes: 20}, {id: "f-new", filename: "new.csv", bytes: 20}], artifacts: [{id: "a", title: "Brief", filename: "brief.md", version: 2}], choices: emptyContext(), message: "synthetic 004173", onChoices: vi.fn(), onSourceReplaced: vi.fn()});
beforeEach(() => {vi.stubGlobal("React", React);});
afterEach(() => {cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks();});
test("UI-only context preview discloses excerpts and omissions without declaring complete reading", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/brief") ? json(brief) : json({mode: "explicit", references: [], target: null, selections: [{kind: "file", id: "f-old", label: "old.csv", content: "004173", has_more: true}], context_bytes: 100, limit_bytes: 65536, digest: "digest-one", coverage: "partial", omissions: ["Older turns omitted"], read_ledger: []})));
  const value = props(); render(<WorkspaceContext {...value}/>);
  fireEvent.click(screen.getByRole("button", {name: "Preview request context"}));
  const view = await screen.findByLabelText("Context preview"); expect(view).toHaveTextContent("100 / 65,536 bytes"); expect(view).toHaveTextContent("Older turns omitted"); expect(view).toHaveTextContent("Excerpt only"); expect(view).toHaveTextContent("not certify semantic completeness");
  fireEvent.click(screen.getByText(/Add project sources/)); fireEvent.click(screen.getByLabelText("old.csv", {selector: "input"})); expect(value.onChoices).toHaveBeenCalledWith({references: [{kind: "file", id: "f-old"}], target: null});
});
test("UI-only brief is user-authored, revision-bound and retries a lost ACK with the same request identity", async () => {
  const bodies: unknown[] = []; let saves = 0;
  vi.stubGlobal("fetch", vi.fn(async (_url: string, init?: RequestInit) => {
    if (!init?.body) return json(brief);
    const body = JSON.parse(init.body as string); bodies.push(body);
    return ++saves === 1 ? json({detail: "http_503"}, 503) : json({...brief, revision: 1, goal: body.goal});
  }));
  render(<WorkspaceContext {...props()}/>); fireEvent.click(screen.getByText("Project brief", {exact: true}));
  await waitFor(() => expect(screen.getByLabelText("Goal", {exact: true})).toBeEnabled()); fireEvent.change(screen.getByLabelText("Goal", {exact: true}), {target: {value: "Museum handover 004173"}});
  fireEvent.click(screen.getByRole("button", {name: "Save project brief"})); await screen.findByRole("alert"); expect(screen.getByLabelText("Goal", {exact: true})).toHaveValue("Museum handover 004173");
  fireEvent.click(screen.getByRole("button", {name: "Save project brief"})); await screen.findByText(/Project brief saved/); expect(bodies).toHaveLength(2); expect(bodies[0]).toEqual(bodies[1]); expect(bodies[0]).toMatchObject({expected_revision: 0, goal: "Museum handover 004173"});
  expect(screen.getByText(/not automatically inferred or verified/)).toBeVisible();
});
test("UI-only source replacement is explicit and never changes either original or output automatically", async () => {
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => url.endsWith("/brief") ? json(brief) : json(JSON.parse(init!.body as string))); vi.stubGlobal("fetch", fetcher);
  const value = props(); render(<WorkspaceContext {...value}/>); fireEvent.click(screen.getByText("Record a source replacement", {exact: true}));
  expect(screen.getByRole("button", {name: "Record replacement"})).toBeDisabled(); fireEvent.change(screen.getByLabelText("Previous source"), {target: {value: "f-old"}}); fireEvent.change(screen.getByLabelText("Replacement source"), {target: {value: "f-new"}}); fireEvent.click(screen.getByRole("button", {name: "Record replacement"}));
  await waitFor(() => expect(value.onSourceReplaced).toHaveBeenCalledOnce()); expect(JSON.parse(fetcher.mock.calls.find(([url]) => url.endsWith("/source-replacements"))![1]!.body as string)).toMatchObject({old_file_id: "f-old", new_file_id: "f-new"}); expect(screen.getByText(/Both originals are retained/)).toBeVisible();
});
test("UI-only local search adds a scoped pinned reference and renders text safely", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/brief") ? json(brief) : json({items: [{kind: "artifact", id: "a", version: 2, label: "Brief", snippet: "<script>synthetic 004173</script>"}], truncated: true})));
  const value = props(); render(<WorkspaceContext {...value}/>); fireEvent.change(screen.getByLabelText("Find in this project"), {target: {value: "004173"}}); fireEvent.click(screen.getByRole("button", {name: "Search project"})); await screen.findByLabelText("Project search results");
  expect(screen.getByText("<script>synthetic 004173</script>")).toBeVisible(); expect(document.querySelector(".aw-context script")).toBeNull(); expect(screen.getByText(/Results are limited/)).toBeVisible(); fireEvent.click(screen.getByRole("button", {name: "Use for next request"})); expect(value.onChoices).toHaveBeenCalledWith({references: [{kind: "artifact", id: "a", version: 2}], target: null});
});
test("UI-only late preview after changing context or unmount cannot replace the current view", async () => {
  let release!: (value: Response) => void;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/brief") ? json(brief) : new Promise<Response>(resolve => {release = resolve;})));
  const value = props(); const view = render(<WorkspaceContext {...value}/>); fireEvent.click(screen.getByRole("button", {name: "Preview request context"}));
  view.rerender(<WorkspaceContext {...value} message="Different request"/>); release(json({mode: "automatic", selections: [], omissions: [], references: [], target: null, context_bytes: 100, limit_bytes: 65536, digest: "stale", coverage: "partial"}));
  await waitFor(() => expect(screen.queryByLabelText("Context preview")).toBeNull());
});
test("UI-only loading current brief invalidates a pending old preview and locks fields until readback", async () => {
  let release!: (value: Response) => void; let briefCalls = 0;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/brief") ? json(++briefCalls === 1 ? brief : {...brief, revision: 1, goal: "New saved brief"}) : new Promise<Response>(resolve => {release = resolve;})));
  render(<WorkspaceContext {...props()}/>); fireEvent.click(screen.getByText("Project brief", {exact: true})); await waitFor(() => expect(screen.getByLabelText("Goal", {exact: true})).toBeEnabled()); fireEvent.click(screen.getByRole("button", {name: "Preview request context"}));
  fireEvent.click(screen.getByRole("button", {name: "Load current brief"})); await waitFor(() => expect(screen.getByLabelText("Goal", {exact: true})).toHaveValue("New saved brief"));
  release(json({mode: "automatic", selections: [], omissions: [], references: [], target: null, context_bytes: 100, limit_bytes: 65536, digest: "old-preview", coverage: "partial"})); await waitFor(() => expect(screen.queryByLabelText("Context preview")).toBeNull());
});
test("UI-only saved context annotates later source replacement without rewriting captured input", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/brief") ? json(brief) : json({mode: "explicit", references: [{kind: "file", id: "f-old"}], target: null, selections: [{kind: "file", id: "f-old", label: "old.csv", content: "old 91.125"}], omissions: [], context_bytes: 40, limit_bytes: 65536, digest: "original-digest", coverage: "partial", current_changes: [{old_file_id: "f-old", new_file_id: "f-new"}], read_ledger: []})));
  render(<WorkspaceContext {...props()} runId="run-one"/>); fireEvent.click(screen.getByRole("button", {name: "Inspect saved run context"})); await screen.findByText("Sources changed after this input was captured"); expect(screen.getByText(/old.csv has a recorded replacement: new.csv/)).toBeVisible(); expect(screen.getByText(/saved input and its fingerprint have not been rewritten/)).toBeVisible(); fireEvent.click(screen.getByText("Context fingerprint", {exact: true})); expect(screen.getByText("original-digest")).toBeVisible();
});
test("UI-only saved run inspection does not pretend the next draft is the run input", async () => {
  const fetcher = vi.fn(async (url: string) => url.endsWith("/brief") ? json(brief) : json({mode: "automatic", references: [], target: null, selections: [], omissions: ["Previous turns not included"], context_bytes: 40, limit_bytes: 65536, digest: "saved-digest", coverage: "partial", read_ledger: [{kind: "file", id: "f", offset: 0, end: 20}]})); vi.stubGlobal("fetch", fetcher);
  render(<WorkspaceContext {...props()} runId="run-one"/>); fireEvent.click(screen.getByRole("button", {name: "Inspect saved run context"})); await screen.findByLabelText("Saved run context"); expect(fetcher.mock.calls.some(([url]) => url.endsWith("/runs/run-one/context"))).toBe(true); expect(screen.getByText(/1 recorded read range/)).toBeVisible(); expect(screen.getByText(/not a resumable execution/)).toBeVisible();
});
test("UI-only unavailable historical context is explained without assuming a complete manifest", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.endsWith("/brief") ? json(brief) : json({status: "unavailable", omissions: ["scope changed"], read_ledger: []})));
  render(<WorkspaceContext {...props()} runId="old-run"/>); fireEvent.click(screen.getByRole("button", {name: "Inspect saved run context"})); await screen.findByText("Saved context is unavailable"); expect(screen.getByText("scope changed")).toBeVisible(); expect(screen.getByText(/not proof that no source was used/)).toBeVisible(); expect(screen.queryByText(/recorded read range/)).toBeNull();
});
test("UI-only dependency freshness reports unknown lineage separately from changed recorded sources", async () => {
  let stale = false; vi.stubGlobal("fetch", vi.fn(async () => json({status: stale ? "known" : "unknown", dependencies: stale ? [{kind: "file", id: "old", label: "old.csv", stale: true}] : [], stale, reasons: stale ? ["old.csv replaced"] : [], coverage: "recorded reads, not semantic completeness"})));
  const artifact = props().artifacts[0]; const view = render(<ArtifactDependencies artifact={artifact}/>); await screen.findByText(/Source lineage is unknown/); stale = true; view.rerender(<ArtifactDependencies artifact={artifact} refreshToken={1}/>); await screen.findByText(/recorded source or output has changed/); expect(screen.getByText("old.csv replaced")).toBeVisible(); expect(screen.getByText("recorded reads, not semantic completeness")).toBeVisible();
});
