import {describe, expect, test} from "vitest";
import {
  locatorQuery,
  parseLocator,
  parseManifest,
  proxyContentUrl,
  viewerFor,
} from "./contracts";

const rendition = {
  rendition_id: "11111111-1111-4111-8111-111111111111",
  kind: "preview_pdf",
  mime_type: "application/pdf",
  byte_size: 123,
  sha256: "b".repeat(64),
  quality_state: "complete",
  content_url: "/api/v1/files/renditions/11111111-1111-4111-8111-111111111111/content",
};
const manifestValue = {
  schema_version: 1,
  version_id: "22222222-2222-4222-8222-222222222222",
  source_sha256: "a".repeat(64),
  detected_mime: "application/pdf",
  viewer_kind: "pdf",
  state: "ready",
  capabilities: {
    preview: true, text: true, search_within_file: true,
    deep_link: true, download_original: false,
  },
  renditions: [rendition],
  locator_schema: "rtr.locator.v1",
  quality: {},
  warnings: [] as unknown[],
};

test("validates manifests and keeps rendition URLs same-origin", () => {
  const manifest = parseManifest(manifestValue);
  expect(manifest.viewer_kind).toBe("pdf");
  expect(proxyContentUrl(manifest.renditions[0])).toBe(
    "/api/files/renditions/11111111-1111-4111-8111-111111111111/content",
  );
  expect(() => parseManifest({...manifest, renditions: [
    {...rendition, content_url: "https://attacker.example/file"},
  ]})).toThrow("invalid_rendition");
});

test.each([
  ["non-boolean capability", {
    ...manifestValue, capabilities: {...manifestValue.capabilities, download_original: "yes"},
  }],
  ["mismatched rendition URL", {
    ...manifestValue, renditions: [{
      ...rendition,
      content_url: "/api/v1/files/renditions/33333333-3333-4333-8333-333333333333/content",
    }],
  }],
  ["invalid rendition checksum", {
    ...manifestValue, renditions: [{...rendition, sha256: "not-a-checksum"}],
  }],
  ["unknown rendition quality", {
    ...manifestValue, renditions: [{...rendition, quality_state: "trusted"}],
  }],
  ["non-string warning", {...manifestValue, warnings: [{html: "<script>"}]}],
  ["unrenderable state", {...manifestValue, state: "processing"}],
])("rejects hostile manifest field: %s", (_label, value) => {
  expect(() => parseManifest(value)).toThrow();
});

describe("deep locators", () => {
  test("round-trips bounded locator fields", () => {
    const locator = parseLocator(new URLSearchParams(
      "page=2&sheet=Data&cell=B12&slide=3&shape=0&t=900",
    ));
    expect(locator).toEqual({
      page: 2, sheet: "Data", cell: "B12", slide: 3, shape: 0, t: 900,
    });
    expect(locatorQuery(locator)).toContain("cell=B12");
  });

  test("drops hostile and unbounded fields", () => {
    expect(parseLocator(new URLSearchParams(
      "page=-1&sheet=%00bad&cell=ZZZZ99999999&t=999999999&region=%3Cscript%3E",
    ))).toEqual({});
  });
});

test("viewer registry is closed to unknown kinds", () => {
  expect(viewerFor("xlsx")).toBe("xlsx");
  expect(viewerFor("html")).toBe("unsupported");
});
