// @vitest-environment jsdom
import React from "react";
import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import "@testing-library/jest-dom/vitest";
import {afterEach, beforeEach, expect, test, vi} from "vitest";
import {WorkspaceApp} from "./WorkspaceApp";
const json = (value: unknown) => new Response(JSON.stringify(value), {headers: {"content-type": "application/json"}});
beforeEach(() => {localStorage.clear(); vi.stubGlobal("React", React); Object.defineProperty(HTMLElement.prototype, "scrollTo", {configurable: true, value: vi.fn()});});
afterEach(() => {cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks();});
test("UI-only output revision replaces the whole version view with one editor and unique control IDs", async () => {
  let item = {id: "output-one", title: "Museum brief", filename: "museum.md", version: 1, content: "# First\n004173", kind: "document"};
  const warnings: string[] = []; vi.spyOn(console, "error").mockImplementation((...args) => {warnings.push(args.map(String).join(" "));});
  vi.stubGlobal("fetch", vi.fn(async (url: string, init?: RequestInit) => {
    if (url.endsWith("/session")) return json({authenticated: true});
    if (url.endsWith("/status")) return json({available: true, test_mode: true, model: "SIMULATION", reason: null, recovery: "mock"});
    if (url.includes("/workspaces?")) return json({items: [{id: "project", name: "Museum project", revision: 1, archived: false}]});
    if (url.endsWith("/messages") || url.endsWith("/files")) return json({items: []});
    if (url.endsWith("/artifacts")) return json({items: [item]});
    if (url.includes("/versions")) return json({items: Array.from({length: item.version}, (_, index) => ({version: index + 1, created_at: 1, characters: 20, run_id: null}))});
    if (url.includes("/dependencies")) return json({status: "unknown", dependencies: [], stale: false, reasons: [], coverage: "Unknown source lineage"});
    if (url.endsWith("/revisions")) {const body = JSON.parse(init!.body as string); item = {...item, content: body.content, version: item.version + 1}; return json(item);}
    if (url.includes("/artifacts/output-one")) return json(item);
    throw new Error(`Unexpected synthetic request: ${url}`);
  }));
  render(<WorkspaceApp/>); await screen.findByRole("heading", {name: "Museum project"});
  fireEvent.click(screen.getByRole("button", {name: /^Outputs/})); fireEvent.click(await screen.findByRole("button", {name: /Museum brief/})); await screen.findByLabelText("Artifact preview"); fireEvent.click(screen.getByRole("tab", {name: "Edit"}));
  fireEvent.change(screen.getByLabelText("Edit Markdown text"), {target: {value: "# Second\n004173 retained"}}); fireEvent.click(screen.getByRole("button", {name: "Save new version"}));
  await waitFor(() => expect(screen.getAllByLabelText("Artifact version")).toHaveLength(1)); await waitFor(() => expect(screen.getByLabelText("Artifact version")).toHaveValue("2")); expect(screen.getAllByLabelText("Artifact preview")).toHaveLength(1); expect(screen.getAllByLabelText("Output source freshness")).toHaveLength(1);
  fireEvent.click(screen.getByRole("button", {name: "Model & setup"})); expect(screen.queryByLabelText("Agent edit proposals")).toBeNull(); expect(screen.queryByLabelText("Selected output handoff")).toBeNull();
  const ids = Array.from(document.querySelectorAll("[id]")).map(element => element.id); expect(new Set(ids).size).toBe(ids.length); expect(warnings.filter(item => item.includes("same key"))).toEqual([]);
});
