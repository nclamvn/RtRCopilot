import {NextRequest} from "next/server";
import {afterEach, describe, expect, test, vi} from "vitest";
import {GET} from "./route";

afterEach(() => {
  vi.unstubAllGlobals();
  vi.unstubAllEnvs();
});

describe("Documents same-origin proxy boundary", () => {
  test.each([["."], [".."], ["bad/path"], ["%2f"]])(
    "rejects unsafe segment %s without upstream disclosure",
    async segment => {
      const upstream = vi.fn();
      vi.stubGlobal("fetch", upstream);
      vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
      const response = await GET(
        new NextRequest("http://localhost/api/document-os/test"),
        {params: Promise.resolve({path: ["templates", segment]})},
      );
      expect(response.status).toBe(400);
      expect(upstream).not.toHaveBeenCalled();
    },
  );

  test("keeps template requests scoped and strips internal headers", async () => {
    vi.stubEnv("API_INTERNAL_URL", "http://api:8000");
    vi.stubGlobal("fetch", vi.fn(async (request: URL | RequestInfo) => {
      expect(new URL(String(request)).pathname).toBe("/api/v1/templates");
      return new Response(JSON.stringify({items: []}), {
        headers: {"x-internal-object-key": "hidden", "content-type": "application/json"},
      });
    }));
    const response = await GET(
      new NextRequest("http://localhost/api/document-os/templates"),
      {params: Promise.resolve({path: ["templates"]})},
    );
    expect(response.status).toBe(200);
    expect(response.headers.has("x-internal-object-key")).toBe(false);
  });
});
