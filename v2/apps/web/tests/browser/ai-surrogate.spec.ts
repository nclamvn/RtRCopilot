import {createHash} from "node:crypto";
import {mkdirSync, readFileSync, writeFileSync} from "node:fs";
import {dirname, resolve} from "node:path";

import {expect, test, type Page} from "@playwright/test";

type SourceCase = {
  id: string;
  domain: string;
  shapes: string[];
  question: string;
  expect: "grounded" | "honest_null";
  required_terms?: string[];
  expected_record_groups?: string[][];
  scenarioId?: string;
};

type PlanCase = {case_id: string; persona: string; scenario: string};
type AskBody = {question?: string; conversation_id?: string};

const projectRoot = resolve(process.cwd(), "../..");
const planPath = resolve(
  projectRoot,
  process.env.AI_SURROGATE_PLAN ?? "eval/pilot/tip035_12_ai_surrogate_plan.json",
);
const sourcePath = resolve(
  projectRoot,
  process.env.AI_SURROGATE_SOURCE ?? "eval/real_world/cases.json",
);
const ledgerPath = resolve(
  projectRoot,
  process.env.AI_SURROGATE_HUMAN_LEDGER ?? "eval/pilot/tip034_observations.json",
);
const outputPath = resolve(
  projectRoot,
  process.env.AI_SURROGATE_UI_OUTPUT ?? "eval/runtime/tip035_12_ai_surrogate_ui.json",
);
const candidateBuild = process.env.AI_SURROGATE_BUILD_IDENTITY ?? "";
const planBytes = readFileSync(planPath);
const sourceBytes = readFileSync(sourcePath);
const ledgerBytes = readFileSync(ledgerPath);
const plan = JSON.parse(planBytes.toString("utf8")) as {
  campaign_key: string;
  tester_kind: string;
  cases: PlanCase[];
};
const sourcePayload = JSON.parse(sourceBytes.toString("utf8")) as {
  cases: SourceCase[];
  scenarios: Array<{id: string; domain: string; turns: SourceCase[]}>;
};
const sha256 = (value: Buffer | string) => createHash("sha256").update(value).digest("hex");
const sourceCases = [
  ...sourcePayload.cases,
  ...sourcePayload.scenarios.flatMap(scenario => scenario.turns.map(turn => ({
    ...turn,
    domain: scenario.domain,
    scenarioId: scenario.id,
  }))),
];
const sourceById = new Map(sourceCases.map(item => [item.id, item]));
const selected = plan.cases.map(item => {
  const source = sourceById.get(item.case_id);
  if (!source) throw new Error(`ai_surrogate_source_case_missing:${item.case_id}`);
  return {plan: item, source};
});

const ids = {
  conversation: "11111111-1111-4111-8111-111111111111",
  run: "22222222-2222-4222-8222-222222222222",
  gap: "33333333-3333-4333-8333-333333333333",
  user: "44444444-4444-4444-8444-444444444444",
  version: "55555555-5555-4555-8555-555555555555",
  chunk: "77777777-7777-4777-8777-777777777777",
};
const checksum = "a".repeat(64);

function answerFor(source: SourceCase) {
  if (source.expect === "honest_null") {
    return {
      state: "honest_null",
      answer: "Không tìm thấy bằng chứng được phép và đủ tin cậy để trả lời.",
      citations: [],
      conversation_id: ids.conversation,
      answer_run_id: ids.run,
      gap_id: ids.gap,
      reason_code: "insufficient_confidence",
      request_id: `ai-surrogate-${source.id}`,
    };
  }
  const terms = source.required_terms ?? [source.id];
  const recordKey = source.expected_record_groups?.[0]?.[0] ?? `surrogate.${source.id}`;
  return {
    state: "grounded",
    answer: `Kết quả đã đối chiếu: ${terms.join(" · ")}. [C1]`,
    answer_mode: "quality_llm",
    coverage_state: "complete",
    citations: [{
      zone_label: "sot",
      marker: "C1",
      chunk_id: ids.chunk,
      record_key: recordKey,
      record_version_id: ids.version,
      evidence_key: `${recordKey}.e1`,
      record_checksum: checksum,
      evidence_checksum: "b".repeat(64),
      source_key: "tip03512.synthetic-ui-oracle",
      source_revision: 1,
      provenance_level: "approved_internal",
      verification_state: "approved",
      freshness_state: "current",
      source_label: `SOT oracle · ${source.id}`,
      locator: {page: 1},
      redacted: false,
    }],
    conversation_id: ids.conversation,
    answer_run_id: ids.run,
    request_id: `ai-surrogate-${source.id}`,
  };
}

async function installRoutes(page: Page, submitted: AskBody[]) {
  await page.route("**/api/**", async route => {
    const request = route.request();
    const path = new URL(request.url()).pathname;
    if (path === "/api/auth/me") return route.fulfill({json: {
      user_id: ids.user,
      email: "ai-surrogate@rtrobotics.com",
      display_name: "AI Surrogate (not employee)",
      roles: ["staff"],
    }});
    if (path === "/api/status") return route.fulfill({json: {
      ok: true,
      status: "ready",
      build_sha: candidateBuild,
    }});
    if (path === "/api/governance/research/scope") {
      return route.fulfill({json: {allowed: false}});
    }
    if (path === `/api/governance/gaps/${ids.gap}`) return route.fulfill({json: {
      gap: {
        zone_label: "sot",
        gap_id: ids.gap,
        question_fingerprint: checksum,
        sanitized_question: "Ambiguous employee query",
        sanitized_summary: "Clarification required",
        reason_category: "ambiguous_entity",
        classification: "internal",
        requester_id: ids.user,
        owner_subject_id: null,
        routing_key: "governance.gap",
        occurrence_count: 1,
        lifecycle: "open",
        origin: "honest_null",
        priority: "normal",
        first_seen_at: "2026-08-14T00:00:00Z",
        last_seen_at: "2026-08-14T00:00:00Z",
        triaged_at: null,
        assigned_at: null,
        due_at: null,
        answered_at: null,
        closed_at: null,
        resolving_version_id: null,
        decline_reason: null,
      },
      transitions: [],
    }});
    if (path === "/api/ask/conversations") return route.fulfill({json: {
      items: [], next_cursor: null, request_id: "ai-surrogate-conversations",
    }});
    if (path === "/api/ask/ask") {
      const body = request.postDataJSON() as AskBody;
      submitted.push(body);
      const source = sourceCases.find(item => item.question === body.question);
      if (!source) return route.fulfill({status: 422, json: {
        error: {code: "unknown_surrogate_question", message: ""},
      }});
      await new Promise(resolveDelay => setTimeout(resolveDelay, 180));
      return route.fulfill({json: answerFor(source)});
    }
    if (path === "/api/files") return route.fulfill({json: {
      items: [], next_cursor: null,
    }});
    return route.fulfill({status: 404, json: {
      error: {code: "not_found", message: ""}, request_id: "ai-surrogate-404",
    }});
  });
}

test.describe.configure({mode: "serial"});

test("TIP-035.12 AI-surrogate exercises all immutable employee personas", async ({page}) => {
  test.setTimeout(180_000);
  expect(candidateBuild).toMatch(/^[0-9a-f]{12,64}$/);
  expect(selected).toHaveLength(27);
  const submitted: AskBody[] = [];
  const results: Array<Record<string, unknown>> = [];
  await installRoutes(page, submitted);
  await page.setViewportSize({width: 1440, height: 900});

  let previous: SourceCase | undefined;
  for (const item of selected) {
    const {source} = item;
    const followUp = Boolean(
      source.scenarioId && previous?.scenarioId === source.scenarioId,
    );
    if (!followUp) await page.goto("/ask");

    const composer = page.getByLabel("Câu hỏi");
    await composer.fill(source.question);
    await expect(composer).toHaveValue(source.question);
    const beforeSubmit = submitted.length;
    await page.getByRole("button", {name: "Gửi câu hỏi"}).click();
    await expect(composer).toHaveValue("");
    await expect(page.locator(".ask-turn-user").last()).toHaveText(source.question);
    await expect(page.locator(".ask-progress")).toBeVisible();

    if (source.expect === "grounded") {
      const answer = page.locator(".ask-answer");
      await expect(answer).toBeVisible();
      for (const term of source.required_terms ?? []) await expect(answer).toContainText(term);
      const marker = answer.locator(".citation-marker").last();
      await expect(marker).toBeVisible();
      await marker.click();
      await expect.poll(() => page.evaluate(() => document.activeElement?.id))
        .toBe("rail-entry-C1");
      await page.getByRole("complementary", {name: "Bằng chứng & xuất xứ"})
        .getByRole("button", {name: "Đóng bằng chứng"}).click();
    } else {
      await expect(page.getByRole("heading", {name: "Chưa có bằng chứng"})).toBeVisible();
      await expect(page.locator(".honest-null .citation-marker")).toHaveCount(0);
      await expect(page.getByText("Chưa có bằng chứng để hiển thị.")).toBeVisible();
    }

    expect(submitted).toHaveLength(beforeSubmit + 1);
    expect(submitted.at(-1)?.question).toBe(source.question);
    const contextPreserved = !followUp || Boolean(submitted.at(-1)?.conversation_id);
    const rendered = page.locator(source.expect === "grounded" ? ".ask-answer" : ".honest-null");
    const renderedText = await rendered.innerText();
    const promptLeakAbsent = !/(system prompt|chain[- ]of[- ]thought|developer message)/i
      .test(renderedText);
    results.push({
      case_id: source.id,
      persona: item.plan.persona,
      question_digest: sha256(source.question),
      expected_state: source.expect,
      rendered_state: source.expect,
      exact_input_round_trip: true,
      composer_cleared: true,
      processing_visible: true,
      response_state_rendered: true,
      citation_or_honest_null_rendered: true,
      evidence_rail_consistent: true,
      conversation_context_preserved: contextPreserved,
      prompt_leak_absent: promptLeakAbsent,
    });
    previous = source;
  }

  expect(results).toHaveLength(27);
  expect(submitted).toHaveLength(27);
  const report = {
    schema_version: 1,
    campaign_key: plan.campaign_key,
    generated_at: new Date().toISOString(),
    candidate_build: candidateBuild,
    tester_kind: plan.tester_kind,
    plan_digest: sha256(planBytes),
    source_suite_digest: sha256(sourceBytes),
    human_ledger_digest: sha256(ledgerBytes),
    human_ledger_modified: false,
    external_calls_executed: 0,
    case_results: results,
  };
  mkdirSync(dirname(outputPath), {recursive: true});
  writeFileSync(outputPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
});
