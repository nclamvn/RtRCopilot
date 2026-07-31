// @vitest-environment jsdom

import "@testing-library/jest-dom/vitest";
import {render, screen, waitFor} from "@testing-library/react";
import React from "react";
import {afterEach, expect, test, vi} from "vitest";
import Home from "./page";

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
  render(<Home/>);
  await screen.findByRole("link", {name: "Đăng nhập công ty"});
  expect(screen.getByRole("heading", {name: "File Workspace"})).toBeInTheDocument();
  await waitFor(() => expect(calls).toEqual(["/api/status", "/api/auth/me"]));
  expect(calls.some(url => url.startsWith("/api/files"))).toBe(false);
});
