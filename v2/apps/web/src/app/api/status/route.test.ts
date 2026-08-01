import {afterEach, describe, expect, test, vi} from "vitest";
import {GET} from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("status endpoint keeps internal topology behind the ingress", () => {
  test("reports aggregate readiness without the dependency map", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      ok: true,
      status: "ready",
      dependencies: {postgres: "ready", redis: "ready", object_storage: "ready"},
    }))));
    const response = await GET();
    expect(response.status).toBe(200);
    const serialized = JSON.stringify(await response.json());
    expect(serialized).toContain("\"ok\":true");
    expect(serialized).toContain("\"status\":\"ready\"");
    for (const internal of ["dependencies", "postgres", "redis", "minio", "object_storage"]) {
      expect(serialized).not.toContain(internal);
    }
  });

  test("degraded upstream stays 503 and still hides dependency detail", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      ok: false,
      status: "unavailable",
      dependencies: {postgres: "unavailable", redis: "ready", object_storage: "ready"},
    }), {status: 503})));
    const response = await GET();
    expect(response.status).toBe(503);
    const serialized = JSON.stringify(await response.json());
    expect(serialized).toContain("\"ok\":false");
    expect(serialized).not.toContain("postgres");
  });

  test("unreachable upstream fails closed without upstream disclosure", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("ECONNREFUSED api:8000"); }));
    const response = await GET();
    expect(response.status).toBe(503);
    const serialized = JSON.stringify(await response.json());
    expect(serialized).toContain("\"status\":\"unavailable\"");
    expect(serialized).not.toContain("api:8000");
  });
});
