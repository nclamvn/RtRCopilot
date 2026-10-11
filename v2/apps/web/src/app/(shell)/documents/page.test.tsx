// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import {act, cleanup, fireEvent, render, screen, waitFor} from "@testing-library/react";
import React from "react";
import {afterEach, expect, test, vi} from "vitest";
import {I18nProvider} from "../../../i18n/provider";
import DocumentsPage from "./page";

afterEach(() => {
  cleanup(); vi.restoreAllMocks(); vi.unstubAllGlobals();
  history.replaceState({}, "", "/documents");
});

test("anonymous identity gate never requests template or document metadata", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    calls.push(String(input));
    return new Response(JSON.stringify({error: {code: "authentication_required"}}), {
      status: 401, headers: {"content-type": "application/json"},
    });
  }));
  render(<DocumentsPage/>);
  // Shell adoption (TIP-011): the sign-in affordance lives in the AppShell
  // topbar; the page renders its gate lede and exactly one H1 (PageHeader).
  await screen.findByText(/Đăng nhập email công ty/);
  const headings = screen.getAllByRole("heading", {level: 1});
  expect(headings.length).toBe(1);
  expect(headings[0]).toHaveTextContent("Tài liệu");
  await waitFor(() => expect(calls).toEqual(["/api/auth/me"]));
  expect(calls.some(url => url.includes("/api/document-os/"))).toBe(false);
});

const renderJobId = "33333333-3333-4333-8333-333333333333";
type MockStatus = {
  render_job_id: string; state: string; progress: number; attempt: number;
  max_attempts: number; retryable: boolean; error_code?: string;
};
const failedStatus: MockStatus = {
  render_job_id: renderJobId, state: "failed", progress: 100,
  attempt: 1, max_attempts: 3, retryable: true, error_code: "render_lease_expired",
};

function mockRecovery(status: MockStatus, retryStatus = 200, options?: {
  delayed?: "render" | "retry" | "cancel"; response?: Promise<Response>;
  secondResponse?: Promise<Response>; createStatus?: number;
}) {
  const calls: Array<{url: string; method: string}> = [];
  let current = status;
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL, init?: RequestInit) => {
    const url = String(input);
    calls.push({url, method: init?.method ?? "GET"});
    const json = (value: unknown, code = 200) => new Response(JSON.stringify(value), {
      status: code, headers: {"content-type": "application/json"},
    });
    if (options?.response && (url.endsWith(`/render-jobs/${renderJobId}/${options.delayed}`)
      || (options.delayed === "render" && url.endsWith("templates/version/render")))) {
      return options.response;
    }
    if (options?.secondResponse && url.endsWith("templates/version-2/render")) {
      return options.secondResponse;
    }
    if (url === "/api/auth/me") return json({user_id: "synthetic-owner", roles: ["staff"]});
    if (url.includes("templates?")) return json({items: [{
      template_id: "template", version_id: "version", display_name: "Synthetic report",
      format: "docx", version_ordinal: 1, status: "approved", document_class: "internal",
    }, {
      template_id: "template-2", version_id: "version-2", display_name: "Second report",
      format: "docx", version_ordinal: 1, status: "approved", document_class: "internal",
    }]});
    if (url.endsWith("templates/template/versions/version")
      || url.endsWith("templates/template-2/versions/version-2")) return json({
      schema: {bindings: []}, template_id: "template", version_id: "version", status: "approved",
    });
    if (url.endsWith("/render") && options?.createStatus) return json({
      error: {code: "permission_denied", message: "NEVER-DISPLAY-ACCESS-ERROR"},
    }, options.createStatus);
    if (url.endsWith("/render")) return json({
      ...status, state: "pending", progress: 0, retryable: false,
    });
    if (url.endsWith(`/render-jobs/${renderJobId}/retry`)) {
      if (retryStatus !== 200) return json({error: {
        code: "render_retry_exhausted", message: "api_key=NEVER-DISPLAY-ERROR",
      }}, retryStatus);
      current = {...status, state: "completed", retryable: false, attempt: 2};
      return json({...current, state: "pending", progress: 0});
    }
    if (url.endsWith(`/render-jobs/${renderJobId}/cancel`)) {
      current = {...status, state: "cancelled", retryable: true};
      return json(current);
    }
    if (url.endsWith(`/render-jobs/${renderJobId}`)) return json({
      ...current, ...(current.state === "completed"
        ? {version_id: "synthetic-version", generated_file_id: "synthetic-generated"} : {}),
    });
    return json({error: {code: "not_found"}}, 404);
  }));
  return calls;
}

test.each(["vi", "en"] as const)("expired render is localized and retries the same job (%s)", async locale => {
  const calls = mockRecovery(failedStatus);
  render(<I18nProvider initialLocale={locale}><DocumentsPage/></I18nProvider>);
  const start = await screen.findByRole("button", {name: locale === "vi" ? "Tạo bản xem" : "Render preview"});
  await waitFor(() => expect(start).toBeEnabled());
  fireEvent.click(start);
  await screen.findByText(locale === "vi"
    ? "Bản dựng đã dừng vì quá thời gian xử lý."
    : "The render stopped because its processing time expired.");
  fireEvent.click(screen.getByRole("button", {name: locale === "vi" ? "Thử lại bản dựng" : "Retry render"}));
  await waitFor(() => expect(document.querySelector(".top-state"))
    .toHaveTextContent(locale === "vi" ? "Hoàn tất" : "Completed"), {timeout: 2500});
  expect(calls.filter(call => call.url.endsWith("/render"))).toHaveLength(1);
  expect(calls.filter(call => call.url.endsWith(`/render-jobs/${renderJobId}/retry`)))
    .toEqual([{url: `/api/document-os/documents/render-jobs/${renderJobId}/retry`, method: "POST"}]);
  expect(screen.queryByText("render_lease_expired")).not.toBeInTheDocument();
});

test("cancelling a pending owned render stops polling without a connection-loss alert", async () => {
  const calls = mockRecovery({...failedStatus, state: "rendering", retryable: false});
  render(<DocumentsPage/>);
  const start = await screen.findByRole("button", {name: "Tạo bản xem"});
  await waitFor(() => expect(start).toBeEnabled());
  fireEvent.click(start);
  fireEvent.click(await screen.findByRole("button", {name: "Hủy bản dựng"}));
  await waitFor(() => expect(document.querySelector(".top-state")).toHaveTextContent("Đã hủy"));
  await new Promise(resolve => setTimeout(resolve, 800));
  expect(calls.filter(call => call.url.endsWith(`/render-jobs/${renderJobId}`))).toHaveLength(0);
  expect(calls.filter(call => call.url.endsWith(`/render-jobs/${renderJobId}/cancel`)))
    .toEqual([{url: `/api/document-os/documents/render-jobs/${renderJobId}/cancel`, method: "POST"}]);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", {name: "Hủy bản dựng"})).not.toBeInTheDocument();
});

test("attempt cap hides retry even if an inconsistent payload says retryable", async () => {
  mockRecovery({...failedStatus, attempt: 3, max_attempts: 3, retryable: true});
  render(<DocumentsPage/>);
  const start = await screen.findByRole("button", {name: "Tạo bản xem"});
  await waitFor(() => expect(start).toBeEnabled());
  fireEvent.click(start);
  await screen.findByText(/Đã hết số lần thử cho công việc này/);
  expect(screen.queryByRole("button", {name: "Thử lại bản dựng"})).not.toBeInTheDocument();
});

test("typed retry-exhausted response hides retry and never displays raw provider error", async () => {
  const calls = mockRecovery(failedStatus, 409);
  render(<DocumentsPage/>);
  const start = await screen.findByRole("button", {name: "Tạo bản xem"});
  await waitFor(() => expect(start).toBeEnabled());
  fireEvent.click(start);
  fireEvent.click(await screen.findByRole("button", {name: "Thử lại bản dựng"}));
  expect(await screen.findByRole("alert")).toHaveTextContent("Đã hết số lần thử");
  expect(screen.queryByRole("button", {name: "Thử lại bản dựng"})).not.toBeInTheDocument();
  expect(document.body).not.toHaveTextContent("NEVER-DISPLAY-ERROR");
  expect(calls.filter(call => call.url.endsWith("/retry"))).toHaveLength(1);
});

test("unknown failure codes are replaced by a safe localized failure message", async () => {
  mockRecovery({...failedStatus, retryable: false, error_code: "api_key=NEVER-DISPLAY-CODE"});
  render(<DocumentsPage/>);
  const start = await screen.findByRole("button", {name: "Tạo bản xem"});
  await waitFor(() => expect(start).toBeEnabled());
  fireEvent.click(start);
  await screen.findByText("Bản dựng chưa hoàn tất. Hãy kiểm tra dữ liệu trước khi thử lại.");
  expect(document.body).not.toHaveTextContent("NEVER-DISPLAY-CODE");
  expect(screen.queryByRole("button", {name: "Thử lại bản dựng"})).not.toBeInTheDocument();
});

test.each(["render", "retry", "cancel"] as const)(
  "a delayed %s response cannot resurrect an old job or clear the new template's busy state",
  async action => {
    let releaseOld!: (response: Response) => void;
    let releaseNew!: (response: Response) => void;
    const oldResponse = new Promise<Response>(resolve => {releaseOld = resolve;});
    const newResponse = new Promise<Response>(resolve => {releaseNew = resolve;});
    const calls = mockRecovery(failedStatus, 200, {
      delayed: action, response: oldResponse, secondResponse: newResponse,
    });
    render(<DocumentsPage/>);
    const start = await screen.findByRole("button", {name: "Tạo bản xem"});
    await waitFor(() => expect(start).toBeEnabled());
    fireEvent.click(start);
    if (action !== "render") fireEvent.click(await screen.findByRole("button", {
      name: action === "retry" ? "Thử lại bản dựng" : "Hủy bản dựng",
    }));
    await waitFor(() => expect(calls.some(call => call.url.endsWith(`/${action}`))).toBe(true));
    fireEvent.click(screen.getByRole("button", {name: /Second report/}));
    await waitFor(() => expect(start).toBeEnabled());
    const polls = calls.filter(call => call.url.endsWith(`/render-jobs/${renderJobId}`)).length;
    fireEvent.click(start);
    await waitFor(() => expect(start).toBeDisabled());
    await act(async () => {
      releaseOld(new Response(JSON.stringify(failedStatus), {status: 200}));
      await oldResponse;
    });
    expect(start).toBeDisabled();
    expect(document.querySelector(".top-state")).toHaveTextContent("Sẵn sàng");
    expect(screen.queryByRole("button", {name: "Thử lại bản dựng"})).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    await new Promise(resolve => setTimeout(resolve, 750));
    expect(calls.filter(call => call.url.endsWith(`/render-jobs/${renderJobId}`))).toHaveLength(polls);
    await act(async () => {
      releaseNew(new Response(JSON.stringify({
        ...failedStatus, render_job_id: "new-template-job", state: "cancelled",
      }), {status: 200}));
      await newResponse;
    });
  },
);

test.each([401, 403])("render creation access loss %s clears the workspace", async status => {
  mockRecovery(failedStatus, 200, {createStatus: status});
  render(<DocumentsPage/>);
  const start = await screen.findByRole("button", {name: "Tạo bản xem"});
  await waitFor(() => expect(start).toBeEnabled());
  fireEvent.click(start);
  await screen.findByText(/Đăng nhập email công ty/);
  expect(screen.queryByRole("button", {name: "Tạo bản xem"})).not.toBeInTheDocument();
  expect(screen.queryByText("Synthetic report")).not.toBeInTheDocument();
  expect(document.body).not.toHaveTextContent("NEVER-DISPLAY-ACCESS-ERROR");
});
