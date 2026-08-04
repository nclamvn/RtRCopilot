import {NextRequest} from "next/server";
import {afterEach, describe, expect, test, vi} from "vitest";
import {GET, PATCH, POST, PUT} from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("Knowledge Ops same-origin proxy boundary", () => {
  test.each([
    {path: ["gaps", "."]}, {path: ["gaps", ".."]}, {path: ["gaps", "bad/path"]},
    {path: ["governance", "%2e%2e"]}, {path: ["research", "a b"]},
  ])("rejects unsafe segment $path without upstream disclosure", async ({path}) => {
    const upstream = vi.fn();
    vi.stubGlobal("fetch", upstream);
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    const response = await GET(
      new NextRequest("http://localhost/api/governance/test"),
      {params: Promise.resolve({path})},
    );
    expect(response.status).toBe(400);
    expect(upstream).not.toHaveBeenCalled();
  });

  test.each([
    {path: [] as string[]}, {path: ["files", "catalog"]}, {path: ["auth", "me"]},
    {path: ["templates"]}, {path: ["sot", "records"]},
  ])("refuses non-governance family $path — no generic /api/v1 relay", async ({path}) => {
    const upstream = vi.fn();
    vi.stubGlobal("fetch", upstream);
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    const response = await GET(
      new NextRequest("http://localhost/api/governance/test"),
      {params: Promise.resolve({path})},
    );
    expect(response.status).toBe(400);
    const body = await response.json() as {error: {code: string}};
    expect(body.error.code).toBe("invalid_governance_path");
    expect(upstream).not.toHaveBeenCalled();
  });

  test("keeps governance requests scoped and strips internal headers", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    vi.stubGlobal("fetch", vi.fn(async (request: URL | RequestInfo) => {
      const url = new URL(String(request));
      expect(url.pathname).toBe("/api/v1/governance/dashboard");
      return new Response(JSON.stringify({computed_at: "2026-08-01T00:00:00Z"}), {
        headers: {
          "content-type": "application/json",
          "x-internal-object-key": "hidden",
          "set-cookie": "internal=1",
        },
      });
    }));
    const response = await GET(
      new NextRequest("http://localhost/api/governance/governance/dashboard"),
      {params: Promise.resolve({path: ["governance", "dashboard"]})},
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
      expect(new URL(String(request)).search).toBe("?limit=25");
      return new Response(JSON.stringify({
        error: {code: "gap_not_found", message: "Governance request could not be completed"},
        request_id: "req-1234",
      }), {status: 404, headers: {"content-type": "application/json"}});
    }));
    const response = await GET(
      new NextRequest("http://localhost/api/governance/gaps?limit=25", {
        headers: {cookie: "rtr_session=abc", "x-request-id": "req-1234"},
      }),
      {params: Promise.resolve({path: ["gaps"]})},
    );
    expect(response.status).toBe(404);
    const body = await response.json() as {error: {code: string}};
    expect(body.error.code).toBe("gap_not_found");
    expect(response.headers.get("x-request-id")).toBe("req-1234");
  });

  test("upstream failure returns a typed 503 with request id and no secrets", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("ECONNREFUSED api:8000"); }));
    const response = await POST(
      new NextRequest("http://localhost/api/governance/gaps/x/triage", {method: "POST"}),
      {params: Promise.resolve({path: ["gaps", "11111111-1111-4111-8111-111111111111", "triage"]})},
    );
    expect(response.status).toBe(503);
    const body = await response.json() as {error: {code: string; message: string}; request_id: string};
    expect(body.error.code).toBe("governance_service_unavailable");
    expect(body.error.message).not.toContain("api:8000");
    expect(body.request_id).toBeTruthy();
    expect(response.headers.get("x-request-id")).toBe(body.request_id);
  });

  test.each([
    {method: "PUT", handler: PUT, path: ["admin", "settings", "gap.sla_hours"]},
    {method: "PATCH", handler: PATCH, path: ["admin", "research-sources", "11111111-1111-4111-8111-111111111111"]},
  ])("forwards bounded admin $method mutations", async ({method, handler, path}) => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    vi.stubGlobal("fetch", vi.fn(async (request: URL | RequestInfo, init?: RequestInit) => {
      expect(init?.method).toBe(method);
      expect(new URL(String(request)).pathname).toBe(`/api/v1/${path.join("/")}`);
      expect(init?.body).toBeTruthy();
      return Response.json({ok: true});
    }));
    const response = await handler(new NextRequest(
      `http://localhost/api/governance/${path.join("/")}`,
      {method, body: JSON.stringify({reason: "approved change"}), headers: {"content-type": "application/json"}},
    ), {params: Promise.resolve({path})});
    expect(response.status).toBe(200);
  });
});
