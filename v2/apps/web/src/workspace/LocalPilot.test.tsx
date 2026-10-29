// @vitest-environment jsdom
import React from "react";
import "@testing-library/jest-dom/vitest";
import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import {afterEach, beforeEach, expect, test, vi} from "vitest";
import {diagnosticDownload, LocalPilot} from "./LocalPilot";

const fingerprint = "python-source-abc123abc123abc123ab";
const diagnostics = {format: "agent-workspace-diagnostics-v1", application: {version: "0.1.0-aw08", workflow_version: "workspace-aw06-v1", build_id: fingerprint}, runtime: {simulation: true, available: true, reason_code: null}, dependencies: {"pydantic-ai-slim": "2.62.0", dbos: "3.2.0", openai: "3.31.0", mcp: "1.26.0"}, counts: {workspaces: 2, files: 3, artifacts: 1, runs_active: 0}, checks: {network_tested: false, real_ai_accepted: false}, recovery: []};
const json = (value: unknown, status = 200) => new Response(JSON.stringify(value), {status, headers: {"content-type": "application/json"}});
beforeEach(() => {vi.stubGlobal("React", React);});
afterEach(() => {cleanup(); vi.unstubAllGlobals(); vi.restoreAllMocks();});

test("local guide is passive, explicit simulation and recovery never run a command or fetch automatically", () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher); render(<LocalPilot/>);
  expect(fetcher).not.toHaveBeenCalled(); fireEvent.click(screen.getByText("Your first local project", {exact: true})); expect(screen.getByText(/These commands copy scripted content/)).toBeVisible(); fireEvent.click(screen.getByText("Before an upgrade or recovery", {exact: true})); expect(screen.getByText(/Restore only to a new data directory/)).toBeVisible(); expect(screen.getByText(/This browser cannot run shell commands/)).toBeVisible(); expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
});
test("diagnostic allowlist omits private extras and replaces untrusted recovery prose with known text", () => {
  const safe = diagnosticDownload({...diagnostics, api_key: "SYNTHETIC-PRIVATE-CANARY", conversation: "SYNTHETIC-PRIVATE-CANARY", runtime: {...diagnostics.runtime, reason_code: "unknown-SYNTHETIC-PRIVATE-CANARY", path: "/private/SYNTHETIC-PRIVATE-CANARY"}, dependencies: {...diagnostics.dependencies, private: "SYNTHETIC-PRIVATE-CANARY"}, counts: {...diagnostics.counts, owner: "SYNTHETIC-PRIVATE-CANARY"}, recovery: [{code: "model_not_configured", hint: "SYNTHETIC-PRIVATE-CANARY"}, {code: "__proto__", hint: "SYNTHETIC-PRIVATE-CANARY"}]});
  expect(JSON.stringify(safe)).not.toContain("SYNTHETIC-PRIVATE-CANARY"); expect(safe.runtime.reason_code).toBe("runtime_unavailable"); expect(safe.recovery).toEqual([{code: "model_not_configured", hint: "No model is configured. Use explicit simulation for this local pilot."}]);
});
test.each([null, {...diagnostics, format: "unsupported"}, {...diagnostics, checks: {...diagnostics.checks, real_ai_accepted: true}}, {...diagnostics, counts: {...diagnostics.counts, files: -1}}, {...diagnostics, application: {...diagnostics.application, build_id: "/private/path"}}, {...diagnostics, dependencies: {...diagnostics.dependencies, dbos: undefined}}])("unsupported diagnostic shapes reject without inventing valid health: %j", value => {
  expect(() => diagnosticDownload(value)).toThrow(/not supported/);
});
test("runtime check requests only diagnostics and makes no download or provider call", async () => {
  const fetcher = vi.fn(async () => json(diagnostics)); vi.stubGlobal("fetch", fetcher); const url = vi.fn(); vi.stubGlobal("URL", {createObjectURL: url}); render(<LocalPilot/>);
  fireEvent.click(screen.getByRole("button", {name: "Check local runtime"})); await screen.findByText("0.1.0-aw08"); expect(screen.getByText(fingerprint)).toBeVisible(); expect(fetcher).toHaveBeenCalledExactlyOnceWith("/api/workspace/diagnostics", expect.objectContaining({method: "GET"})); expect(url).not.toHaveBeenCalled();
});
test("explicit safe diagnostic download reconstructs JSON, performs one request and no post", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json({...diagnostics, raw_logs: "SYNTHETIC-PRIVATE-CANARY"}))); let downloaded: Blob | undefined; const create = vi.fn((blob: Blob) => {downloaded = blob; return "blob:synthetic-local";}); vi.stubGlobal("URL", {createObjectURL: create, revokeObjectURL: vi.fn()}); const click = vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {}); render(<LocalPilot/>);
  fireEvent.click(screen.getByRole("button", {name: "Download safe diagnostics"})); await screen.findByText(/Diagnostic file downloaded locally/); expect(create).toHaveBeenCalledOnce(); expect(click).toHaveBeenCalledOnce(); expect(downloaded?.type).toBe("application/json");
  const body = await new Promise<string>((resolve, reject) => {const reader = new FileReader(); reader.onload = () => resolve(String(reader.result)); reader.onerror = reject; reader.readAsText(downloaded!);}); expect(JSON.parse(body)).toEqual(diagnostics); expect(body).not.toContain("SYNTHETIC-PRIVATE-CANARY");
});
test("API outage remains actionable, leaves guide usable and never prints transport exceptions", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => {throw new Error("SYNTHETIC-PRIVATE-CANARY /home/private");})); render(<LocalPilot/>); fireEvent.click(screen.getByRole("button", {name: "Check local runtime"})); await screen.findByRole("alert"); expect(screen.getByRole("alert")).toHaveTextContent("Saved work is unchanged"); expect(screen.getByRole("alert")).toHaveTextContent("Do not delete your data directory"); expect(screen.queryByText(/SYNTHETIC-PRIVATE-CANARY/)).not.toBeInTheDocument(); expect(screen.getByText("Your first local project", {exact: true})).toBeVisible();
});
test("unmounted setup cannot download a delayed diagnostic response", async () => {
  let release: ((value: Response) => void) | undefined; vi.stubGlobal("fetch", vi.fn(() => new Promise<Response>(resolve => {release = resolve;}))); const create = vi.fn(); vi.stubGlobal("URL", {createObjectURL: create}); const view = render(<LocalPilot/>); fireEvent.click(screen.getByRole("button", {name: "Download safe diagnostics"})); await waitFor(() => expect(release).toBeTypeOf("function")); view.unmount(); release!(json(diagnostics)); await new Promise(resolve => setTimeout(resolve, 0)); expect(create).not.toHaveBeenCalled();
});
test("duplicate download click uses one request and one download, without dispatch", async () => {
  let release: ((value: Response) => void) | undefined; const fetcher = vi.fn(() => new Promise<Response>(resolve => {release = resolve;})); vi.stubGlobal("fetch", fetcher); const create = vi.fn(() => "blob:synthetic-once"); vi.stubGlobal("URL", {createObjectURL: create, revokeObjectURL: vi.fn()}); vi.spyOn(HTMLAnchorElement.prototype, "click").mockImplementation(() => {}); render(<LocalPilot/>); const button = screen.getByRole("button", {name: "Download safe diagnostics"}); fireEvent.click(button); fireEvent.click(button); expect(fetcher).toHaveBeenCalledTimes(1); release!(json(diagnostics)); await screen.findByText(/Diagnostic file downloaded locally/); expect(create).toHaveBeenCalledTimes(1);
});
test("no-model diagnostics keeps first-project guide available and renders known recovery only", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json({...diagnostics, runtime: {simulation: false, available: false, reason_code: "model_not_configured"}, recovery: [{code: "model_not_configured", hint: "SYNTHETIC-PRIVATE-HINT"}]}))); render(<LocalPilot/>); fireEvent.click(screen.getByRole("button", {name: "Check local runtime"})); await screen.findByText("No model configured · Unavailable"); expect(screen.getByLabelText("Local recovery guidance")).toHaveTextContent("No model is configured"); expect(screen.queryByText("SYNTHETIC-PRIVATE-HINT")).not.toBeInTheDocument(); expect(screen.getByText("Your first local project", {exact: true})).toBeVisible();
});
test("malformed successful response never becomes a downloadable healthy diagnostic", async () => {
  vi.stubGlobal("fetch", vi.fn(async () => json({...diagnostics, application: {...diagnostics.application, build_id: "SYNTHETIC-PRIVATE-FREEFORM-BUILD"}}))); const create = vi.fn(); vi.stubGlobal("URL", {createObjectURL: create}); render(<LocalPilot/>); fireEvent.click(screen.getByRole("button", {name: "Download safe diagnostics"})); await screen.findByRole("alert"); expect(create).not.toHaveBeenCalled(); expect(screen.queryByLabelText("Local runtime details")).not.toBeInTheDocument(); expect(screen.queryByText(/SYNTHETIC-PRIVATE-FREEFORM-BUILD/)).not.toBeInTheDocument();
});
