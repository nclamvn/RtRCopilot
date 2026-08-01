import {NextRequest} from "next/server";
import {afterEach, describe, expect, test, vi} from "vitest";
import {GET, POST} from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("Ask same-origin proxy boundary", () => {
  test.each([
    {path: ["ask", "."]}, {path: ["conversations", ".."]},
    {path: ["conversations", "bad/path"]}, {path: ["ask", "%2e%2e"]},
    {path: ["conversations", "a b"]},
  ])("rejects unsafe segment $path without upstream disclosure", async ({path}) => {
    const upstream = vi.fn();
    vi.stubGlobal("fetch", upstream);
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    const response = await GET(
      new NextRequest("http://localhost/api/ask/test"),
      {params: Promise.resolve({path})},
    );
    expect(response.status).toBe(400);
    expect(upstream).not.toHaveBeenCalled();
  });

  test.each([
    {path: [] as string[]}, {path: ["search"]}, {path: ["files", "catalog"]},
    {path: ["auth", "me"]}, {path: ["gaps"]}, {path: ["governance", "dashboard"]},
    {path: ["research", "search"]}, {path: ["sot", "records"]},
  ])("refuses non-ask family $path — no generic /api/v1 relay", async ({path}) => {
    const upstream = vi.fn();
    vi.stubGlobal("fetch", upstream);
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    const response = await GET(
      new NextRequest("http://localhost/api/ask/test"),
      {params: Promise.resolve({path})},
    );
    expect(response.status).toBe(400);
    const body = await response.json() as {error: {code: string}};
    expect(body.error.code).toBe("invalid_ask_path");
    expect(upstream).not.toHaveBeenCalled();
  });

  test("keeps ask requests scoped and strips internal headers", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    vi.stubGlobal("fetch", vi.fn(async (request: URL | RequestInfo) => {
      const url = new URL(String(request));
      expect(url.pathname).toBe("/api/v1/ask");
      return new Response(JSON.stringify({state: "honest_null"}), {
        headers: {
          "content-type": "application/json",
          "x-internal-object-key": "hidden",
          "set-cookie": "internal=1",
        },
      });
    }));
    const response = await POST(
      new NextRequest("http://localhost/api/ask/ask", {method: "POST", body: "{}"}),
      {params: Promise.resolve({path: ["ask"]})},
    );
    expect(response.status).toBe(200);
    expect(response.headers.has("x-internal-object-key")).toBe(false);
    expect(response.headers.has("set-cookie")).toBe(false);
    expect(response.headers.get("cache-control")).toBe("no-store");
  });

  test("forwards session cookie and request id, passes typed errors through", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    vi.stubGlobal("fetch", vi.fn(async (request: URL | RequestInfo, init?: RequestInit) => {
      const headers = new Headers((init as RequestInit).headers);
      expect(headers.get("cookie")).toBe("rtr_session=abc");
      expect(headers.get("x-request-id")).toBe("req-1234");
      expect(new URL(String(request)).pathname)
        .toBe("/api/v1/conversations/11111111-1111-4111-8111-111111111111");
      return new Response(JSON.stringify({
        error: {code: "conversation_not_found", message: "Knowledge request could not be completed"},
        request_id: "req-1234",
      }), {status: 404, headers: {"content-type": "application/json"}});
    }));
    const response = await GET(
      new NextRequest(
        "http://localhost/api/ask/conversations/11111111-1111-4111-8111-111111111111",
        {headers: {cookie: "rtr_session=abc", "x-request-id": "req-1234"}},
      ),
      {params: Promise.resolve({
        path: ["conversations", "11111111-1111-4111-8111-111111111111"],
      })},
    );
    expect(response.status).toBe(404);
    const body = await response.json() as {error: {code: string}};
    expect(body.error.code).toBe("conversation_not_found");
    expect(response.headers.get("x-request-id")).toBe("req-1234");
  });

  test("upstream failure returns a typed 503 with request id and no secrets", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("ECONNREFUSED api:8000"); }));
    const response = await POST(
      new NextRequest("http://localhost/api/ask/ask", {method: "POST", body: "{}"}),
      {params: Promise.resolve({path: ["ask"]})},
    );
    expect(response.status).toBe(503);
    const body = await response.json() as {error: {code: string; message: string}; request_id: string};
    expect(body.error.code).toBe("ask_service_unavailable");
    expect(body.error.message).not.toContain("api:8000");
    expect(body.request_id).toBeTruthy();
    expect(response.headers.get("x-request-id")).toBe(body.request_id);
  });
});
