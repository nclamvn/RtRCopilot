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
test("AW08 focused paragraph edits persist staged text across reload and apply only the selected region", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json({items: []}))); const view = mount(); fireEvent.click(screen.getByRole("tab", {name: "Edit"})); fireEvent.click(screen.getByRole("button", {name: "Focused edit"})); fireEvent.change(screen.getByLabelText("Paragraph to edit"), {target: {value: String(artifact.content!.indexOf("Old detail"))}});
  // The heading and paragraph belong to one Markdown block; choose the exact source region when needed.
  const source = screen.getByLabelText("Select source text") as HTMLTextAreaElement; source.setSelectionRange(artifact.content!.indexOf("Old detail"), artifact.content!.length); fireEvent.click(screen.getByRole("button", {name: "Edit selected text"})); fireEvent.change(screen.getByLabelText("Replacement text"), {target: {value: "New local detail"}}); expect(screen.getByRole("button", {name: "Save new version"})).toBeDisabled(); view.unmount();
  mount(); fireEvent.click(screen.getByRole("tab", {name: "Edit"})); expect(screen.getByLabelText("Replacement text")).toHaveValue("New local detail"); fireEvent.click(screen.getByRole("button", {name: "Apply to draft"})); expect(screen.getByLabelText("Document draft preview")).toHaveTextContent("New local detail"); fireEvent.click(screen.getByRole("button", {name: "Raw Markdown"})); expect(screen.getByLabelText("Edit Markdown text")).toHaveValue(artifact.content!.replace("Old detail", "New local detail")); fireEvent.click(screen.getByRole("button", {name: "Undo draft"})); expect(screen.getByLabelText("Edit Markdown text")).toHaveValue(artifact.content); fireEvent.click(screen.getByRole("button", {name: "Redo draft"})); expect(screen.getByLabelText("Edit Markdown text")).toHaveValue(artifact.content!.replace("Old detail", "New local detail"));
});
test("AW08 table grid preserves string values, atomic malformed paste and one-step paste undo", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json({items: []}))); const item = {...artifact, kind: "table" as const, filename: "ledger.csv", content: "ID,Value\n00431,91.125\n"}; mount(item); fireEvent.click(screen.getByRole("tab", {name: "Edit"})); fireEvent.change(screen.getByLabelText("Row 2, column 2"), {target: {value: "=1+1"}}); expect(screen.getByLabelText("Row 2, column 1")).toHaveValue("00431"); expect(screen.getByLabelText("Row 2, column 2")).toHaveValue("=1+1");
  fireEvent.focus(screen.getByLabelText("Row 2, column 1")); fireEvent.click(screen.getByText("Paste a rectangular area", {exact: true})); fireEvent.change(screen.getByLabelText("Area to paste"), {target: {value: "001\t92.125\n002"}}); fireEvent.click(screen.getByRole("button", {name: "Apply area to draft"})); expect(screen.getByRole("alert")).toHaveTextContent("rectangular"); expect(screen.getByLabelText("Row 2, column 1")).toHaveValue("00431"); expect(screen.getByLabelText("Area to paste")).toHaveValue("001\t92.125\n002");
  fireEvent.change(screen.getByLabelText("Area to paste"), {target: {value: "001\t92.125\n002\t=2+2"}}); fireEvent.click(screen.getByRole("button", {name: "Apply area to draft"})); expect(screen.getByLabelText("Row 3, column 2")).toHaveValue("=2+2"); fireEvent.click(screen.getByRole("button", {name: "Undo draft"})); expect(screen.queryByLabelText("Row 3, column 2")).toBeNull(); expect(screen.getByLabelText("Row 2, column 2")).toHaveValue("=1+1");
});
test("AW08 typing coalesces, draft storage can recover, and cross-tab draft is not overwritten", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json({items: []}))); mount(); fireEvent.click(screen.getByRole("tab", {name: "Edit"})); const editor = screen.getByLabelText("Edit Markdown text"); fireEvent.change(editor, {target: {value: "first"}}); fireEvent.change(editor, {target: {value: "first second"}}); fireEvent.click(screen.getByRole("button", {name: "Undo draft"})); expect(editor).toHaveValue(artifact.content);
  const storage = vi.spyOn(Storage.prototype, "setItem").mockImplementationOnce(() => {throw new Error("quota");}); fireEvent.change(editor, {target: {value: "kept in memory"}}); expect(screen.getByRole("alert")).toHaveTextContent("full or unavailable"); fireEvent.change(editor, {target: {value: "recovered browser draft"}}); expect(JSON.parse(localStorage.getItem("agent-workspace:artifact-draft:artifact-one")!).content).toBe("recovered browser draft"); storage.mockRestore();
  localStorage.setItem("agent-workspace:artifact-draft:artifact-one", JSON.stringify({content: "Other tab content", baseVersion: 2, requestId: "other-tab"})); fireEvent.change(editor, {target: {value: "This tab remains usable"}}); expect(editor).toHaveValue("This tab remains usable"); expect(screen.getByRole("alert")).toHaveTextContent("Another tab changed"); expect(JSON.parse(localStorage.getItem("agent-workspace:artifact-draft:artifact-one")!).content).toBe("Other tab content");
});
test("AW08 grid pages 20,000 cells without rendering every field and IDs stay unique", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json({items: []}))); const content = Array.from({length: 2000}, (_, row) => Array.from({length: 10}, (_, column) => `${row}-${column}`).join(",")).join("\n"); mount({...artifact, kind: "table", filename: "large.csv", content}); fireEvent.click(screen.getByRole("tab", {name: "Edit"})); expect(screen.getAllByRole("textbox")).toHaveLength(161); expect(screen.getByText(/Rows 1–20 of 2000/)).toBeVisible(); fireEvent.click(screen.getByRole("button", {name: "Next rows"})); expect(screen.getByLabelText("Row 21, column 1")).toHaveValue("20-0"); const ids = Array.from(document.querySelectorAll("[id]")).map(element => element.id); expect(new Set(ids).size).toBe(ids.length);
});
test("AW08 raw and cell edits retain unapplied buffers, including stale focused selections after reload", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json({items: []}))); const first = mount(); fireEvent.click(screen.getByRole("tab", {name: "Edit"})); fireEvent.click(screen.getByRole("button", {name: "Focused edit"})); const source = screen.getByLabelText("Select source text") as HTMLTextAreaElement; source.setSelectionRange(0, 7); fireEvent.click(screen.getByRole("button", {name: "Edit selected text"})); fireEvent.change(screen.getByLabelText("Replacement text"), {target: {value: "Replacement kept"}}); fireEvent.click(screen.getByRole("button", {name: "Raw Markdown"})); fireEvent.change(screen.getByLabelText("Edit Markdown text"), {target: {value: "# Changed source\n\nManual draft retained"}}); first.unmount();
  const second = mount(); fireEvent.click(screen.getByRole("tab", {name: "Edit"})); expect(screen.getByLabelText("Replacement text")).toHaveValue("Replacement kept"); fireEvent.click(screen.getByRole("button", {name: "Apply to draft"})); expect(screen.getByRole("alert")).toHaveTextContent("selected text changed"); expect(screen.getByLabelText("Select source text")).toHaveValue("# Changed source\n\nManual draft retained"); second.unmount();
  const table = {...artifact, id: "table-buffer", kind: "table" as const, content: "ID,Value\n001,2.50\n"}; mount(table); fireEvent.click(screen.getByRole("tab", {name: "Edit"})); fireEvent.click(screen.getByText("Paste a rectangular area", {exact: true})); fireEvent.change(screen.getByLabelText("Area to paste"), {target: {value: "unapplied\tarea"}}); fireEvent.change(screen.getByLabelText("Row 2, column 2"), {target: {value: "3.75"}}); expect(screen.getByLabelText("Area to paste")).toHaveValue("unapplied\tarea"); expect(JSON.parse(localStorage.getItem("agent-workspace:artifact-draft:table-buffer")!).buffers.paste).toBe("unapplied\tarea");
});
