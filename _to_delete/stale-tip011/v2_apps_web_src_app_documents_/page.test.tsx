// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import {render, screen, waitFor} from "@testing-library/react";
import React from "react";
import {afterEach, expect, test, vi} from "vitest";
import DocumentsPage from "./page";

afterEach(() => vi.restoreAllMocks());

test("anonymous identity gate never requests template or document metadata", async () => {
  const calls: string[] = [];
  vi.stubGlobal("fetch", vi.fn(async (input: RequestInfo | URL) => {
    calls.push(String(input));
    return new Response(JSON.stringify({error: {code: "authentication_required"}}), {
      status: 401, headers: {"content-type": "application/json"},
    });
  }));
  render(<DocumentsPage/>);
  await screen.findByRole("link", {name: "Đăng nhập công ty"});
  expect(screen.getByRole("heading", {name: "Documents"})).toBeInTheDocument();
  await waitFor(() => expect(calls).toEqual(["/api/auth/me"]));
  expect(calls.some(url => url.includes("/api/document-os/"))).toBe(false);
});
