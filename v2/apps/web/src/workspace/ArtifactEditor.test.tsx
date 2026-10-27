// @vitest-environment jsdom
import React from "react";
import "@testing-library/jest-dom/vitest";
import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {afterEach, beforeEach, expect, test, vi} from "vitest";
import {ArtifactCreator, ArtifactEditor} from "./ArtifactEditor";
import {type Artifact} from "./contracts";
const artifact: Artifact = {id: "artifact-one", title: "Study", filename: "study.md", version: 2, kind: "document", content: "# Study\n\nPreserved 24,750.\n\n## Change\nOld detail"};
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status, headers: {"content-type": "application/json"}});
beforeEach(() => {localStorage.clear(); vi.stubGlobal("React", React);});
afterEach(() => {cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks();});
function mount(item = artifact, latestVersion = item.version, onSaved = vi.fn(async () => {})) {
  return render(<ArtifactEditor artifact={item} latestVersion={latestVersion} onOpen={vi.fn()} onSaved={onSaved} onRevise={vi.fn()}/>);
}
test("UI-only: localized manual edit sends expected version and idempotency key once, preserving other text", async () => {
  let finish: ((response: Response) => void) | undefined;
  const fetcher = vi.fn(async (url: string, init?: RequestInit) => {void init; return url.includes("revisions") ? new Promise<Response>(resolve => {finish = resolve;}) : json({items: []});}); vi.stubGlobal("fetch", fetcher);
  const onSaved = vi.fn(async () => {}); mount(artifact, 2, onSaved);
  fireEvent.click(screen.getByRole("tab", {name: "Edit"}));
  const text = artifact.content!.replace("Old detail", "New detail"); fireEvent.change(screen.getByLabelText("Edit Markdown text"), {target: {value: text}});
  fireEvent.click(screen.getByRole("button", {name: "Save new version"})); fireEvent.click(screen.getByRole("button", {name: "Save new version"}));
  expect(screen.getByLabelText("Edit Markdown text")).toHaveAttribute("readonly");
  const requests = fetcher.mock.calls.filter(([url]) => url.includes("revisions")); expect(requests).toHaveLength(1);
  const payload = JSON.parse(requests[0][1]!.body as string); expect(payload).toMatchObject({expected_version: 2, content: text}); expect(payload.request_id.length).toBeGreaterThan(8);
  finish!(json({...artifact, version: 3, content: text})); await waitFor(() => expect(onSaved).toHaveBeenCalledTimes(1)); expect(localStorage.getItem("agent-workspace:artifact-draft:artifact-one")).toBeNull();
});
test("UI-only delayed revision acknowledgement cannot delete a newer draft after close/reopen", async () => {
  let finish: ((response: Response) => void) | undefined;
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.includes("revisions") ? new Promise<Response>(resolve => {finish = resolve;}) : json({items: []})));
  const saved = vi.fn(async () => {}); const first = mount(artifact, 2, saved); fireEvent.click(screen.getByRole("tab", {name: "Edit"})); fireEvent.change(screen.getByLabelText("Edit Markdown text"), {target: {value: "Submitted content"}}); fireEvent.click(screen.getByRole("button", {name: "Save new version"})); first.unmount();
  mount(); fireEvent.click(screen.getByRole("tab", {name: "Edit"})); fireEvent.change(screen.getByLabelText("Edit Markdown text"), {target: {value: "Newer unsaved content"}});
  finish!(json({...artifact, version: 3, content: "Submitted content"})); await waitFor(() => expect(saved).toHaveBeenCalled());
  expect(JSON.parse(localStorage.getItem("agent-workspace:artifact-draft:artifact-one")!).content).toBe("Newer unsaved content"); expect(screen.getByLabelText("Edit Markdown text")).toHaveValue("Newer unsaved content");
});
test("UI-only delayed creation locks submitted fields and preserves a newer reopened creation draft", async () => {
  let finish: ((response: Response) => void) | undefined; vi.stubGlobal("fetch", vi.fn(async () => new Promise<Response>(resolve => {finish = resolve;})));
  const created = vi.fn(async () => {}); const props = {workspaceId: "w1", kind: "document" as const, onCreated: created, onCancel: vi.fn()};
  const first = render(<ArtifactCreator {...props}/>); fireEvent.change(screen.getByLabelText("Title"), {target: {value: "Original title"}}); fireEvent.change(screen.getByLabelText("Markdown content"), {target: {value: "Original content"}}); fireEvent.click(screen.getByRole("button", {name: "Save first version"}));
  expect(screen.getByLabelText("Title")).toHaveAttribute("readonly"); expect(screen.getByLabelText("Markdown content")).toHaveAttribute("readonly"); fireEvent.change(screen.getByLabelText("Markdown content"), {target: {value: "Blocked change"}}); expect(screen.getByLabelText("Markdown content")).toHaveValue("Original content"); first.unmount();
  render(<ArtifactCreator {...props}/>); fireEvent.change(screen.getByLabelText("Markdown content"), {target: {value: "Newer reopened content"}}); finish!(json({...artifact, version: 1})); await waitFor(() => expect(created).toHaveBeenCalled()); expect(JSON.parse(localStorage.getItem("agent-workspace:new-draft:w1:document")!).content).toBe("Newer reopened content");
});
test("UI-only: conflict preserves browser draft across unmount/reload and blocks editing a stale saved version", async () => {
  vi.stubGlobal("fetch", vi.fn(async (url: string) => url.includes("revisions") ? json({detail: "stale_artifact_version"}, 409) : json({items: []})));
  const view = mount(); fireEvent.click(screen.getByRole("tab", {name: "Edit"})); fireEvent.change(screen.getByLabelText("Edit Markdown text"), {target: {value: "Unsaved useful work"}}); fireEvent.click(screen.getByRole("button", {name: "Save new version"}));
  await screen.findByRole("alert"); expect(screen.getByLabelText("Edit Markdown text")).toHaveValue("Unsaved useful work"); view.unmount();
  mount({...artifact, version: 1}, 3); fireEvent.click(screen.getByRole("tab", {name: "Edit"})); expect(screen.getByLabelText("Edit Markdown text")).toHaveValue("Unsaved useful work"); expect(screen.getByLabelText("Edit Markdown text")).toHaveAttribute("readonly"); expect(screen.getByRole("button", {name: "Save new version"})).toBeDisabled();
});
test("UI-only: export failure keeps the unsaved draft and does not call revision API", async () => {
  const fetcher = vi.fn(async (url: string) => url.includes("download") ? json({detail: "render_failed"}, 422) : json({items: []})); vi.stubGlobal("fetch", fetcher);
  mount(); fireEvent.click(screen.getByRole("tab", {name: "Edit"})); fireEvent.change(screen.getByLabelText("Edit Markdown text"), {target: {value: "Keep me"}}); fireEvent.click(screen.getByRole("link", {name: "Download"}));
  await screen.findByText(/Export failed/); expect(screen.getByLabelText("Edit Markdown text")).toHaveValue("Keep me"); expect(fetcher.mock.calls.some(([url]) => url.includes("revisions"))).toBe(false);
});
