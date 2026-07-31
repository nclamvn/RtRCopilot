import {NextRequest} from "next/server";

type RouteContext = {params: Promise<{path?: string[]}>};

const REQUEST_HEADERS = new Set([
  "accept",
  "content-length",
  "content-type",
  "range",
  "x-content-sha256",
  "x-declared-mime",
  "x-logical-name",
  "x-original-filename",
  "x-parent-resource-id",
  "x-request-id",
]);
const RESPONSE_HEADERS = new Set([
  "accept-ranges",
  "cache-control",
  "content-disposition",
  "content-length",
  "content-range",
  "content-type",
  "etag",
  "x-content-type-options",
  "x-request-id",
]);
const SAFE_SEGMENT = /^[A-Za-z0-9._~-]+$/;

function safeSegment(segment: string) {
  if (!SAFE_SEGMENT.test(segment)) return false;
  let decoded = segment;
  for (let attempt = 0; attempt < 3; attempt += 1) {
    if (decoded === "." || decoded === "..") return false;
    try {
      const next = decodeURIComponent(decoded);
      if (next === decoded) break;
      decoded = next;
    } catch {
      return false;
    }
  }
  return decoded !== "." && decoded !== ".."
    && !decoded.includes("/") && !decoded.includes("\\");
}

async function proxy(request: NextRequest, context: RouteContext) {
  const {path} = await context.params;
  const segments = path ?? [];
  if (segments.some(segment => !safeSegment(segment))) {
    return Response.json(
      {error: {code: "invalid_file_path", message: "File request is invalid"}},
      {status: 400},
    );
  }
  const requestId = request.headers.get("x-request-id") ?? crypto.randomUUID();
  const headers = new Headers({"x-request-id": requestId});
  for (const [name, value] of request.headers) {
    if (REQUEST_HEADERS.has(name.toLowerCase())) headers.set(name, value);
  }
  const cookie = request.headers.get("cookie");
  if (cookie) headers.set("cookie", cookie);
  const upstream = new URL(
    `/api/v1/files${segments.length ? `/${segments.join("/")}` : ""}${request.nextUrl.search}`,
    process.env.API_INTERNAL_URL,
  );
  try {
    const init: RequestInit & {duplex?: "half"} = {
      method: request.method,
      headers,
      body: ["GET", "HEAD"].includes(request.method) ? undefined : request.body,
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(180_000),
      duplex: "half",
    };
    const response = await fetch(upstream, init);
    const responseHeaders = new Headers();
    for (const [name, value] of response.headers) {
      if (RESPONSE_HEADERS.has(name.toLowerCase())) responseHeaders.set(name, value);
    }
    responseHeaders.set(
      "x-request-id",
      response.headers.get("x-request-id") ?? requestId,
    );
    return new Response(response.body, {
      status: response.status,
      headers: responseHeaders,
    });
  } catch {
    return Response.json(
      {
        error: {
          code: "file_service_unavailable",
          message: "Dịch vụ tệp tạm thời không khả dụng",
        },
        request_id: requestId,
      },
      {status: 503, headers: {"x-request-id": requestId}},
    );
  }
}

export const GET = proxy;
export const POST = proxy;
