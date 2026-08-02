// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import {cleanup, render, screen, waitFor, within} from "@testing-library/react";
import React from "react";
import {afterEach, expect, test, vi} from "vitest";
import KnowledgeOpsPage from "./page";

const sha = "a".repeat(64);
const id = (n: string) =>
  `${n.repeat(8)}-${n.repeat(4)}-4${n.repeat(3)}-8${n.repeat(3)}-${n.repeat(12)}`;
const identity = {
  user_id: id("7"), email: "curator@rtrobotics.com",
  display_name: "RtR Curator", roles: ["curator"],
};
const dashboard = {
  computed_at: "2026-08-01T00:00:00Z",
  coverage: {zone_label: "sot", total_records: 12, by_source_key: {kernel: 12},
    by_owner: {curator: 12}, by_classification: {internal: 12}},
  freshness: {zone_label: "sot", total: 3, expiring: 2, expired: 1,
    assigned: 1, unassigned: 2},
  gap_flow: {zone_label: "sot", open_total: 4, closed_total: 6, overdue: 1,
    by_state: {open: 4}, aging: {under_24h: 4}},
  research_intake: {zone_label: "research", sources_total: 2, sources_active: 1,
    packages_by_state: {imported: 3}, records_by_tier: {P: 5}},
  graduation: {zone_label: "research", proposed: 2, approved: 1,
    rejected: 0, submitted: 1},
};
const emptyQueue = (kind: string) => ({
  queue_kind: kind, computed_at: "2026-08-01T00:00:00Z", entries: [],
  aggregates: {total: 0, by_status: {}, assigned: 0, unassigned: 0},
  next_cursor: null,
});
const researchPackage = {
  zone_label: "research", package_id: id("2"), source_key: "refinery.industry",
  fingerprint: sha, payload_sha256: sha, captured_at: "2026-07-01T00:00:00Z",
  snapshot_scope: "industry-vn", adapter_version: "refinery-1.2",
  tier_composition: {P: 1}, import_state: "imported", rejection_code: null,
  record_count: 1, received_at: "2026-07-02T00:00:00Z",
  imported_at: "2026-07-02T00:01:00Z",
};
const researchRecord = {
  zone_label: "research", research_record_id: id("3"), package_id: id("2"),
  package_fingerprint: sha, source_key: "refinery.industry",
  record_key: "vendor.abb.profile", version_ordinal: 1, tier: "P",
  content: {name: "ABB"}, searchable_text: "ABB robotics",
  evidence: [{source_url: "https://example.com/a", locator: {page: 1},
    quoted_text: "ABB manufactures industrial robots.", checksum: sha}],
  corroboration_state: "corroborated", content_sha256: sha,
  created_at: "2026-07-30T00:00:00Z",
};

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status, headers: {"content-type": "application/json"},
  });
}

function stubFetch(routes: Record<string, () => Response>) {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    if (url === "/api/auth/me") return json(identity);
    const handler = routes[url.replace(/^\/api\/governance\//, "")];
    if (handler) return handler();
    return json({error: {code: "not_found", message: ""}, request_id: "req-0"}, 404);
  }));
  return calls;
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  history.replaceState({}, "", "/");
});

test("anonymous identity gate never requests governance data", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    calls.push(String(input));
    return json({error: {code: "authentication_required"}}, 401);
  }));
  render(<KnowledgeOpsPage/>);
  await screen.findByRole("link", {name: "Đăng nhập công ty"});
  expect(screen.getByRole("heading", {name: "Vận hành tri thức"})).toBeInTheDocument();
  await waitFor(() => expect(calls).toEqual(["/api/auth/me"]));
  expect(calls.some(url => url.includes("/api/governance/"))).toBe(false);
});

test("dashboard renders self-labeled tiles with server-provided zone chips", async () => {
  stubFetch({
    "governance/dashboard": () => json(dashboard),
    "governance/queues/conflict?limit=1": () => json(emptyQueue("conflict")),
    "governance/queues/owner-review?limit=1": () => json(emptyQueue("owner_review")),
  });
  render(<KnowledgeOpsPage/>);
  const surface = within(await screen.findByRole("region", {name: "Bàn xử lý"}));
  await surface.findByRole("heading", {name: "Bảng điều hành tri thức"});
  await surface.findByRole("heading", {name: "Phễu nâng cấp"});
  expect(surface.getAllByText("SOT").length).toBe(3);
  expect(surface.getAllByText("RESEARCH").length).toBe(2);
  expect(surface.getByText("Tiếp nhận nghiên cứu")).toBeInTheDocument();
  expect(screen.getByRole("navigation", {name: "Sổ hàng đợi"}))
    .toHaveTextContent("1 quá hạn SLA");
});

test("policy denial renders a typed denied state, not an empty dashboard", async () => {
  stubFetch({
    "governance/dashboard": () => json({
      error: {code: "curator_required", message: ""}, request_id: "req-77",
    }, 403),
    "governance/queues/conflict?limit=1": () => json(emptyQueue("conflict")),
    "governance/queues/owner-review?limit=1": () => json(emptyQueue("owner_review")),
  });
  render(<KnowledgeOpsPage/>);
  const alerts = await screen.findAllByRole("alert");
  expect(alerts.some(alert =>
    alert.textContent?.includes("Bị từ chối theo chính sách")
    && alert.textContent.includes("curator_required")
    && alert.textContent.includes("req-77"))).toBe(true);
});

test("upstream failure renders a typed error with retry", async () => {
  stubFetch({
    "governance/dashboard": () => json({
      error: {code: "governance_service_unavailable", message: ""}, request_id: "req-9",
    }, 503),
    "governance/queues/conflict?limit=1": () => json(emptyQueue("conflict")),
    "governance/queues/owner-review?limit=1": () => json(emptyQueue("owner_review")),
  });
  render(<KnowledgeOpsPage/>);
  const alerts = await screen.findAllByRole("alert");
  expect(alerts.some(alert =>
    alert.textContent?.includes("governance_service_unavailable"))).toBe(true);
  expect(screen.getAllByRole("button", {name: "Thử lại"}).length).toBeGreaterThan(0);
});

test("empty gap queue shows the scoped empty state", async () => {
  history.replaceState({}, "", "/knowledge-ops?view=gaps");
  stubFetch({
    "governance/dashboard": () => json(dashboard),
    "governance/queues/conflict?limit=1": () => json(emptyQueue("conflict")),
    "governance/queues/owner-review?limit=1": () => json(emptyQueue("owner_review")),
    "gaps?limit=50": () => json({items: [], next_cursor: null}),
  });
  render(<KnowledgeOpsPage/>);
  await screen.findByText("Không có khoảng trống trong phạm vi được cấp quyền.");
});

test("zone-chip regression: research content renders the research chip and never an SOT label", async () => {
  history.replaceState(
    {}, "",
    `/knowledge-ops?view=research&package=${id("2")}&record=${id("3")}`,
  );
  stubFetch({
    "governance/dashboard": () => json(dashboard),
    "governance/queues/conflict?limit=1": () => json(emptyQueue("conflict")),
    "governance/queues/owner-review?limit=1": () => json(emptyQueue("owner_review")),
    "research/packages?limit=50": () => json({items: [researchPackage], next_cursor: null}),
    [`research/packages/${id("2")}/records?limit=50`]: () =>
      json({items: [researchRecord], next_cursor: null}),
    [`research/records/${id("3")}`]: () => json(researchRecord),
  });
  render(<KnowledgeOpsPage/>);
  const surface = within(await screen.findByRole("region", {name: "Bàn xử lý"}));
  await surface.findByRole("heading", {name: "vendor.abb.profile"});
  expect(surface.getAllByText("RESEARCH").length).toBeGreaterThan(0);
  expect(surface.queryByText("SOT")).toBeNull();
  const rail = within(screen.getByRole("complementary", {name: "Bằng chứng và xuất xứ"}));
  expect(rail.getAllByText("RESEARCH").length).toBeGreaterThan(0);
  expect(rail.queryByText("SOT")).toBeNull();
  expect(surface.getByText("ABB manufactures industrial robots.")).toBeInTheDocument();
});

test("zone-chip regression: a forged SOT label on research content blocks rendering", async () => {
  history.replaceState(
    {}, "",
    `/knowledge-ops?view=research&package=${id("2")}&record=${id("3")}`,
  );
  stubFetch({
    "governance/dashboard": () => json(dashboard),
    "governance/queues/conflict?limit=1": () => json(emptyQueue("conflict")),
    "governance/queues/owner-review?limit=1": () => json(emptyQueue("owner_review")),
    "research/packages?limit=50": () => json({items: [researchPackage], next_cursor: null}),
    [`research/packages/${id("2")}/records?limit=50`]: () =>
      json({items: [researchRecord], next_cursor: null}),
    [`research/records/${id("3")}`]: () => json({...researchRecord, zone_label: "sot"}),
  });
  render(<KnowledgeOpsPage/>);
  const alerts = await screen.findAllByRole("alert");
  expect(alerts.some(alert => alert.textContent?.includes("contract_violation"))).toBe(true);
  expect(screen.queryByText("ABB manufactures industrial robots.")).toBeNull();
  expect(screen.queryByRole("heading", {name: "vendor.abb.profile"})).toBeNull();
});
