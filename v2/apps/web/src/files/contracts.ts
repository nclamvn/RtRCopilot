export type ViewerKind = "image" | "pdf" | "docx" | "xlsx" | "pptx" | "video" | "audio";

export type Rendition = {
  rendition_id: string;
  kind: string;
  mime_type: string;
  byte_size: number;
  sha256: string;
  quality_state: "complete" | "partial" | "low_confidence";
  content_url: string;
};

export type ViewerManifest = {
  schema_version: 1;
  version_id: string;
  source_sha256: string;
  detected_mime: string;
  viewer_kind: ViewerKind;
  state: string;
  capabilities: {
    preview: boolean;
    text: boolean;
    search_within_file: boolean;
    deep_link: boolean;
    download_original: boolean;
  };
  renditions: Rendition[];
  locator_schema: "rtr.locator.v1";
  quality: Record<string, unknown>;
  warnings: string[];
};

export type FileItem = {
  document_id: string;
  version_id: string;
  logical_name: string;
  display_filename: string;
  detected_mime: string;
  viewer_kind: ViewerKind;
  viewer_state: string;
  byte_size: number;
  classification: string;
  owner_display_name?: string | null;
  version_created_at: string;
  quality: Record<string, unknown>;
  warnings: string[];
  can_download: boolean;
};

export type Locator = {
  page?: number;
  region?: string;
  paragraph?: number;
  table?: number;
  sheet?: string;
  cell?: string;
  slide?: number;
  shape?: number;
  t?: number;
};

const UUID_PART = "[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}";
const UUID = new RegExp(`^${UUID_PART}$`, "i");
const HEX = /^[0-9a-f]{64}$/i;
const CELL = /^[A-Z]{1,3}[1-9][0-9]{0,6}$/;
const KINDS = new Set<ViewerKind>(["image", "pdf", "docx", "xlsx", "pptx", "video", "audio"]);
const QUALITY_STATES = new Set(["complete", "partial", "low_confidence"]);
const RENDITION_URL = new RegExp(
  `^/api/v1/files/renditions/(${UUID_PART})/content$`,
  "i",
);

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export function parseManifest(value: unknown): ViewerManifest {
  if (!record(value) || value.schema_version !== 1 || value.locator_schema !== "rtr.locator.v1"
      || typeof value.version_id !== "string" || !UUID.test(value.version_id)
      || typeof value.source_sha256 !== "string" || !HEX.test(value.source_sha256)
      || typeof value.detected_mime !== "string" || value.detected_mime.length > 200
      || /[\u0000-\u001f]/.test(value.detected_mime)
      || typeof value.viewer_kind !== "string" || !KINDS.has(value.viewer_kind as ViewerKind)
      || !record(value.capabilities) || !Array.isArray(value.renditions)
      || !["ready", "partial"].includes(String(value.state))
      || !record(value.quality)
      || value.renditions.length > 64 || !Array.isArray(value.warnings)
      || value.warnings.length > 64
      || value.warnings.some(item => typeof item !== "string" || item.length > 200)) {
    throw new Error("invalid_manifest");
  }
  for (const capability of [
    "preview", "text", "search_within_file", "deep_link", "download_original",
  ]) {
    if (typeof value.capabilities[capability] !== "boolean") {
      throw new Error("invalid_capabilities");
    }
  }
  for (const item of value.renditions) {
    const contentMatch = record(item) && typeof item.content_url === "string"
      ? RENDITION_URL.exec(item.content_url) : null;
    if (!record(item) || typeof item.rendition_id !== "string" || !UUID.test(item.rendition_id)
        || typeof item.kind !== "string" || !/^[a-z0-9_]{1,100}$/.test(item.kind)
        || typeof item.mime_type !== "string" || item.mime_type.length > 200
        || typeof item.byte_size !== "number" || item.byte_size < 0
        || !Number.isSafeInteger(item.byte_size) || item.byte_size > 100_000_000
        || typeof item.sha256 !== "string" || !HEX.test(item.sha256)
        || typeof item.quality_state !== "string" || !QUALITY_STATES.has(item.quality_state)
        || !contentMatch || contentMatch[1].toLowerCase() !== item.rendition_id.toLowerCase()) {
      throw new Error("invalid_rendition");
    }
  }
  return value as ViewerManifest;
}

function boundedInt(raw: string | null, minimum: number, maximum: number) {
  if (raw === null || !/^\d+$/.test(raw)) return undefined;
  const value = Number(raw);
  return Number.isSafeInteger(value) && value >= minimum && value <= maximum
    ? value : undefined;
}

export function parseLocator(params: URLSearchParams): Locator {
  const locator: Locator = {};
  const page = boundedInt(params.get("page"), 1, 5000);
  const paragraph = boundedInt(params.get("paragraph"), 0, 100_000);
  const table = boundedInt(params.get("table"), 0, 10_000);
  const slide = boundedInt(params.get("slide"), 1, 5000);
  const shape = boundedInt(params.get("shape"), 0, 100_000);
  const t = boundedInt(params.get("t"), 0, 14_400_000);
  const sheet = params.get("sheet");
  const cell = params.get("cell")?.toUpperCase();
  const region = params.get("region");
  if (page) locator.page = page;
  if (paragraph !== undefined) locator.paragraph = paragraph;
  if (table !== undefined) locator.table = table;
  if (slide) locator.slide = slide;
  if (shape !== undefined) locator.shape = shape;
  if (t !== undefined) locator.t = t;
  if (sheet && sheet.length <= 100 && !/[\u0000-\u001f]/.test(sheet)) locator.sheet = sheet;
  if (cell && CELL.test(cell)) locator.cell = cell;
  if (region && /^[A-Za-z0-9._~-]{1,100}$/.test(region)) locator.region = region;
  return locator;
}

export function locatorQuery(locator: Locator) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(locator)) {
    if (value !== undefined) params.set(key, String(value));
  }
  return params.toString();
}

export function proxyContentUrl(rendition: Rendition) {
  if (!RENDITION_URL.test(rendition.content_url)) throw new Error("unsafe_content_url");
  return rendition.content_url.replace("/api/v1/files/", "/api/files/");
}

export function viewerFor(kind: string): ViewerKind | "unsupported" {
  return KINDS.has(kind as ViewerKind) ? kind as ViewerKind : "unsupported";
}
