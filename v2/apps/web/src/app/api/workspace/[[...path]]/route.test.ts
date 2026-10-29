import {NextRequest} from "next/server";
import {afterEach, beforeEach, describe, expect, test, vi} from "vitest";
import {GET, POST, workspaceUpstream} from "./route";
afterEach(() => {vi.unstubAllGlobals(); vi.unstubAllEnvs();});
beforeEach(() => {vi.stubEnv("WORKSPACE_UI_ENABLED", "1");});
describe("Workspace BFF boundary", () => {
  test("AW08 allowlists exact proposal read/decision and selected handoff only, without publishing or runtime aliases", async () => {
    const fetcher = vi.fn(async () => new Response("{}")); vi.stubGlobal("fetch", fetcher);
    for (const path of [["workspaces", "w1", "proposals"], ["proposals", "p1"]]) expect((await GET(new NextRequest(`http://localhost/api/workspace/${path.join("/")}`), {params: Promise.resolve({path})})).status).toBe(200);
    for (const path of [["proposals", "p1", "decision"], ["workspaces", "w1", "handoff"]]) expect((await POST(new NextRequest(`http://localhost/api/workspace/${path.join("/")}`, {method: "POST", body: "{}"}), {params: Promise.resolve({path})})).status).toBe(200);
    for (const path of [["proposals", "p1", "publish"], ["workspaces", "w1", "handoff", "restore"], ["proposals", "p1", "content"]]) expect((await POST(new NextRequest(`http://localhost/api/workspace/${path.join("/")}`, {method: "POST", body: "{}"}), {params: Promise.resolve({path})})).status).toBe(400);
    expect(fetcher).toHaveBeenCalledTimes(4);
  });
  test("AW07 diagnostics is read-only; backup, restore and arbitrary health commands remain private CLI operations", async () => {
    const fetcher = vi.fn(async () => new Response("{}")); vi.stubGlobal("fetch", fetcher);
    expect((await GET(new NextRequest("http://localhost/api/workspace/diagnostics"), {params: Promise.resolve({path: ["diagnostics"]})})).status).toBe(200);
    for (const path of [["diagnostics"], ["backup"], ["restore"], ["preflight"], ["diagnostics", "upload"], ["runtime", "restart"]]) expect((await POST(new NextRequest(`http://localhost/api/workspace/${path.join("/")}`, {method: "POST", body: "{}"}), {params: Promise.resolve({path})})).status).toBe(400);
    expect(fetcher).toHaveBeenCalledTimes(1);
  });
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
    for (const path of [["auth"], ["runs", ".."], ["runs", "a/b"], ["runs", "%2e%2e"], ["files", "id", "arbitrary"], ["workspaces", "id", "research", "fetch"]]) {
      expect((await GET(new NextRequest("http://localhost/api/workspace/x"), {params: Promise.resolve({path})})).status).toBe(400);
    }
    expect(fetcher).not.toHaveBeenCalled();
  });
  test("allows only explicit AW02 endpoints and forwards binary response metadata", async () => {
    const fetcher = vi.fn(async () => new Response(new Uint8Array([80, 75, 3, 4]), {headers: {"content-type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "content-disposition": 'attachment; filename="brief.docx"'}})); vi.stubGlobal("fetch", fetcher);
    for (const path of [["files", "f1"], ["files", "f1", "download"], ["artifacts", "a1", "versions"], ["artifacts", "a1", "diff"], ["artifacts", "a1", "download"]]) {
      const response = await GET(new NextRequest(`http://localhost/api/workspace/${path.join("/")}?version=2&format=docx`), {params: Promise.resolve({path})});
      expect(response.status).toBe(200); expect(response.headers.get("content-disposition")).toContain("brief.docx"); expect(new Uint8Array(await response.arrayBuffer())).toEqual(new Uint8Array([80, 75, 3, 4]));
    }
    for (const path of [["workspaces", "w1", "files", "batch"], ["workspaces", "w1", "research", "search"], ["workspaces", "w1", "research", "read"], ["workspaces", "w1", "research", "import"], ["artifacts", "a1", "revisions"]]) expect((await POST(new NextRequest(`http://localhost/api/workspace/${path.join("/")}`, {method: "POST", body: "{}"}), {params: Promise.resolve({path})})).status).toBe(200);
    const before = fetcher.mock.calls.length;
    expect((await GET(new NextRequest("http://localhost/api/workspace/artifacts/a1/revisions"), {params: Promise.resolve({path: ["artifacts", "a1", "revisions"]})})).status).toBe(400); expect(fetcher).toHaveBeenCalledTimes(before);
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
  test("AW03 forwards only explicit scoped control routes; arbitrary MCP commands stay blocked", async () => {
    const fetcher = vi.fn(async () => new Response("{}")); vi.stubGlobal("fetch", fetcher);
    for (const family of ["memory", "schedules", "connection", "approvals", "effects"]) expect((await GET(new NextRequest(`http://localhost/api/workspace/workspaces/w-one/${family}`), {params: Promise.resolve({path: ["workspaces", "w-one", family]})})).status).toBe(200);
    const mutations = [["workspaces", "w-one", "memory"], ["workspaces", "w-one", "memory", "m-one", "edit"], ["workspaces", "w-one", "memory", "m-one", "delete"], ["workspaces", "w-one", "schedules"], ["workspaces", "w-one", "schedules", "s-one", "action"], ["workspaces", "w-one", "clock", "tick"], ["workspaces", "w-one", "connection"], ["approvals", "a-one", "resolve"], ["effects", "e-one", "reconcile"]];
    for (const path of mutations) expect((await POST(new NextRequest(`http://localhost/api/workspace/${path.join("/")}`, {method: "POST", body: "{}"}), {params: Promise.resolve({path})})).status).toBe(200);
    const count = fetcher.mock.calls.length;
    for (const path of [["mcp", "execute"], ["workspaces", "w-one", "connection", "command"], ["workspaces", "w-one", "clock", "start"], ["approvals", "a-one", "approve"], ["effects", "e-one", "retry"]]) expect((await POST(new NextRequest(`http://localhost/api/workspace/${path.join("/")}`, {method: "POST", body: "{}"}), {params: Promise.resolve({path})})).status).toBe(400);
    expect(fetcher).toHaveBeenCalledTimes(count);
  });
  test("AW04 allowlists exact readiness/export/delete routes without exposing generic setup or admin writes", async () => {
    const fetcher = vi.fn(async () => new Response(new Uint8Array([80, 75, 3, 4]), {headers: {"content-type": "application/zip", "content-disposition": 'attachment; filename="workspace.zip"'}})); vi.stubGlobal("fetch", fetcher);
    for (const path of [["readiness"], ["workspaces", "w-one", "export"], ["workspaces", "w-one", "delete-preview"]]) {const response = await GET(new NextRequest(`http://localhost/api/workspace/${path.join("/")}`), {params: Promise.resolve({path})}); expect(response.status).toBe(200); expect(response.headers.get("content-type")).toBe("application/zip");}
    expect((await POST(new NextRequest("http://localhost/api/workspace/workspaces/w-one/delete", {method: "POST", body: "{}"}), {params: Promise.resolve({path: ["workspaces", "w-one", "delete"]})})).status).toBe(200); const count = fetcher.mock.calls.length;
    for (const path of [["readiness"], ["configure"], ["admin", "delete"], ["workspaces", "w-one", "export"], ["workspaces", "w-one", "delete-preview"]]) expect((await POST(new NextRequest(`http://localhost/api/workspace/${path.join("/")}`, {method: "POST", body: "{}"}), {params: Promise.resolve({path})})).status).toBe(400);
    expect(fetcher).toHaveBeenCalledTimes(count);
  });
  test("AW05 import and project metadata paths are explicit, not a generic restore or filesystem proxy", async () => {
    const fetcher = vi.fn(async () => new Response("{}")); vi.stubGlobal("fetch", fetcher);
    for (const path of [["imports", "preview"], ["imports", "commit"], ["workspaces", "w-one", "metadata"]]) expect((await POST(new NextRequest(`http://localhost/api/workspace/${path.join("/")}`, {method:"POST", body:"{}"}), {params:Promise.resolve({path})})).status).toBe(200);
    expect((await GET(new NextRequest("http://localhost/api/workspace/workspaces/w-one/import-lineage"), {params:Promise.resolve({path:["workspaces","w-one","import-lineage"]})})).status).toBe(200);
    const before = fetcher.mock.calls.length;
    for (const path of [["imports", "execute"], ["workspaces", "w-one", "restore"], ["imports", "commit", "w-one"], ["filesystem", "import"]]) expect((await POST(new NextRequest(`http://localhost/api/workspace/${path.join("/")}`, {method:"POST", body:"{}"}), {params:Promise.resolve({path})})).status).toBe(400);
    expect(fetcher).toHaveBeenCalledTimes(before);
  });
  test("AW06 exposes only bounded context and lineage routes, not arbitrary index or execution commands", async () => {
    const fetcher = vi.fn(async () => new Response("{}")); vi.stubGlobal("fetch", fetcher);
    for (const path of [["workspaces", "w-one", "brief"], ["workspaces", "w-one", "search"], ["runs", "r-one", "context"], ["artifacts", "a-one", "dependencies"]]) {
      expect((await GET(new NextRequest(`http://localhost/api/workspace/${path.join("/")}?version=2`), {params: Promise.resolve({path})})).status).toBe(200);
    }
    for (const path of [["workspaces", "w-one", "brief"], ["workspaces", "w-one", "context-preview"], ["workspaces", "w-one", "source-replacements"]]) {
      expect((await POST(new NextRequest(`http://localhost/api/workspace/${path.join("/")}`, {method: "POST", body: "{}"}), {params: Promise.resolve({path})})).status).toBe(200);
    }
    const before = fetcher.mock.calls.length;
    for (const path of [["workspaces", "w-one", "reindex"], ["runs", "r-one", "context", "execute"], ["artifacts", "a-one", "dependencies", "verify"]]) expect((await POST(new NextRequest(`http://localhost/api/workspace/${path.join("/")}`, {method: "POST", body: "{}"}), {params: Promise.resolve({path})})).status).toBe(400);
    expect(fetcher).toHaveBeenCalledTimes(before);
  });
});
