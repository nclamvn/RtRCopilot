// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import {cleanup, fireEvent, render, screen, waitFor, within} from "@testing-library/react";
import React from "react";
import {afterEach, expect, test, vi} from "vitest";
import IntelligencePage from "./page";

const id = (n: string) =>
  `${n.repeat(8)}-${n.repeat(4)}-4${n.repeat(3)}-8${n.repeat(3)}-${n.repeat(12)}`;
const sha = "a".repeat(64);
const identity = {
  user_id: id("7"), email: "staff@rtrobotics.com",
  display_name: "RtR Staff", roles: ["staff"],
};
const briefing = {
  generated_at: "2026-08-15T05:00:00Z",
  request_id: "req-038",
  counts: {updates: 1, attention: 1, research: 1},
  items: [
    {
      item_id: "1".repeat(64), zone_label: "sot", kind: "attention",
      priority: "high", title: "RTR POLICY TRAVEL", summary: "server copy",
      observed_at: "2026-08-14T05:00:00Z",
      ask_query: "Giải thích chính sách công tác.",
      evidence: {
        zone_label: "sot", record_key: "RTR.POLICY.TRAVEL",
        source_key: "rtr.company", source_label: "Company policy registry",
        content_sha256: sha, locator: {record_key: "RTR.POLICY.TRAVEL"},
        record_version_id: id("1"), source_revision: 3,
        provenance_level: "approved_internal", verification_state: "approved",
        freshness_state: "stale", research_record_id: null,
        package_fingerprint: null, tier: null, corroboration_state: null,
      },
    },
    {
      item_id: "2".repeat(64), zone_label: "sot", kind: "update",
      priority: "normal", title: "HERA product roadmap",
      summary: "Roadmap hiện hành đã được phê duyệt.",
      observed_at: "2026-08-15T04:00:00Z",
      ask_query: "Giải thích tác động của roadmap HERA.",
      evidence: {
        zone_label: "sot", record_key: "RTR.HERA.ROADMAP",
        source_key: "rtr.company", source_label: "Product registry",
        content_sha256: sha, locator: {record_key: "RTR.HERA.ROADMAP"},
        record_version_id: id("2"), source_revision: 4,
        provenance_level: "approved_internal", verification_state: "verified",
        freshness_state: "current", research_record_id: null,
        package_fingerprint: null, tier: null, corroboration_state: null,
      },
    },
    {
      item_id: "3".repeat(64), zone_label: "research", kind: "research",
      priority: "normal", title: "precision agriculture signal",
      summary: "Tín hiệu nghiên cứu có nguồn đối chiếu.",
      observed_at: "2026-08-15T03:00:00Z",
      ask_query: "Đối chiếu tín hiệu nông nghiệp chính xác.",
      evidence: {
        zone_label: "research", record_key: "research.agri.signal",
        source_key: "theskywatch", source_label: "https://theskywatch.com/report",
        content_sha256: sha, locator: {url: "https://theskywatch.com/report"},
        record_version_id: null, source_revision: null, provenance_level: null,
        verification_state: null, freshness_state: null,
        research_record_id: id("3"), package_fingerprint: "b".repeat(64),
        tier: "P", corroboration_state: "corroborated",
      },
    },
  ],
};

function json(value: unknown, status = 200) {
  return new Response(JSON.stringify(value), {
    status, headers: {"content-type": "application/json"},
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

test("anonymous users never trigger a briefing data request", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    calls.push(String(input));
    return json({error: {code: "authentication_required"}}, 401);
  }));
  render(<IntelligencePage/>);
  await screen.findByText(/Đăng nhập bằng email công ty/);
  await waitFor(() => expect(calls).toEqual(["/api/auth/me"]));
  expect(calls.some(url => url.includes("intelligence/briefing"))).toBe(false);
});

test("renders separately labeled SOT, stale review and Research signals", async () => {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    if (url === "/api/auth/me") return json(identity);
    if (url === "/api/governance/intelligence/briefing?limit=16") {
      return json(briefing);
    }
    return json({}, 404);
  }));
  render(<IntelligencePage/>);

  expect(await screen.findByText(/Bản ghi này cần được rà soát độ mới/))
    .toBeInTheDocument();
  expect(screen.getByRole("heading", {name: "Tín hiệu"})).toBeInTheDocument();
  expect(screen.getByRole("button", {name: "Làm mới"})).toBeInTheDocument();
  expect(screen.getAllByText("1", {selector: "dd"})).toHaveLength(3);
  expect(screen.getAllByText("Nguồn sự thật").length).toBeGreaterThanOrEqual(2);
  expect(screen.getAllByText("Nghiên cứu · chưa là SOT").length).toBe(1);
  expect(screen.queryByText("server copy")).toBeNull();

  const researchButton = screen.getByRole("button", {name: /precision agriculture signal/i});
  fireEvent.click(researchButton);
  const rail = within(screen.getByRole("complementary", {name: "Nguồn đối chiếu"}));
  expect(rail.getByRole("heading", {name: "precision agriculture signal"}))
    .toBeInTheDocument();
  expect(rail.getByText("corroborated")).toBeInTheDocument();
  expect(rail.getByRole("link", {name: /Hỏi tiếp/}))
    .toHaveAttribute("href", "/ask?q=%C4%90%E1%BB%91i%20chi%E1%BA%BFu%20t%C3%ADn%20hi%E1%BB%87u%20n%C3%B4ng%20nghi%E1%BB%87p%20ch%C3%ADnh%20x%C3%A1c.");
});

test("a malformed mixed-zone payload fails closed", async () => {
  const invalid = {
    ...briefing,
    items: briefing.items.map((item, index) => index === 2 ? {
      ...item,
      evidence: {...item.evidence, record_version_id: id("9")},
    } : item),
  };
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => (
    String(input) === "/api/auth/me" ? json(identity) : json(invalid)
  )));
  render(<IntelligencePage/>);
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Không tải được bản tin có căn cứ.",
  );
  expect(screen.queryByText("Tín hiệu nghiên cứu có nguồn đối chiếu.")).toBeNull();
});
