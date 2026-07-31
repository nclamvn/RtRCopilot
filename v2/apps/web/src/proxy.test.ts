import {describe, expect, test} from "vitest";
import {hasTraversalPath} from "./proxy";

describe("pre-routing path defense", () => {
  test.each([
    "/api/files/../auth/me",
    "/api/files/%2e%2e/auth/me",
    "/api/files/%252e%252e/auth/me",
    "/api/files/%2e/auth/me",
    "/api/files/%2f..%2fauth/me",
    "/api/files/%5c..%5cauth/me",
  ])("rejects raw or encoded traversal %s", value => {
    expect(hasTraversalPath(value)).toBe(true);
  });

  test.each([
    "/api/files",
    "/api/files/renditions/11111111-1111-4111-8111-111111111111/content",
    "/api/files/catalog.v1",
  ])("accepts ordinary scoped path %s", value => {
    expect(hasTraversalPath(value)).toBe(false);
  });
});
