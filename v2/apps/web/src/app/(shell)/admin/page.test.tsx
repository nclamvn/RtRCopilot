// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import React from "react";
import {afterEach, expect, test, vi} from "vitest";
import {I18nProvider} from "../../../i18n/provider";
import AdminPage from "./page";

const identity = {user_id: "11111111-1111-4111-8111-111111111111", email: "admin@rtr.vn", display_name: "Admin RtR", roles: ["admin"]};
const health = {computed_at: "2026-08-04T08:00:00Z", families: [
  {family: "ingestion", job_counts: {completed: 4}, outbox_counts: {published: 4}, recent_failures: []},
  {family: "render", job_counts: {failed: 1}, outbox_counts: {}, recent_failures: [{job_id: "22222222-2222-4222-8222-222222222222", kind: "render", status: "failed", error_code: "renderer_timeout", attempt: null, occurred_at: "2026-08-04T07:00:00Z"}]},
  {family: "reindex", job_counts: {}, outbox_counts: {}, recent_failures: []},
]};
const subject = {user_id: "33333333-3333-4333-8333-333333333333", issuer: "https://accounts.example", email: "staff@rtr.vn", display_name: "Staff RtR", status: "active", security_version: 2, roles: ["staff"], groups: [], last_seen_at: "2026-08-04T08:00:00Z"};
const pilot = {computed_at: "2026-08-04T08:00:00Z",
  sot: {active_records: 219, strict_records: 8, caveated_records: 211, current_records: 219, stale_records: 0, named_owner_records: 0, placeholder_owner_records: 219, caveated_named_owner_records: 0, caveated_placeholder_owner_records: 211, high_risk_records: 20, high_risk_caveated_records: 12, zone_masquerade_findings: 0},
  files: {documents: 6, versions: 6, representative_versions: 0, ready_versions: 6, indexed_versions: 6, viewer_families: {}, original_checksum_mismatches: 0, rendition_lineage_mismatches: 0},
  templates: {templates: 0, approved_templates: 0, locked_bindings: 0, official_or_legal_approved: 0},
  research: {active_sources: 0, imported_packages: 0, records: 0, tiers: {}, corroboration: {}},
  question_count: 32, gates: [
    {gate_key: "sot_gold_baseline", target: 8, actual: 8, state: "met", detail: "Strict records retained"},
    {gate_key: "caveated_named_owners", target: 211, actual: 0, state: "blocked", detail: "Human owners required"},
  ], production_boundary: "local_dev_only"};

afterEach(() => {cleanup(); vi.unstubAllGlobals();});

async function responseFor(input: URL | RequestInfo, init?: RequestInit) {
  const url = String(input);
  if (url === "/api/auth/me") return Response.json(identity);
  if (url.includes("jobs/health")) return Response.json(health);
  if (url.includes("pilot-readiness")) return Response.json(pilot);
  if (url.includes("subjects/") && init?.method === "POST") return Response.json({...subject, security_version: 3, roles: ["staff", "curator"]});
  if (url.includes("subjects")) return Response.json([subject]);
  if (url.includes("research-sources")) return Response.json([]);
  if (url.includes("settings")) return Response.json([]);
  throw new Error(`unexpected ${url}`);
}

test("anonymous session never calls an admin API", async () => {
  const fetch = vi.fn(async () => new Response(null, {status: 401})); vi.stubGlobal("fetch", fetch);
  render(<AdminPage/>);
  expect(await screen.findByRole("heading", {name: "Cần đăng nhập công ty"})).toBeInTheDocument();
  expect(fetch).toHaveBeenCalledTimes(1); expect(fetch).toHaveBeenCalledWith("/api/auth/me", expect.anything());
});

test("admin sees live job ledger and explicit failures", async () => {
  vi.stubGlobal("fetch", vi.fn(responseFor)); render(<AdminPage/>);
  expect(await screen.findByRole("heading", {name: "Sức khỏe job và worker"})).toBeInTheDocument();
  expect(await screen.findByText("renderer_timeout")).toBeInTheDocument();
  expect(screen.getByText("CẦN CHÚ Ý")).toBeInTheDocument();
  expect(screen.getByText(/SOT, audit log/)).toBeInTheDocument();
});

test("pilot corpus panel renders live gates and the local-only boundary", async () => {
  vi.stubGlobal("fetch", vi.fn(responseFor)); render(<AdminPage/>);
  fireEvent.click(await screen.findByRole("button", {name: /Corpus pilot/}));
  expect(await screen.findByRole("heading", {name: "Corpus pilot và provenance"})).toBeInTheDocument();
  expect(screen.getByText(/211 fact có caveat/)).toBeInTheDocument();
  expect(screen.getByText("caveated_named_owners")).toBeInTheDocument();
  expect(screen.getByText(/LOCAL \/ DEV ONLY/)).toBeInTheDocument();
});

test("403 is persistent and does not drop the authenticated identity", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: URL | RequestInfo) => String(input) === "/api/auth/me"
    ? Response.json(identity) : Response.json({error: {code: "admin_required", message: "Denied"}, request_id: "req-denied"}, {status: 403})));
  render(<AdminPage/>);
  expect(await screen.findByRole("alert")).toHaveTextContent("admin_required · req-denied");
  expect(screen.getByText("CONTROL PLANE · LIVE")).toBeInTheDocument();
  expect(screen.queryByRole("heading", {name: "Cần đăng nhập công ty"})).not.toBeInTheDocument();
});

test("binding change sends a bounded audited payload and replaces returned subject", async () => {
  const fetch = vi.fn(responseFor); vi.stubGlobal("fetch", fetch); render(<AdminPage/>);
  fireEvent.click(await screen.findByRole("button", {name: /Tài khoản/}));
  const subjectButton = (await screen.findByText("Staff RtR")).closest("button");
  expect(subjectButton).toBeTruthy(); fireEvent.click(subjectButton!);
  fireEvent.change(screen.getByLabelText("Khóa role hoặc group"), {target: {value: "curator"}});
  fireEvent.change(screen.getByLabelText(/Lý do thay đổi/), {target: {value: "approved coverage duty"}});
  fireEvent.click(screen.getByRole("button", {name: "Áp dụng thay đổi"}));
  await waitFor(() => expect(fetch).toHaveBeenCalledWith(expect.stringContaining("/bindings"), expect.objectContaining({method: "POST"})));
  const call = fetch.mock.calls.find(([url, init]) => String(url).includes("/bindings") && init?.method === "POST");
  expect(JSON.parse(String(call?.[1]?.body))).toEqual({binding: "role", key: "curator", operation: "assign", reason: "approved coverage duty"});
  expect(await screen.findByText("Đã lưu · audit trail đã được tạo")).toBeInTheDocument();
  expect(screen.getByText(/security v3/)).toBeInTheDocument();
});

test("workspace is translated under the English locale", async () => {
  vi.stubGlobal("fetch", vi.fn(responseFor));
  render(<I18nProvider initialLocale="en"><AdminPage/></I18nProvider>);
  expect(await screen.findByRole("heading", {name: "Job and worker health"})).toBeInTheDocument();
  expect(screen.getByRole("navigation", {name: "Administration surfaces"})).toBeInTheDocument();
});
