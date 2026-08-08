import {afterEach, describe, expect, test, vi} from "vitest";
import {GET} from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("status endpoint keeps internal topology behind the ingress", () => {
  test("reports aggregate readiness without the dependency map", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    vi.stubEnv("RTR_BUILD_SHA", "0123456789ab");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      ok: true,
      status: "operational",
      build_sha: "0123456789ab",
      dependencies: {
        postgres: "ready", redis: "ready", object_storage: "ready", worker: "ready",
      },
      capabilities: {grounded_answering: "ready"},
    }))));
    const response = await GET();
    expect(response.status).toBe(200);
    const serialized = JSON.stringify(await response.json());
    expect(serialized).toContain("\"ok\":true");
    expect(serialized).toContain("\"status\":\"operational\"");
    expect(serialized).toContain("\"build_sha\":\"0123456789ab\"");
    expect(serialized).toContain("\"answer_quality\":\"ready\"");
    for (const internal of ["dependencies", "postgres", "redis", "minio", "object_storage", "worker"]) {
      expect(serialized).not.toContain(internal);
    }
  });

  test("degraded upstream stays 503 and still hides dependency detail", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    vi.stubEnv("RTR_BUILD_SHA", "0123456789ab");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      ok: false,
      status: "unavailable",
      build_sha: "0123456789ab",
      dependencies: {
        postgres: "unavailable", redis: "ready", object_storage: "ready", worker: "ready",
      },
      capabilities: {grounded_answering: "configuration_required"},
    }), {status: 503})));
    const response = await GET();
    expect(response.status).toBe(503);
    const serialized = JSON.stringify(await response.json());
    expect(serialized).toContain("\"ok\":false");
    expect(serialized).toContain("\"answer_quality\":\"configuration_required\"");
    expect(serialized).not.toContain("postgres");
  });

  test("preserves the usable evidence-only answer capability", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    vi.stubEnv("RTR_BUILD_SHA", "0123456789ab");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      ok: true,
      status: "operational",
      build_sha: "0123456789ab",
      capabilities: {grounded_answering: "evidence_only"},
    }))));
    const response = await GET();
    expect(response.status).toBe(200);
    expect(await response.json()).toMatchObject({
      ok: true,
      answer_quality: "evidence_only",
    });
  });

  test("unreachable upstream fails closed without upstream disclosure", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    vi.stubEnv("RTR_BUILD_SHA", "0123456789ab");
    vi.stubGlobal("fetch", vi.fn(async () => { throw new Error("ECONNREFUSED api:8000"); }));
    const response = await GET();
    expect(response.status).toBe(503);
    const serialized = JSON.stringify(await response.json());
    expect(serialized).toContain("\"status\":\"unavailable\"");
    expect(serialized).not.toContain("api:8000");
  });

  test("a source/runtime mismatch fails closed", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    vi.stubEnv("RTR_BUILD_SHA", "0123456789ab");
    vi.stubGlobal("fetch", vi.fn(async () => new Response(JSON.stringify({
      ok: true,
      status: "operational",
      build_sha: "fedcba987654",
      dependencies: {
        postgres: "ready", redis: "ready", object_storage: "ready", worker: "ready",
      },
    }))));
    const response = await GET();
    expect(response.status).toBe(503);
    expect(await response.json()).toMatchObject({
      ok: false,
      status: "version_mismatch",
      build_sha: "0123456789ab",
    });
  });
});
