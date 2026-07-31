import {NextRequest} from "next/server";
import {afterEach, describe, expect, test, vi} from "vitest";
import {GET} from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("Files same-origin proxy boundary", () => {
  test.each([
    {path: ["."]}, {path: [".."]}, {path: ["%2e"]}, {path: ["%2e%2e"]},
    {path: ["%252e%252e"]}, {path: ["renditions", "..", "auth"]},
    {path: ["renditions", "%2E%2E", "auth"]},
  ])("rejects traversal segment $path before upstream fetch", async ({path}) => {
    const upstream = vi.fn();
    vi.stubGlobal("fetch", upstream);
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    const response = await GET(
      new NextRequest("http://localhost/api/files/test"),
      {params: Promise.resolve({path})},
    );
    expect(response.status).toBe(400);
    expect(upstream).not.toHaveBeenCalled();
  });

  test("keeps the upstream path scoped and forwards nosniff only from allowlist", async () => {
    const upstream = vi.fn(async (request: URL | RequestInfo) => {
      expect(new URL(String(request)).pathname).toBe(
        "/api/v1/files/renditions/11111111-1111-4111-8111-111111111111/content",
      );
      return new Response("safe", {
        headers: {
          "X-Content-Type-Options": "nosniff",
          "X-Internal-Object-Key": "must-not-cross",
        },
      });
    });
    vi.stubGlobal("fetch", upstream);
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    const response = await GET(
      new NextRequest("http://localhost/api/files/test"),
      {params: Promise.resolve({path: [
        "renditions", "11111111-1111-4111-8111-111111111111", "content",
      ]})},
    );
    expect(response.status).toBe(200);
    expect(response.headers.get("x-content-type-options")).toBe("nosniff");
    expect(response.headers.has("x-internal-object-key")).toBe(false);
  });
});
