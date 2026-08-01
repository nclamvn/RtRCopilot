import {expect, Page, test} from "@playwright/test";

const gapId = "11111111-1111-4111-8111-111111111111";
const packageId = "22222222-2222-4222-8222-222222222222";
const recordId = "33333333-3333-4333-8333-333333333333";
const proposalId = "44444444-4444-4444-8444-444444444444";
const curatorId = "55555555-5555-4555-8555-555555555555";
const peerId = "66666666-6666-4666-8666-666666666666";
const versionId = "77777777-7777-4777-8777-777777777777";
const publishPackageId = "88888888-8888-4888-8888-888888888888";
const sha = "a".repeat(64);

type GapMock = {
  lifecycle: string; owner: string | null; due: string | null;
  resolving: string | null;
  transitions: Array<{from_state: string; to_state: string; reason: string}>;
};

function gapJson(state: GapMock) {
  return {
    gap_id: gapId, question_fingerprint: sha,
    sanitized_question: "Chính sách bảo hành robot RtR là gì?",
    sanitized_summary: "Bảo hành robot", reason_category: "no_evidence",
    classification: "internal", requester_id: peerId,
    owner_subject_id: state.owner, routing_key: "governance.gap",
    occurrence_count: 3, lifecycle: state.lifecycle, origin: "honest_null",
    priority: "high", first_seen_at: "2026-07-29T00:00:00Z",
    last_seen_at: "2026-07-31T00:00:00Z", triaged_at: null, assigned_at: null,
    due_at: state.due, answered_at: null, closed_at: null,
    resolving_version_id: state.resolving, decline_reason: null,
  };
}

const dashboard = {
  computed_at: "2026-08-01T00:00:00Z",
  coverage: {zone_label: "sot", total_records: 24, by_source_key: {kernel: 24},
    by_owner: {curator: 24}, by_classification: {internal: 20, restricted: 4}},
  freshness: {zone_label: "sot", total: 5, expiring: 3, expired: 2,
    assigned: 1, unassigned: 4},
  gap_flow: {zone_label: "sot", open_total: 4, closed_total: 9, overdue: 1,
    by_state: {open: 3, triaged: 1}, aging: {under_24h: 2, days_1_3: 2}},
  research_intake: {zone_label: "research", sources_total: 2, sources_active: 2,
    packages_by_state: {imported: 3, rejected: 1}, records_by_tier: {P: 5, S: 2}},
  graduation: {zone_label: "research", proposed: 1, approved: 1,
    rejected: 0, submitted: 1},
};

const researchPackage = {
  zone_label: "research", package_id: packageId, source_key: "refinery.industry",
  fingerprint: sha, payload_sha256: sha, captured_at: "2026-07-01T00:00:00Z",
  snapshot_scope: "industry-vn-2026", adapter_version: "refinery-1.2",
  tier_composition: {P: 1}, import_state: "imported", rejection_code: null,
  record_count: 1, received_at: "2026-07-02T00:00:00Z",
  imported_at: "2026-07-02T00:01:00Z",
};

const researchRecord = {
  zone_label: "research", research_record_id: recordId, package_id: packageId,
  package_fingerprint: sha, source_key: "refinery.industry",
  record_key: "vendor.abb.profile", version_ordinal: 1, tier: "P",
  content: {name: "ABB", country: "CH/SE"}, searchable_text: "ABB robotics",
  evidence: [{source_url: "https://example.com/abb", locator: {page: 4},
    quoted_text: "ABB manufactures industrial robots for welding lines.",
    checksum: sha}],
  corroboration_state: "corroborated", content_sha256: sha,
  created_at: "2026-07-30T00:00:00Z",
};

function proposalJson(state: {state: string; publish: string | null; decidedBy: string | null}) {
  return {
    proposal_id: proposalId, research_record_ids: [recordId],
    claim_draft: {claim_text: "ABB là nhà cung cấp robot hàn được RtR tích hợp",
      classification: "internal"},
    target_record_key: "partners.abb", proposer_subject_id: peerId,
    rationale: "Đủ bằng chứng tier P", state: state.state,
    decided_by: state.decidedBy, decision_reason: null,
    attestation_hash: state.state === "approved" ? sha : null,
    publish_package_id: state.publish, supersedes_proposal_id: null,
    proposed_at: "2026-07-30T00:00:00Z",
    decided_at: state.state === "proposed" ? null : "2026-08-01T00:00:00Z",
  };
}

function queuePage(kind: string, entries: unknown[], byStatus: Record<string, number>) {
  return {
    queue_kind: kind, computed_at: "2026-08-01T00:00:00Z", entries,
    aggregates: {
      total: entries.length, by_status: byStatus,
      assigned: 0, unassigned: entries.length,
    },
    next_cursor: null,
  };
}

async function mockKnowledgeOps(page: Page) {
  const gap: GapMock = {
    lifecycle: "open", owner: null, due: null, resolving: null, transitions: [],
  };
  const proposal = {state: "proposed", publish: null as string | null,
    decidedBy: null as string | null};
  await page.route("**/api/auth/me", route => route.fulfill({json: {
    user_id: curatorId, email: "curator@rtrobotics.com",
    display_name: "RtR Curator", roles: ["curator"],
  }}));
  await page.route("**/api/governance/**", async route => {
    const request = route.request();
    const url = new URL(request.url());
    const path = url.pathname;
    if (path === "/api/governance/governance/dashboard") {
      return route.fulfill({json: dashboard});
    }
    if (path.startsWith("/api/governance/governance/queues/freshness")) {
      return route.fulfill({json: queuePage("freshness", [{
        queue_kind: "freshness", record_id: peerId, record_key: "company.warranty",
        record_version_id: versionId, owner_subject_id: curatorId,
        classification: "internal", status: "expired",
        sort_at: "2026-07-20T00:00:00Z", effective_to: "2026-07-20T00:00:00Z",
        review_due_at: null, sides: [], task: null,
      }], {expired: 1})});
    }
    if (path.startsWith("/api/governance/governance/queues/conflict")) {
      return route.fulfill({json: queuePage("conflict", [], {})});
    }
    if (path.startsWith("/api/governance/governance/queues/owner-review")) {
      return route.fulfill({json: queuePage("owner_review", [], {})});
    }
    if (path === "/api/governance/gaps") {
      return route.fulfill({json: {items: [gapJson(gap)], next_cursor: null}});
    }
    if (path === `/api/governance/gaps/${gapId}`) {
      return route.fulfill({json: {
        gap: gapJson(gap),
        transitions: gap.transitions.map((item, index) => ({
          sequence: index + 1,
          transition_id: `99999999-9999-4999-8999-${String(index).padStart(12, "0")}`,
          gap_id: gapId, from_state: item.from_state, to_state: item.to_state,
          actor_subject_id: curatorId, reason: item.reason,
          occurred_at: "2026-08-01T01:00:00Z",
        })),
      }});
    }
    if (path.startsWith(`/api/governance/gaps/${gapId}/`) && request.method() === "POST") {
      const operation = path.split("/").at(-1);
      const body = request.postDataJSON() as Record<string, string>;
      const from = gap.lifecycle;
      if (operation === "triage") gap.lifecycle = "triaged";
      if (operation === "assign") {
        gap.lifecycle = "assigned";
        gap.owner = body.owner_subject_id;
        gap.due = "2026-08-03T00:00:00Z";
      }
      if (operation === "answer") {
        gap.lifecycle = "answered";
        gap.resolving = body.resolving_version_id;
      }
      if (operation === "decline") gap.lifecycle = "declined";
      gap.transitions.push({
        from_state: from, to_state: gap.lifecycle, reason: body.reason,
      });
      return route.fulfill({json: gapJson(gap)});
    }
    if (path === "/api/governance/research/packages") {
      return route.fulfill({json: {items: [researchPackage], next_cursor: null}});
    }
    if (path === `/api/governance/research/packages/${packageId}/records`) {
      return route.fulfill({json: {items: [researchRecord], next_cursor: null}});
    }
    if (path === `/api/governance/research/records/${recordId}`) {
      return route.fulfill({json: researchRecord});
    }
    if (path === "/api/governance/graduation/proposals" && request.method() === "POST") {
      return route.fulfill({status: 201, json: proposalJson(proposal)});
    }
    if (path === "/api/governance/graduation/proposals") {
      return route.fulfill({json: {items: [proposalJson(proposal)], next_cursor: null}});
    }
    if (path === `/api/governance/graduation/proposals/${proposalId}/decide`
        && request.method() === "POST") {
      const body = request.postDataJSON() as {decision: string};
      proposal.state = body.decision;
      proposal.decidedBy = curatorId;
      if (body.decision === "approved") proposal.publish = publishPackageId;
      return route.fulfill({json: proposalJson(proposal)});
    }
    if (path === `/api/governance/graduation/proposals/${proposalId}`) {
      return route.fulfill({json: proposalJson(proposal)});
    }
    return route.fulfill({status: 404, json: {
      error: {code: "not_found", message: ""}, request_id: "req-0",
    }});
  });
}

test("curator completes triage → assign → answer keyboard-reachable flow", async ({page}) => {
  await mockKnowledgeOps(page);
  await page.goto("/knowledge-ops?view=gaps");
  await page.getByRole("button", {name: /Bảo hành robot/}).click();
  await expect(page.getByRole("heading", {name: "Chính sách bảo hành robot RtR là gì?"}))
    .toBeVisible();
  await page.getByLabel("Lý do thao tác").fill("Câu hỏi lặp lại 3 lần");
  await page.getByRole("button", {name: "Nhận xử lý"}).click();
  await expect(page.locator(".transition-history")).toContainText("open → triaged");
  await page.getByLabel("Giao cho (subject ID)").fill(peerId);
  await page.getByRole("button", {name: "Giao cho", exact: true}).click();
  await expect(page.locator(".transition-history")).toContainText("triaged → assigned");
  await expect(page.getByRole("complementary", {name: "Bằng chứng và xuất xứ"}))
    .toContainText("internal");
  await page.getByLabel("Bản ghi SOT đã kích hoạt (version ID)").fill(versionId);
  await page.getByRole("button", {name: "Trả lời bằng bản ghi đã phát hành"}).click();
  await expect(page.locator(".transition-history")).toContainText("assigned → answered");
  await page.screenshot({path: "test-results/tip010-gap-flow.png", fullPage: true});
});

test("research package inspection shows tier, snapshot and verbatim evidence — research chip only", async ({page}) => {
  await mockKnowledgeOps(page);
  await page.goto("/knowledge-ops?view=research");
  await page.getByRole("button", {name: /industry-vn-2026/}).click();
  await page.getByRole("button", {name: /vendor.abb.profile/}).click();
  const surface = page.getByRole("region", {name: "Bàn xử lý"});
  await expect(surface.getByRole("heading", {name: "vendor.abb.profile"})).toBeVisible();
  await expect(surface).toContainText("ABB manufactures industrial robots");
  await expect(surface.getByText("RESEARCH").first()).toBeVisible();
  await expect(surface.getByText("SOT", {exact: true})).toHaveCount(0);
  const rail = page.getByRole("complementary", {name: "Bằng chứng và xuất xứ"});
  await expect(rail).toContainText("Tier");
  await expect(rail).toContainText(sha.slice(0, 16));
  await expect(rail.getByText("SOT", {exact: true})).toHaveCount(0);
  await page.screenshot({path: "test-results/tip010-research-record.png", fullPage: true});
});

test("propose → decide stops at the publish gate with separation-of-duties messaging", async ({page}) => {
  await mockKnowledgeOps(page);
  await page.goto("/knowledge-ops?view=research");
  await page.getByRole("button", {name: /industry-vn-2026/}).click();
  await page.getByRole("button", {name: /vendor.abb.profile/}).click();
  await page.getByRole("button", {name: "Đề xuất nâng cấp"}).click();
  await page.getByLabel("Nội dung claim").fill("ABB là nhà cung cấp robot hàn");
  await expect(page.getByText("một curator khác quyết định")).toBeVisible();
  await page.getByRole("button", {name: "Đề xuất nâng cấp"}).click();
  await expect(page.getByText("Đã tạo đề xuất nâng cấp")).toBeVisible();
  await page.getByRole("button", {name: /Nâng cấp/}).click();
  await page.getByRole("button", {name: /partners.abb/}).click();
  const crossing = page.locator(".gated-crossing figcaption");
  await expect(crossing).toHaveAttribute("data-phase", "proposed");
  await expect(page.getByText("người đề xuất không thể tự quyết định")).toBeVisible();
  await page.getByLabel("Lý do quyết định").fill("Bằng chứng đầy đủ, cho qua cổng");
  await page.getByRole("button", {name: "Đưa vào cổng phát hành"}).click();
  await expect(crossing).toHaveAttribute("data-phase", "approved_staged");
  await expect(crossing).toContainText("dừng tại cổng phát hành SOT");
  await expect(page.getByRole("complementary", {name: "Bằng chứng và xuất xứ"}))
    .toContainText(publishPackageId);
  await page.screenshot({path: "test-results/tip010-gated-crossing.png", fullPage: true});
});

test("dashboard tiles render server-labeled zones and live counts", async ({page}) => {
  await mockKnowledgeOps(page);
  await page.goto("/knowledge-ops");
  const surface = page.getByRole("region", {name: "Bàn xử lý"});
  await expect(surface.getByRole("heading", {name: "Bảng điều hành tri thức"})).toBeVisible();
  await expect(surface.getByText("SOT", {exact: true})).toHaveCount(3);
  await expect(surface.getByText("RESEARCH", {exact: true})).toHaveCount(2);
  await expect(surface).toContainText("24");
  await expect(page.getByRole("navigation", {name: "Sổ hàng đợi"}))
    .toContainText("1 quá hạn SLA");
  await page.screenshot({path: "test-results/tip010-dashboard.png", fullPage: true});
});

test("freshness queue surfaces expired SLA state and assignment action", async ({page}) => {
  await mockKnowledgeOps(page);
  await page.goto("/knowledge-ops?view=freshness");
  const surface = page.getByRole("region", {name: "Bàn xử lý"});
  await expect(surface.getByText("Đã hết hạn", {exact: true})).toBeVisible();
  await expect(surface.getByText("company.warranty")).toBeVisible();
  const assign = page.getByRole("button", {name: "Giao cho", exact: true});
  await expect(assign).toBeDisabled();
  await page.getByLabel("Giao cho (subject ID)").fill(peerId);
  await expect(assign).toBeEnabled();
});

for (const viewport of [
  {name: "mobile", width: 360, height: 800},
  {name: "tablet", width: 768, height: 1024},
  {name: "desktop", width: 1440, height: 900},
  {name: "wide", width: 1920, height: 1080},
]) {
  test(`${viewport.name} ${viewport.width}×${viewport.height} has no overflow and visible focus`, async ({page}) => {
    await mockKnowledgeOps(page);
    await page.setViewportSize({width: viewport.width, height: viewport.height});
    await page.goto("/knowledge-ops");
    await expect(page.getByRole("heading", {name: "Bảng điều hành tri thức"})).toBeVisible();
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
    await page.keyboard.press("Tab");
    const focusedOutline = await page.evaluate(() => {
      const style = getComputedStyle(document.activeElement as Element);
      return Number.parseFloat(style.outlineWidth);
    });
    expect(focusedOutline).toBeGreaterThanOrEqual(3);
  });
}

test("mobile drawers: queue ledger and evidence sheet open, Escape closes", async ({page}) => {
  await mockKnowledgeOps(page);
  await page.setViewportSize({width: 360, height: 800});
  await page.goto("/knowledge-ops");
  await page.getByRole("button", {name: "Hàng đợi", exact: true}).click();
  await expect(page.getByRole("navigation", {name: "Sổ hàng đợi"})).toHaveClass(/open/);
  await page.getByRole("button", {name: /Khoảng trống/}).click();
  await expect(page.getByRole("navigation", {name: "Sổ hàng đợi"})).not.toHaveClass(/open/);
  await page.getByRole("button", {name: "Bằng chứng", exact: true}).click();
  await expect(page.getByRole("complementary", {name: "Bằng chứng và xuất xứ"}))
    .toHaveClass(/open/);
  await page.waitForTimeout(250);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  await page.screenshot({path: "test-results/tip010-mobile-rail.png", fullPage: true});
  await page.keyboard.press("Escape");
  await expect(page.getByRole("complementary", {name: "Bằng chứng và xuất xứ"}))
    .not.toHaveClass(/open/);
});

test("anonymous user never issues a governance request", async ({page}) => {
  let governanceRequests = 0;
  await page.route("**/api/auth/me", route => route.fulfill({status: 401, json: {}}));
  page.on("request", request => {
    if (new URL(request.url()).pathname.startsWith("/api/governance")) {
      governanceRequests += 1;
    }
  });
  await page.goto("/knowledge-ops");
  await expect(page.getByRole("link", {name: "Đăng nhập công ty"})).toBeVisible();
  expect(governanceRequests).toBe(0);
});
