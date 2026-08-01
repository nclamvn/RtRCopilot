// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import {render, screen, waitFor} from "@testing-library/react";
import React from "react";
import {afterEach, expect, test, vi} from "vitest";
import FilesPage from "./page";

afterEach(() => vi.restoreAllMocks());

test("anonymous identity gate never requests catalog or viewer data", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    const url = String(input);
    calls.push(url);
    if (url === "/api/status") {
      return new Response(JSON.stringify({ok: true, status: "ready"}), {
        status: 200, headers: {"content-type": "application/json"},
      });
    }
    return new Response(JSON.stringify({error: {code: "authentication_required"}}), {
      status: 401, headers: {"content-type": "application/json"},
    });
  }));
  render(<FilesPage/>);
  // Shell adoption (TIP-011): the sign-in affordance lives in the AppShell
  // topbar; the page renders its gate lede and exactly one H1 (PageHeader).
  await screen.findByText(/Đăng nhập bằng email công ty/);
  const headings = screen.getAllByRole("heading", {level: 1});
  expect(headings.length).toBe(1);
  expect(headings[0]).toHaveTextContent("Tệp");
  await waitFor(() => expect(calls).toEqual(["/api/status", "/api/auth/me"]));
  expect(calls.some(url => url.startsWith("/api/files"))).toBe(false);
});
