import {describe, expect, test} from "vitest";
import {
  askQuery,
  parseAskAnswer,
  parseAskProgressEvent,
  parseAskState,
  parseConversation,
  parseFileScopePage,
} from "./contracts";

const conversationId = "11111111-1111-4111-8111-111111111111";
const runId = "22222222-2222-4222-8222-222222222222";
const gapId = "33333333-3333-4333-8333-333333333333";
const sha = "a".repeat(64);

const citation = {
  marker: "C1",
  chunk_id: "44444444-4444-4444-8444-444444444444",
  record_key: "company.warranty",
  record_version_id: "55555555-5555-4555-8555-555555555555",
  evidence_key: "company.warranty.e1",
  record_checksum: sha,
  evidence_checksum: null,
  source_key: "rtr.specs",
  source_revision: 1,
  provenance_level: "approved_internal",
  verification_state: "approved",
  freshness_state: "current",
  source_label: "Company specification",
  locator: {paragraph: 2},
  redacted: false,
};

const grounded = {
  state: "grounded",
  answer: "Bảo hành 24 tháng. [C1]",
  citations: [citation],
  conversation_id: conversationId,
  answer_run_id: runId,
  gap_id: null,
  request_id: "req-1",
};

describe("ask answer contract", () => {
  test("grounded answers adapt citations into rail entries", () => {
    const parsed = parseAskAnswer(grounded);
    expect(parsed.state).toBe("grounded");
    expect(parsed.entries).toHaveLength(1);
    expect(parsed.entries[0].marker).toBe("C1");
    expect(parsed.entries[0].grounding).toBe("grounded");
    expect(parsed.entries[0].zone).toBeNull();
    expect(parsed.conversationId).toBe(conversationId);
    expect(parsed.gapId).toBeNull();
    expect(parsed.answerMode).toBeNull();
    expect(parsed.coverageState).toBe("not_assessed");
  });

  test("grounded evidence-only mode is explicit at the client boundary", () => {
    expect(parseAskAnswer({...grounded, answer_mode: "evidence_only"}).answerMode)
      .toBe("evidence_only");
  });

  test("honest-null carries the recorded gap id and no citations", () => {
    const parsed = parseAskAnswer({
      ...grounded, state: "honest_null", citations: [],
      answer: "Không tìm thấy bằng chứng được phép và đủ tin cậy để trả lời.",
      gap_id: gapId,
    });
    expect(parsed.state).toBe("honest_null");
    expect(parsed.entries).toEqual([]);
    expect(parsed.gapId).toBe(gapId);
  });

  test("provider configuration abstention is typed and carries no false gap", () => {
    const parsed = parseAskAnswer({
      ...grounded, state: "honest_null", citations: [], gap_id: null,
      reason_code: "answer_quality_configuration_required",
      answer: "Đã tìm thấy bằng chứng phù hợp nhưng chưa thể tổng hợp.",
    });
    expect(parsed.state).toBe("honest_null");
    expect(parsed.reasonCode).toBe("answer_quality_configuration_required");
    expect(parsed.gapId).toBeNull();
  });

  test("a non-grounded answer may not smuggle citations", () => {
    expect(() => parseAskAnswer({...grounded, state: "honest_null", gap_id: gapId}))
      .toThrow("invalid_ask_response");
  });

  test("the confidence caveat flag rides only a grounded answer (TIP-013B)", () => {
    // Absent field → false; the field flips it true on a grounded answer.
    expect(parseAskAnswer(grounded).confidenceCaveat).toBe(false);
    expect(parseAskAnswer({...grounded, confidence_caveat: true}).confidenceCaveat)
      .toBe(true);
    // A non-grounded answer never carries the caveat, even if the server set it.
    expect(parseAskAnswer({
      ...grounded, state: "honest_null", citations: [], gap_id: gapId,
      confidence_caveat: true,
    }).confidenceCaveat).toBe(false);
    // A non-boolean caveat is a contract violation.
    expect(() => parseAskAnswer({...grounded, confidence_caveat: "yes"}))
      .toThrow("invalid_ask_response");
  });

  test("grounded partial coverage is typed without changing grounding", () => {
    const parsed = parseAskAnswer({...grounded, coverage_state: "partial"});
    expect(parsed.state).toBe("grounded");
    expect(parsed.coverageState).toBe("partial");
    expect(parsed.entries).toHaveLength(1);
    expect(() => parseAskAnswer({...grounded, coverage_state: "mostly"}))
      .toThrow("invalid_ask_response");
  });

  test("a forged zone label inside a citation rejects the whole answer", () => {
    // TIP-011: the literal server "sot" is the legitimate label…
    const labeled = parseAskAnswer({
      ...grounded, citations: [{...citation, zone_label: "sot"}],
    });
    expect(labeled.entries[0].zone).toBe("sot");
    // …anything else smuggled onto a citation still rejects the answer.
    expect(() => parseAskAnswer({
      ...grounded, citations: [{...citation, zone_label: "research"}],
    })).toThrow("zone_label_forged");
  });

  test.each([
    {patch: {state: "speculative"}},
    {patch: {conversation_id: "nope"}},
    {patch: {gap_id: "nope"}},
    {patch: {reason_code: "provider_made_this_up"}},
    {patch: {answer_mode: "speculative"}},
    {patch: {citations: "none"}},
  ])("rejects malformed response $patch", ({patch}) => {
    expect(() => parseAskAnswer({...grounded, ...patch})).toThrow();
  });
});

describe("ask progress contract", () => {
  const progress = {
    stage: "retrieving",
    status: "completed",
    elapsed_ms: 1200,
    sequence: 4,
    stage_elapsed_ms: 640,
    milestone: "sources_ready",
    detail: null,
    source_count: 1,
    sources: [{
      marker: "C1",
      record_key: "company.product.hera",
      source_label: "HERA approved specification",
      verification_state: "approved",
      freshness_state: "current",
    }],
  };

  test("accepts bounded additive latency metadata", () => {
    const parsed = parseAskProgressEvent(progress);
    expect(parsed.sequence).toBe(4);
    expect(parsed.stageElapsedMs).toBe(640);
    expect(parsed.milestone).toBe("sources_ready");
    expect(parsed.sources[0].recordKey).toBe("company.product.hera");
  });

  test("keeps older stream payloads compatible", () => {
    const legacy: Record<string, unknown> = {...progress};
    delete legacy.sequence;
    delete legacy.stage_elapsed_ms;
    delete legacy.milestone;
    const parsed = parseAskProgressEvent(legacy);
    expect(parsed.sequence).toBe(0);
    expect(parsed.stageElapsedMs).toBeNull();
    expect(parsed.milestone).toBeNull();
  });

  test.each([
    {milestone: "draft_tokens"},
    {sequence: -1},
    {stage_elapsed_ms: -1},
    {source_count: 21},
  ])("rejects unbounded or forged progress metadata %o", patch => {
    expect(() => parseAskProgressEvent({...progress, ...patch}))
      .toThrow("invalid_ask_progress");
  });
});

describe("conversation contract", () => {
  const message = {
    message_id: "66666666-6666-4666-8666-666666666666",
    role: "assistant",
    content: "Bảo hành 24 tháng. [C1]",
    answer_state: "grounded",
    citations: [citation],
    created_at: "2026-08-01T00:00:00Z",
  };

  test("parses owner conversations with citation-bearing messages", () => {
    const parsed = parseConversation({
      conversation_id: conversationId,
      messages: [
        {...message, role: "user", answer_state: null, citations: [],
          content: "Chính sách bảo hành?"},
        message,
      ],
      request_id: "req-2",
    });
    expect(parsed.messages).toHaveLength(2);
    expect(parsed.messages[0].role).toBe("user");
    expect(parsed.messages[1].entries[0].marker).toBe("C1");
  });

  test("rejects malformed roles and forged citation zones", () => {
    expect(() => parseConversation({
      conversation_id: conversationId,
      messages: [{...message, role: "system"}],
      request_id: "req-2",
    })).toThrow();
    expect(() => parseConversation({
      conversation_id: conversationId,
      messages: [{...message, citations: [{...citation, zone_label: "external"}]}],
      request_id: "req-2",
    })).toThrow("zone_label_forged");
  });
});

describe("file-scope picker contract and URL state", () => {
  test("parses ACL-scoped catalog rows", () => {
    const page = parseFileScopePage({items: [{
      document_id: "77777777-7777-4777-8777-777777777777",
      version_id: "88888888-8888-4888-8888-888888888888",
      logical_name: "fixture.pdf", display_filename: "fixture.pdf",
      viewer_kind: "pdf", classification: "internal", byte_size: 120,
    }], next_cursor: null});
    expect(page.items[0].logicalName).toBe("fixture.pdf");
    expect(page.items[0].viewerKind).toBe("pdf");
    expect(page.nextCursor).toBeNull();
  });

  test("rejects malformed catalog rows", () => {
    expect(() => parseFileScopePage({items: [{document_id: "x"}]})).toThrow();
  });

  test("URL state restores only a valid conversation id", () => {
    expect(parseAskState(new URLSearchParams(`conversation=${conversationId}`)))
      .toEqual({conversationId});
    expect(parseAskState(new URLSearchParams("conversation=../../etc")))
      .toEqual({conversationId: null});
    expect(askQuery(conversationId)).toBe(`conversation=${conversationId}`);
    expect(askQuery(null)).toBe("");
  });
});
