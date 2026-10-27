import {NextRequest} from "next/server";
import {afterEach, beforeEach, describe, expect, test, vi} from "vitest";
import {GET, POST, workspaceUpstream} from "./route";
afterEach(() => {vi.unstubAllGlobals(); vi.unstubAllEnvs();});
beforeEach(() => {vi.stubEnv("WORKSPACE_UI_ENABLED", "1");});
describe("Workspace BFF boundary", () => {
  test("is unavailable by default in a generic legacy web deployment", async () => {
    vi.stubEnv("WORKSPACE_UI_ENABLED", ""); const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    const response = await POST(new NextRequest("http://localhost/api/workspace/session", {method: "POST", body: "{}"}), {params: Promise.resolve({path: ["session"]})});
    expect(response.status).toBe(404); expect(await response.json()).toEqual({detail: "workspace_disabled"}); expect(fetcher).not.toHaveBeenCalled();
  });
  test("rejects non-loopback incoming hosts before forwarding session or body", async () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    for (const host of ["attacker.example:3110", "192.168.1.50:3110", "localhost@attacker.example"]) {
      const response = await POST(new NextRequest("http://localhost/api/workspace/session", {method: "POST", headers: {host, origin: "http://localhost:3110"}, body: "{}"}), {params: Promise.resolve({path: ["session"]})});
      expect(response.status).toBe(403);
    }
    expect(fetcher).not.toHaveBeenCalled();
  });
  test.each(["https://127.0.0.1", "http://example.com", "http://127.0.0.1/path", "http://user:pass@localhost", "http://localhost?url=evil"])("rejects non-local or ambiguous upstream %s", value => {expect(() => workspaceUpstream(value)).toThrow();});
  test("does not accept arbitrary URL/path families", async () => {
    const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
    for (const path of [["auth"], ["runs", ".."], ["runs", "a/b"], ["runs", "%2e%2e"]]) {
      expect((await GET(new NextRequest("http://localhost/api/workspace/x"), {params: Promise.resolve({path})})).status).toBe(400);
    }
    expect(fetcher).not.toHaveBeenCalled();
  });
  test("preserves session Set-Cookie but strips legacy cookies and identity headers", async () => {
    vi.stubGlobal("fetch", vi.fn(async (_url: unknown, init: RequestInit) => {
      const headers = new Headers(init.headers);
      expect(headers.get("cookie")).toBe("workspace_session=abc");
      expect(headers.has("x-user-id")).toBe(false);
      expect(headers.get("origin")).toBe("http://localhost:3110");
      return new Response("{}", {headers: {"set-cookie": "workspace_session=new; HttpOnly; SameSite=Strict; Path=/api/workspace", "x-internal-key": "hidden"}});
    }));
    const response = await POST(new NextRequest("http://localhost/api/workspace/session", {method: "POST", body: "{}", headers: {cookie: "legacy=secret; workspace_session=abc", "x-user-id": "forged", origin: "http://localhost:3110"}}), {params: Promise.resolve({path: ["session"]})});
    expect(response.headers.get("set-cookie")).toContain("HttpOnly");
    expect(response.headers.has("x-internal-key")).toBe(false);
  });
  test("passes streaming body and cursor without redispatch or implicit cancellation", async () => {
    const fetcher = vi.fn(async (url: URL, init: RequestInit) => {
      expect(url.pathname).toBe("/api/workspace/runs/run-a/events"); expect(url.searchParams.get("after")).toBe("12");
      expect(init.method).toBe("GET");
      return new Response("id:13\nevent:workspace\ndata:{}\n\n", {headers: {"content-type": "text/event-stream"}});
    }); vi.stubGlobal("fetch", fetcher);
    const response = await GET(new NextRequest("http://localhost/api/workspace/runs/run-a/events?after=12", {headers: {accept: "text/event-stream"}}), {params: Promise.resolve({path: ["runs", "run-a", "events"]})});
    expect(response.headers.get("x-accel-buffering")).toBe("no"); expect(await response.text()).toContain("id:13"); expect(fetcher).toHaveBeenCalledTimes(1);
  });
  test("service failure is actionable and does not disclose private upstream", async () => {
    vi.stubGlobal("fetch", vi.fn(() => {throw new Error("private details");}));
    const response = await GET(new NextRequest("http://localhost/api/workspace/status"), {params: Promise.resolve({path: ["status"]})});
    expect(response.status).toBe(503); expect(await response.json()).toEqual({detail: "workspace_service_unavailable"});
  });
});
