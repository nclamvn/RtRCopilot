// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import {cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import React from "react";
import {afterEach, expect, test, vi} from "vitest";
import {I18nProvider} from "../../../i18n/provider";
import AskPage, {parseAnswerClaims} from "./page";

vi.mock("next/navigation", () => ({
  useSearchParams: () => new URLSearchParams(window.location.search),
}));

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  window.history.replaceState({}, "", "/ask");
});

const conversationId = "11111111-1111-4111-8111-111111111111";
const runId = "22222222-2222-4222-8222-222222222222";
const gapId = "33333333-3333-4333-8333-333333333333";
const versionId = "55555555-5555-4555-8555-555555555555";
const sha = "a".repeat(64);

const identity = {
  user_id: "44444444-4444-4444-8444-444444444444",
  email: "staff@rtrobotics.com", display_name: "RtR Staff", roles: ["staff"],
};

const citation = {
  marker: "C1",
  chunk_id: "66666666-6666-4666-8666-666666666666",
  record_key: "company.warranty",
  record_version_id: versionId,
  evidence_key: "company.warranty.e1",
  record_checksum: sha,
  evidence_checksum: null,
  source_key: "rtr.specs",
  source_revision: 1,
  provenance_level: "approved_internal",
  verification_state: "approved",
  freshness_state: "current",
  source_label: "Company specification",
  locator: {page: 4},
  redacted: false,
};

test("answer claim parser uses citation boundaries without inventing structure", () => {
  expect(parseAnswerClaims(
    "Nền tảng HERA dùng chung phần cứng lõi. [C1] "
    + "Biến thể Energy dự kiến Q4/2026. [C2][C3] Phần cuối chưa có căn cứ.",
  )).toEqual([
    {text: "Nền tảng HERA dùng chung phần cứng lõi.", citations: ["C1"]},
    {text: "Biến thể Energy dự kiến Q4/2026.", citations: ["C2", "C3"]},
    {text: "Phần cuối chưa có căn cứ.", citations: []},
  ]);
});

type Handler = (init?: RequestInit) => {status?: number; json: unknown};

function mockFetch(routes: Record<string, Handler>) {
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const raw = typeof input === "string"
      ? input
      : input instanceof URL ? input.toString() : input.url;
    const path = (raw.startsWith("http") ? new URL(raw).pathname : raw.split("?")[0]);
    const handler = routes[path];
    if (!handler) return new Response(JSON.stringify({error: {code: "unmocked"}}), {
      status: 500, headers: {"content-type": "application/json"},
    });
    const {status = 200, json} = handler(init);
    return new Response(JSON.stringify(json), {
      status, headers: {"content-type": "application/json"},
    });
  }));
}

const anonymous: Record<string, Handler> = {
  "/api/auth/me": () => ({status: 401, json: {
    error: {code: "authentication_required", message: ""}, request_id: "req-0",
  }}),
};

test("anonymous ask renders exactly one H1 in Vietnamese by default", async () => {
  mockFetch(anonymous);
  render(<AskPage/>);
  await waitFor(() => expect(screen.getByText(/Đăng nhập bằng email công ty/))
    .toBeInTheDocument());
  const headings = screen.getAllByRole("heading", {level: 1});
  expect(headings.length).toBe(1);
  expect(headings[0]).toHaveTextContent("Hỏi");
});

test("anonymous ask is fully translated under the en locale", async () => {
  mockFetch(anonymous);
  render(<I18nProvider initialLocale="en"><AskPage/></I18nProvider>);
  await waitFor(() => expect(screen.getByText(/Sign in with your company email/))
    .toBeInTheDocument());
  expect(screen.getByRole("heading", {level: 1, name: "Ask"})).toBeInTheDocument();
  expect(screen.queryByText(/Đăng nhập/)).toBeNull();
});

test("grounded ask renders citation markers wired to the shared rail; research denial disables the scope", async () => {
  mockFetch({
    "/api/auth/me": () => ({json: identity}),
    // TIP-011: the content-free scope capability replaces the search probe.
    "/api/governance/research/scope": () => ({json: {allowed: false}}),
    "/api/ask/conversations": () => ({json: {
      items: [], next_cursor: null, request_id: "req-list-1",
    }}),
    "/api/ask/ask": () => ({json: {
      state: "grounded",
      answer: "Robot RtR được bảo hành 24 tháng. [C1]",
      citations: [citation],
      conversation_id: conversationId,
      answer_run_id: runId,
      request_id: "req-1",
    }}),
  });
  render(<AskPage/>);
  const input = await screen.findByLabelText("Câu hỏi");
  // {allowed: false} → the research scope renders disabled with the denied state.
  expect(await screen.findByText(/Phạm vi nghiên cứu bị từ chối theo chính sách/))
    .toBeInTheDocument();
  expect(screen.getByLabelText("Kèm vùng nghiên cứu")).toBeDisabled();
  fireEvent.change(input, {target: {value: "Chính sách bảo hành robot?"}});
  fireEvent.click(screen.getByRole("button", {name: "Gửi câu hỏi"}));
  expect(await screen.findByText(/Robot RtR được bảo hành 24 tháng/)).toBeInTheDocument();
  // TIP-013B AC-4: an unflagged (strict-grounded) answer shows NO caveat.
  expect(screen.queryByText(/vui lòng kiểm chứng lại/)).toBeNull();
  // Citation marker focuses the rail entry.
  const marker = screen.getByRole("button", {
    name: "Trích dẫn — mở bằng chứng trong Evidence Rail C1",
  });
  fireEvent.click(marker);
  const entry = document.getElementById("rail-entry-C1");
  expect(entry).not.toBeNull();
  await waitFor(() => expect(entry).toHaveFocus());
  expect(entry).toHaveAttribute("aria-current", "true");
  // The rail deep link follows the TIP-008 contract.
  expect(screen.getByRole("link", {name: "Mở đúng vị trí — Trang 4"}))
    .toHaveAttribute("href", `/files?version=${versionId}&page=4`);
  // URL-restorable conversation id, without any browser storage.
  expect(location.search).toBe(`?conversation=${conversationId}`);
  expect(localStorage.length + sessionStorage.length).toBe(0);
});

test("TIP-013B: a soft-grounded answer renders the double-check caveat as a note", async () => {
  mockFetch({
    "/api/auth/me": () => ({json: identity}),
    "/api/governance/research/scope": () => ({json: {allowed: true}}),
    "/api/ask/conversations": () => ({json: {
      items: [], next_cursor: null, request_id: "req-list-caveat",
    }}),
    "/api/ask/ask": () => ({json: {
      state: "grounded",
      answer: "Robot RtR được bảo hành 24 tháng. [C1]",
      citations: [{...citation, needs_double_check: true}],
      conversation_id: conversationId,
      answer_run_id: runId,
      confidence_caveat: true,
      request_id: "req-caveat",
    }}),
  });
  render(<AskPage/>);
  const input = await screen.findByLabelText("Câu hỏi");
  fireEvent.change(input, {target: {value: "Chính sách bảo hành robot?"}});
  fireEvent.click(screen.getByRole("button", {name: "Gửi câu hỏi"}));
  expect(await screen.findByText(/Robot RtR được bảo hành 24 tháng/)).toBeInTheDocument();
  // The caveat is real, legible text in the answer region, reachable as a note.
  const caveat = screen.getByText(/Một số căn cứ chưa có trích dẫn nguyên văn/);
  expect(caveat).toBeInTheDocument();
  expect(caveat).toHaveAttribute("role", "note");
  expect(caveat).toHaveTextContent("vui lòng kiểm chứng lại");
});

test("honest-null is a first-class state showing the recorded gap id and state", async () => {
  mockFetch({
    "/api/auth/me": () => ({json: identity}),
    "/api/governance/research/scope": () => ({json: {allowed: true}}),
    "/api/ask/conversations": () => ({json: {
      items: [], next_cursor: null, request_id: "req-list-2",
    }}),
    "/api/ask/ask": () => ({json: {
      state: "honest_null",
      answer: "Không tìm thấy bằng chứng được phép và đủ tin cậy để trả lời.",
      citations: [],
      conversation_id: conversationId,
      answer_run_id: runId,
      gap_id: gapId,
      request_id: "req-2",
    }}),
    [`/api/governance/gaps/${gapId}`]: () => ({status: 403, json: {
      error: {code: "forbidden", message: ""}, request_id: "req-3",
    }}),
  });
  render(<AskPage/>);
  const input = await screen.findByLabelText("Câu hỏi");
  fireEvent.change(input, {target: {value: "Điều chưa ai ghi lại?"}});
  fireEvent.click(screen.getByRole("button", {name: "Gửi câu hỏi"}));
  expect(await screen.findByRole("heading", {name: "Chưa có bằng chứng"}))
    .toBeInTheDocument();
  expect(screen.getByText(/Không tìm thấy bằng chứng được phép/)).toBeInTheDocument();
  expect(screen.getByText(gapId)).toBeInTheDocument();
  // The caller may not read the gap: state degrades honestly, no invention.
  await waitFor(() => expect(screen.getByText("ngoài phạm vi xem của bạn"))
    .toBeInTheDocument());
  expect(screen.getByRole("link", {name: /Vận hành tri thức/}))
    .toHaveAttribute("href", `/knowledge-ops?view=gaps&gap=${gapId}`);
  // No fabricated citations appear.
  expect(screen.getByText("Chưa có bằng chứng để hiển thị.")).toBeInTheDocument();
});

test("research-scoped results render exactly the server zone, tier and grounding labels", async () => {
  mockFetch({
    "/api/auth/me": () => ({json: identity}),
    "/api/governance/research/scope": () => ({json: {allowed: true}}),
    "/api/ask/conversations": () => ({json: {
      items: [], next_cursor: null, request_id: "req-list-3",
    }}),
    "/api/governance/research/search": () => ({json: {
      zone_label: "research", grounding: "research_supported",
      results: [{
        zone_label: "research",
        research_record_id: "77777777-7777-4777-8777-777777777777",
        record_key: "vendor.abb.profile", tier: "P",
        snippet: "ABB manufactures industrial robots.", lexical_score: 0.9,
        citation: {
          zone_label: "research",
          research_record_id: "77777777-7777-4777-8777-777777777777",
          record_key: "vendor.abb.profile", version_ordinal: 1, tier: "P",
          source_key: "refinery.industry", package_fingerprint: sha,
          content_sha256: "c".repeat(64), corroboration_state: "corroborated",
          evidence_checksums: ["d".repeat(64)],
        },
      }], request_id: "req-7",
    }}),
    "/api/ask/ask": () => ({json: {
      state: "grounded",
      answer: "Theo SOT, RtR tích hợp robot hàn. [C1]",
      citations: [citation],
      conversation_id: conversationId,
      answer_run_id: runId,
      request_id: "req-4",
    }}),
  });
  render(<AskPage/>);
  const research = await screen.findByLabelText("Kèm vùng nghiên cứu");
  await waitFor(() => expect(research).toBeEnabled());
  fireEvent.click(research);
  fireEvent.change(screen.getByLabelText("Câu hỏi"),
    {target: {value: "RtR tích hợp robot của hãng nào?"}});
  fireEvent.click(screen.getByRole("button", {name: "Gửi câu hỏi"}));
  expect(await screen.findByRole("heading", {name: "Kết quả vùng nghiên cứu"}))
    .toBeInTheDocument();
  expect(screen.getAllByText("RESEARCH").length).toBeGreaterThanOrEqual(2);
  expect(screen.getAllByText("Tier P").length).toBeGreaterThanOrEqual(1);
  expect(screen.getAllByText(/research_supported/).length).toBeGreaterThanOrEqual(1);
  // SOT facts and research-supported statements are visibly distinguished.
  expect(await screen.findByText(/Theo SOT, RtR tích hợp robot hàn/)).toBeInTheDocument();
  expect(screen.getByText("Sự thật SOT (grounded)")).toBeInTheDocument();
  expect(screen.getByText("Do nghiên cứu hỗ trợ (research_supported)"))
    .toBeInTheDocument();
});

test("denied file catalog renders the typed state inside the picker", async () => {
  mockFetch({
    "/api/auth/me": () => ({json: identity}),
    "/api/governance/research/scope": () => ({json: {allowed: true}}),
    "/api/ask/conversations": () => ({json: {
      items: [], next_cursor: null, request_id: "req-list-4",
    }}),
    "/api/files": () => ({status: 403, json: {
      error: {code: "policy_denied", message: ""}, request_id: "req-5",
    }}),
  });
  render(<AskPage/>);
  fireEvent.click(await screen.findByRole("button", {name: "Chọn tệp được cấp quyền"}));
  const denied = await screen.findByText(/Bị từ chối theo chính sách/);
  expect(denied).toHaveTextContent("policy_denied · req-5");
});

test("file-scoped Ask sends the immutable version id", async () => {
  let askBody: unknown = null;
  mockFetch({
    "/api/auth/me": () => ({json: identity}),
    "/api/governance/research/scope": () => ({json: {allowed: true}}),
    "/api/ask/conversations": () => ({json: {
      items: [], next_cursor: null, request_id: "req-list-file",
    }}),
    "/api/files": () => ({json: {items: [{
      document_id: "77777777-7777-4777-8777-777777777777",
      version_id: versionId,
      logical_name: "flight-envelope",
      display_filename: "flight-envelope.pdf",
      viewer_kind: "pdf",
      classification: "internal",
    }], next_cursor: null}}),
    "/api/ask/ask": init => {
      askBody = JSON.parse(String(init?.body));
      return {json: {
        state: "honest_null", answer: "Không tìm thấy bằng chứng.", citations: [],
        conversation_id: conversationId, answer_run_id: runId,
        gap_id: gapId, request_id: "req-file",
      }};
    },
    [`/api/governance/gaps/${gapId}`]: () => ({status: 403, json: {
      error: {code: "forbidden", message: ""}, request_id: "req-gap-file",
    }}),
  });
  render(<AskPage/>);
  fireEvent.click(await screen.findByRole("button", {name: "Chọn tệp được cấp quyền"}));
  fireEvent.click(await screen.findByText("flight-envelope.pdf"));
  fireEvent.change(screen.getByLabelText("Câu hỏi"), {
    target: {value: "Giới hạn bay là gì?"},
  });
  fireEvent.click(screen.getByRole("button", {name: "Gửi câu hỏi"}));
  await waitFor(() => expect(askBody).toEqual({
    question: "Giới hạn bay là gì?",
    filters: {version_id: versionId},
  }));
});
