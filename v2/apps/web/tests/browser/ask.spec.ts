import {expect, Page, test} from "@playwright/test";

const conversationId = "11111111-1111-4111-8111-111111111111";
const runId = "22222222-2222-4222-8222-222222222222";
const gapId = "33333333-3333-4333-8333-333333333333";
const versionId = "55555555-5555-4555-8555-555555555555";
const documentId = "66666666-6666-4666-8666-666666666666";
const chunkId = "77777777-7777-4777-8777-777777777777";
const researchRecordId = "88888888-8888-4888-8888-888888888888";
const renditionId = "99999999-9999-4999-8999-999999999999";
const dataRenditionId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
const requesterId = "44444444-4444-4444-8444-444444444444";
const messageId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const answerMessageId = "cccccccc-cccc-4ccc-8ccc-cccccccccccc";
const sha = "a".repeat(64);

const citation = {
  // TIP-011: the backend serializes the literal server SOT zone label.
  zone_label: "sot",
  marker: "C1", chunk_id: chunkId, record_key: "company.warranty",
  record_version_id: versionId, evidence_key: "company.warranty.e1",
  record_checksum: sha, evidence_checksum: "b".repeat(64),
  source_key: "rtr.specs", source_revision: 3,
  provenance_level: "approved_internal", verification_state: "approved",
  freshness_state: "current", source_label: "Company specification",
  locator: {page: 4}, redacted: false,
};

const groundedAnswer = {
  state: "grounded", answer: "Robot RtR được bảo hành 24 tháng. [C1]",
  citations: [citation], conversation_id: conversationId,
  answer_run_id: runId, request_id: "req-ask-1",
};

// TIP-013B AC-4: same grounded answer, but the server flagged it as grounded on
// a softly-verified fact (and marks the soft citation).
const groundedCaveat = {
  ...groundedAnswer,
  confidence_caveat: true,
  citations: [{...citation, needs_double_check: true}],
  request_id: "req-ask-caveat",
};

const honestNull = {
  state: "honest_null",
  answer: "Không tìm thấy bằng chứng được phép và đủ tin cậy để trả lời.",
  citations: [], conversation_id: conversationId, answer_run_id: runId,
  gap_id: gapId, request_id: "req-ask-2",
};

const researchHit = {
  zone_label: "research", research_record_id: researchRecordId,
  record_key: "vendor.abb.profile", tier: "P",
  snippet: "ABB manufactures industrial robots for welding lines.",
  lexical_score: 0.9,
  citation: {
    zone_label: "research", research_record_id: researchRecordId,
    record_key: "vendor.abb.profile", version_ordinal: 1, tier: "P",
    source_key: "refinery.industry", package_fingerprint: sha,
    content_sha256: "c".repeat(64), corroboration_state: "corroborated",
    evidence_checksums: ["d".repeat(64)],
  },
};

const researchEmpty = {
  zone_label: "research", grounding: "research_supported",
  results: [], request_id: "req-research-0",
};

const gapDetail = {
  gap: {
    gap_id: gapId, question_fingerprint: sha,
    sanitized_question: "Điều chưa ai ghi lại?", sanitized_summary: "Khoảng trống",
    reason_category: "denied_or_unavailable", classification: "internal",
    requester_id: requesterId, owner_subject_id: null,
    routing_key: "governance.gap", occurrence_count: 1, lifecycle: "open",
    origin: "honest_null", priority: "normal",
    first_seen_at: "2026-08-01T00:00:00Z", last_seen_at: "2026-08-01T00:00:00Z",
    triaged_at: null, assigned_at: null, due_at: null, answered_at: null,
    closed_at: null, resolving_version_id: null, decline_reason: null,
  },
  transitions: [],
};

const viewerManifest = {
  schema_version: 1, version_id: versionId, source_sha256: sha,
  detected_mime: "application/pdf", viewer_kind: "pdf", state: "ready",
  capabilities: {preview: true, text: true, search_within_file: true,
    deep_link: true, download_original: false},
  renditions: [
    {rendition_id: renditionId, kind: "preview_pdf", mime_type: "application/pdf",
      byte_size: 120, sha256: sha, quality_state: "complete",
      content_url: `/api/v1/files/renditions/${renditionId}/content`},
    {rendition_id: dataRenditionId, kind: "page_text_json",
      mime_type: "application/json", byte_size: 120, sha256: sha,
      quality_state: "complete",
      content_url: `/api/v1/files/renditions/${dataRenditionId}/content`},
  ],
  locator_schema: "rtr.locator.v1", quality: {}, warnings: [],
};

type AskMockOptions = {
  research?: "empty" | "denied" | "results";
  ask?: Record<string, unknown>;
  catalog?: "ok" | "denied";
};

async function mockAsk(page: Page, options: AskMockOptions = {}) {
  const askBodies: Array<Record<string, unknown>> = [];
  await page.route("**/api/auth/me", route => route.fulfill({json: {
    user_id: requesterId, email: "staff@rtrobotics.com",
    display_name: "RtR Staff", roles: ["staff"],
  }}));
  await page.route("**/api/status", route => route.fulfill({json: {
    ok: true, status: "ready",
  }}));
  await page.route("**/api/governance/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/governance/research/scope") {
      // TIP-011: content-free capability replaces the audited search probe.
      return route.fulfill({json: {allowed: options.research !== "denied"}});
    }
    if (path === "/api/governance/research/search") {
      if (options.research === "results") {
        return route.fulfill({json: {
          zone_label: "research", grounding: "research_supported",
          results: [researchHit], request_id: "req-research-1",
        }});
      }
      return route.fulfill({json: researchEmpty});
    }
    if (path === `/api/governance/gaps/${gapId}`) {
      return route.fulfill({json: gapDetail});
    }
    return route.fulfill({status: 404, json: {
      error: {code: "not_found", message: ""}, request_id: "req-x",
    }});
  });
  await page.route("**/api/ask/**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/ask/ask") {
      askBodies.push(route.request().postDataJSON() as Record<string, unknown>);
      return route.fulfill({json: options.ask ?? groundedAnswer});
    }
    if (path === "/api/ask/conversations") {
      // TIP-011 owner-only list: metadata + stored first-question digest.
      return route.fulfill({json: {
        items: [{
          conversation_id: conversationId,
          started_at: "2026-08-01T00:00:00Z",
          last_activity_at: "2026-08-01T00:00:10Z",
          first_question_digest: sha,
        }],
        next_cursor: null, request_id: "req-list-1",
      }});
    }
    if (path === `/api/ask/conversations/${conversationId}`) {
      return route.fulfill({json: {
        conversation_id: conversationId,
        messages: [
          {message_id: messageId, role: "user",
            content: "Chính sách bảo hành robot?", answer_state: null,
            citations: [], created_at: "2026-08-01T00:00:00Z"},
          {message_id: answerMessageId, role: "assistant",
            content: "Robot RtR được bảo hành 24 tháng. [C1]",
            answer_state: "grounded", citations: [citation],
            created_at: "2026-08-01T00:00:10Z"},
        ],
        request_id: "req-conv-1",
      }});
    }
    return route.fulfill({status: 404, json: {
      error: {code: "conversation_not_found", message: ""}, request_id: "req-y",
    }});
  });
  await page.route("**/api/files**", route => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/api/files") {
      if (options.catalog === "denied") {
        return route.fulfill({status: 403, json: {
          error: {code: "policy_denied", message: ""}, request_id: "req-files-403",
        }});
      }
      return route.fulfill({json: {items: [{
        document_id: documentId, version_id: versionId,
        logical_name: "rtr.specs", display_filename: "company-spec.pdf",
        detected_mime: "application/pdf", viewer_kind: "pdf",
        viewer_state: "ready", byte_size: 120, classification: "internal",
        owner_display_name: "RtR Staff",
        version_created_at: "2026-07-31T00:00:00Z", quality: {}, warnings: [],
        can_download: false,
      }], next_cursor: null}});
    }
    if (path.endsWith("/upload-targets")) return route.fulfill({json: {items: []}});
    if (path.endsWith("/viewer-manifest")) {
      return route.fulfill({json: viewerManifest});
    }
    if (path.includes("/renditions/")) {
      return route.fulfill({json: {pages: [{page: 4, text: "Warranty 24 months"}]}});
    }
    return route.fulfill({status: 404, json: {error: {code: "not_found"}}});
  });
  return askBodies;
}

async function submitQuestion(page: Page, question: string) {
  await page.getByLabel("Câu hỏi").fill(question);
  await page.getByRole("button", {name: "Gửi câu hỏi"}).click();
}

test("grounded answer: citation focuses the rail entry and the locator opens the viewer at the exact position", async ({page}) => {
  await mockAsk(page);
  await page.goto("/ask");
  await submitQuestion(page, "Chính sách bảo hành robot?");
  await expect(page.getByText("Robot RtR được bảo hành 24 tháng.")).toBeVisible();
  await expect(page.getByText("Có căn cứ — mọi mệnh đề đều mang trích dẫn SOT"))
    .toBeVisible();
  // TIP-013B AC-4: an unflagged (strict-grounded) answer shows NO caveat.
  await expect(page.getByText(/vui lòng kiểm chứng lại/)).toHaveCount(0);
  // URL-restorable conversation id, no browser storage.
  await expect(page).toHaveURL(new RegExp(`conversation=${conversationId}`));
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);
  // Citation → rail focus.
  await page.getByRole("button", {name: /Trích dẫn — mở bằng chứng.*C1/}).click();
  await expect
    .poll(async () => page.evaluate(() => document.activeElement?.id))
    .toBe("rail-entry-C1");
  const rail = page.getByRole("complementary", {name: "Bằng chứng & xuất xứ"});
  await expect(rail.getByText("[C1]")).toBeVisible();
  await expect(rail.getByText("Sự thật SOT (grounded)")).toBeVisible();
  // TIP-011: the citation's literal server zone label renders the SOT chip.
  await expect(rail.locator(".zone-chip.zone-sot").first()).toBeVisible();
  // Locator activation → TIP-008 deep link, same tab, exact position.
  const locatorLink = rail.getByRole("link", {name: "Mở đúng vị trí — Trang 4"});
  await expect(locatorLink)
    .toHaveAttribute("href", `/files?version=${versionId}&page=4`);
  await locatorLink.click();
  await expect(page).toHaveURL(new RegExp(`version=${versionId}`));
  await expect(page).toHaveURL(/page=4/);
  await expect(page.getByTitle("Bản xem PDF an toàn")).toBeVisible();
  await expect(page.locator(".locator-spine")).toContainText("P4");
});

test("TIP-013B: a soft-grounded answer surfaces the double-check caveat as a note", async ({page}) => {
  await mockAsk(page, {ask: groundedCaveat});
  await page.goto("/ask");
  await submitQuestion(page, "Chính sách bảo hành robot?");
  await expect(page.getByText("Robot RtR được bảo hành 24 tháng.")).toBeVisible();
  // The caveat is present, legible text, reachable as a note (a11y).
  const caveat = page.getByRole("note")
    .filter({hasText: /Một số căn cứ chưa có trích dẫn nguyên văn/});
  await expect(caveat).toBeVisible();
  await expect(caveat).toContainText("vui lòng kiểm chứng lại");
});

test("honest-null renders the recorded gap id and state with a Knowledge Ops link", async ({page}) => {
  await mockAsk(page, {ask: honestNull});
  await page.goto("/ask");
  await submitQuestion(page, "Điều chưa ai ghi lại?");
  await expect(page.getByRole("heading", {name: "Chưa có bằng chứng"})).toBeVisible();
  await expect(page.getByText(/Không tìm thấy bằng chứng được phép/)).toBeVisible();
  await expect(page.getByText(gapId, {exact: true})).toBeVisible();
  await expect(page.getByText("open", {exact: true})).toBeVisible();
  await expect(page.getByRole("link", {name: /Vận hành tri thức/}))
    .toHaveAttribute("href", `/knowledge-ops?view=gaps&gap=${gapId}`);
  // No fabricated evidence appears anywhere.
  await expect(page.getByText("Chưa có bằng chứng để hiển thị.")).toBeVisible();
});

test("research scope renders results exactly as the backend labels them, distinct from SOT facts", async ({page}) => {
  await mockAsk(page, {research: "results"});
  await page.goto("/ask");
  const researchOption = page.getByLabel("Kèm vùng nghiên cứu");
  await expect(researchOption).toBeEnabled();
  await researchOption.check();
  await submitQuestion(page, "RtR tích hợp robot của hãng nào?");
  await expect(page.getByRole("heading", {name: "Kết quả vùng nghiên cứu"}))
    .toBeVisible();
  await expect(page.getByText(/research_supported.*không phải SOT/)).toBeVisible();
  const hit = page.getByRole("button", {name: /vendor\.abb\.profile/});
  await expect(hit).toContainText("RESEARCH");
  await expect(hit).toContainText("Tier P");
  await expect(hit).toContainText("corroborated");
  // The rail distinguishes the SOT-grounded fact from research support.
  const rail = page.getByRole("complementary", {name: "Bằng chứng & xuất xứ"});
  await expect(rail.getByText("Sự thật SOT (grounded)")).toBeVisible();
  await expect(rail.getByText("Do nghiên cứu hỗ trợ (research_supported)")).toBeVisible();
  await expect(rail.locator(".zone-chip.zone-research").first()).toBeVisible();
});

test("a denied scope capability disables the research option", async ({page}) => {
  // TIP-011: the content-free /research/scope capability ({allowed:false})
  // replaces the audited search probe's typed 403.
  await mockAsk(page, {research: "denied"});
  await page.goto("/ask");
  await expect(page.getByLabel("Kèm vùng nghiên cứu")).toBeDisabled();
  await expect(page.getByText(/Phạm vi nghiên cứu bị từ chối theo chính sách/))
    .toBeVisible();
});

test("denied file catalog renders the typed state inside the picker", async ({page}) => {
  await mockAsk(page, {catalog: "denied"});
  await page.goto("/ask");
  await page.getByRole("button", {name: "Chọn tệp được cấp quyền"}).click();
  await expect(page.getByText(/Bị từ chối theo chính sách/))
    .toContainText("policy_denied · req-files-403");
});

test("a picked file scopes the ask request to that file's source key", async ({page}) => {
  const askBodies = await mockAsk(page);
  await page.goto("/ask");
  await page.getByRole("button", {name: "Chọn tệp được cấp quyền"}).click();
  await page.getByRole("button", {name: /company-spec\.pdf/}).click();
  await expect(page.getByText("company-spec.pdf")).toBeVisible();
  await submitQuestion(page, "Tệp này nói gì về bảo hành?");
  await expect(page.getByText("Robot RtR được bảo hành 24 tháng.")).toBeVisible();
  expect(askBodies).toHaveLength(1);
  expect(askBodies[0].filters).toEqual({source_key: "rtr.specs"});
  // Clearing the scope removes the filter on the next ask.
  await page.getByRole("button", {name: "Bỏ giới hạn tệp"}).click();
  await submitQuestion(page, "Còn câu hỏi chung thì sao?");
  await expect.poll(() => askBodies.length).toBe(2);
  expect(askBodies[1].filters).toBeUndefined();
});

test("keyboard-only: ask → citation → rail → viewer at the exact locator", async ({page}) => {
  await mockAsk(page);
  await page.goto("/ask");
  await expect(page.getByRole("heading", {level: 1, name: "Hỏi"})).toBeVisible();
  // Skip link → work surface → question input, all by keyboard.
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", {name: "Bỏ qua tới nội dung chính"})).toBeFocused();
  await page.keyboard.press("Enter");
  await page.keyboard.press("Tab");
  await expect(page.getByLabel("Câu hỏi")).toBeFocused();
  await page.keyboard.type("Chính sách bảo hành robot?");
  await page.keyboard.press("Enter");
  await expect(page.getByText("Robot RtR được bảo hành 24 tháng.")).toBeVisible();
  // Tab to the citation marker and activate it.
  let focusedLabel = "";
  for (let step = 0; step < 20 && !focusedLabel.startsWith("Trích dẫn"); step += 1) {
    await page.keyboard.press("Tab");
    focusedLabel = await page.evaluate(
      () => document.activeElement?.getAttribute("aria-label") ?? "",
    );
  }
  expect(focusedLabel).toContain("C1");
  await page.keyboard.press("Enter");
  await expect
    .poll(async () => page.evaluate(() => document.activeElement?.id))
    .toBe("rail-entry-C1");
  // Next tab stop inside the focused entry is the locator link.
  await page.keyboard.press("Tab");
  await expect(page.getByRole("link", {name: "Mở đúng vị trí — Trang 4"})).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`version=${versionId}`));
  await expect(page).toHaveURL(/page=4/);
  await expect(page.getByTitle("Bản xem PDF an toàn")).toBeVisible();
});

test("F6 cycles navigation → work surface → evidence rail → navigation", async ({page}) => {
  await mockAsk(page);
  await page.goto("/ask");
  await expect(page.getByRole("heading", {level: 1, name: "Hỏi"})).toBeVisible();
  const focusedId = () => page.evaluate(() => document.activeElement?.id);
  await page.keyboard.press("F6");
  expect(await focusedId()).toBe("shell-nav");
  await page.keyboard.press("F6");
  expect(await focusedId()).toBe("main");
  await page.keyboard.press("F6");
  expect(await focusedId()).toBe("evidence-rail");
  await page.keyboard.press("F6");
  expect(await focusedId()).toBe("shell-nav");
  await page.keyboard.press("Shift+F6");
  expect(await focusedId()).toBe("evidence-rail");
  await page.keyboard.press("Shift+F6");
  expect(await focusedId()).toBe("main");
});

test("mobile: the rail is a bottom sheet with no horizontal overflow", async ({page}) => {
  await mockAsk(page);
  await page.setViewportSize({width: 360, height: 800});
  await page.goto("/ask");
  const rail = page.locator("#evidence-rail");
  await expect(rail).not.toHaveClass(/open/);
  await page.getByRole("button", {name: "Bằng chứng", exact: true}).click();
  await expect(rail).toHaveClass(/open/);
  await page.keyboard.press("Escape");
  await expect(rail).not.toHaveClass(/open/);
  // A citation click reopens the sheet and focuses the entry.
  await submitQuestion(page, "Chính sách bảo hành robot?");
  await page.getByRole("button", {name: /Trích dẫn — mở bằng chứng.*C1/}).click();
  await expect(rail).toHaveClass(/open/);
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
  await page.screenshot({path: "test-results/tip011-ask-mobile.png", fullPage: true});
});

test("the primary flow is fully translated under the en locale", async ({page}) => {
  await mockAsk(page);
  await page.goto("/ask");
  await page.getByRole("button", {name: "EN"}).click();
  await expect(page.getByRole("heading", {level: 1, name: "Ask"})).toBeVisible();
  await page.getByLabel("Question").fill("What is the robot warranty?");
  await page.getByRole("button", {name: "Submit question"}).click();
  await expect(page.getByText("Robot RtR được bảo hành 24 tháng.")).toBeVisible();
  await expect(page.getByText("Grounded — every statement carries an SOT citation"))
    .toBeVisible();
  const rail = page.getByRole("complementary", {name: "Evidence & provenance"});
  await expect(rail.getByText("SOT fact (grounded)")).toBeVisible();
  await expect(rail.getByRole("link", {name: "Open at exact position — Page 4"}))
    .toHaveAttribute("href", `/files?version=${versionId}&page=4`);
  // No mixed-language chrome on this screen.
  await expect(page.getByText("Câu trả lời")).toHaveCount(0);
  await expect(page.getByText("Gửi câu hỏi")).toHaveCount(0);
  await page.screenshot({path: "test-results/tip011-ask-desktop-en.png", fullPage: true});
});

test("the history panel lists the caller's server conversations and reopens one", async ({page}) => {
  // TIP-011: the panel is fed by GET /conversations (owner-only metadata:
  // id, timestamps, stored first-question digest — never content).
  await mockAsk(page);
  await page.goto("/ask");
  const historyPanel = page.getByRole("region", {name: "Hội thoại của bạn"});
  await expect(historyPanel.getByText(`${sha.slice(0, 12)}…`)).toBeVisible();
  await historyPanel.getByRole("button", {name: "Mở lại"}).click();
  await expect(page).toHaveURL(new RegExp(`conversation=${conversationId}`));
  await expect(page.getByRole("heading", {name: "Hội thoại", exact: true})).toBeVisible();
  await expect(page.getByText("Robot RtR được bảo hành 24 tháng.")).toBeVisible();
  expect(await page.evaluate(() => localStorage.length + sessionStorage.length)).toBe(0);
});

test("a conversation reopens from the URL with citations wired to the rail", async ({page}) => {
  await mockAsk(page);
  await page.goto(`/ask?conversation=${conversationId}`);
  await expect(page.getByRole("heading", {name: "Hội thoại"})).toBeVisible();
  await expect(page.getByText("Chính sách bảo hành robot?")).toBeVisible();
  await expect(page.getByText("Robot RtR được bảo hành 24 tháng.")).toBeVisible();
  await expect(page.getByText("grounded", {exact: true})).toBeVisible();
  // The reopened conversation's citations feed the shared rail.
  await page.getByRole("button", {name: /Trích dẫn — mở bằng chứng.*C1/}).click();
  await expect
    .poll(async () => page.evaluate(() => document.activeElement?.id))
    .toBe("rail-entry-C1");
  await expect(page.getByRole("complementary", {name: "Bằng chứng & xuất xứ"})
    .getByRole("link", {name: "Mở đúng vị trí — Trang 4"})).toBeVisible();
});

test("keyboard: [ and ] step the active citation across rail entries (PRD §14)", async ({page}) => {
  const citation2 = {
    ...citation, marker: "C2",
    chunk_id: "dddddddd-dddd-4ddd-8ddd-dddddddddddd",
    record_version_id: "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee",
    evidence_key: "company.warranty.e2",
  };
  await mockAsk(page, {ask: {
    state: "grounded",
    answer: "Bảo hành 24 tháng. [C1] Có thể gia hạn thêm. [C2]",
    citations: [citation, citation2],
    conversation_id: conversationId, answer_run_id: runId, request_id: "req-ask-2c",
  }});
  await page.goto("/ask");
  await submitQuestion(page, "Chính sách bảo hành robot?");
  await expect(page.locator(".rail-entries article")).toHaveCount(2);
  // Open C1 from its marker; focus lands in the rail on entry C1.
  await page.locator(".answer-text .citation-marker").first().click();
  await expect.poll(() => page.evaluate(() => document.activeElement?.id)).toBe("rail-entry-C1");
  await expect(page.locator("#rail-entry-C1")).toHaveAttribute("aria-current", "true");
  // ] steps to the next entry; [ steps back (focus moves with the active citation).
  await page.keyboard.press("]");
  await expect(page.locator("#rail-entry-C2")).toHaveAttribute("aria-current", "true");
  await expect.poll(() => page.evaluate(() => document.activeElement?.id)).toBe("rail-entry-C2");
  await page.keyboard.press("[");
  await expect(page.locator("#rail-entry-C1")).toHaveAttribute("aria-current", "true");
});
