import {NextRequest} from "next/server";

type RouteContext = {params: Promise<{path?: string[]}>};

const SAFE_SEGMENT = /^[A-Za-z0-9._~-]+$/;
/**
 * Only the governance-plane API families may cross this proxy; the backend
 * enforces authorization, but the web edge still refuses to become a generic
 * relay into /api/v1 (files, auth and document paths have their own proxies).
 */
const FAMILIES = new Set([
  "gaps", "governance", "research", "graduation", "admin", "enterprise",
]);

function valid(segment: string) {
  return SAFE_SEGMENT.test(segment) && segment !== "." && segment !== "..";
}

async function proxy(request: NextRequest, context: RouteContext) {
  const segments = (await context.params).path ?? [];
  if (segments.length === 0 || segments.some(segment => !valid(segment))
      || !FAMILIES.has(segments[0])) {
    return Response.json(
      {error: {code: "invalid_governance_path", message: "Governance request is invalid"}},
      {status: 400},
    );
  }
  const requestId = request.headers.get("x-request-id") ?? crypto.randomUUID();
  const headers = new Headers({
    "accept": "application/json",
    "x-request-id": requestId,
  });
  const contentType = request.headers.get("content-type");
  if (contentType) headers.set("content-type", contentType);
  const cookie = request.headers.get("cookie");
  if (cookie) headers.set("cookie", cookie);
  const upstream = new URL(
    `/api/v1/${segments.join("/")}${request.nextUrl.search}`,
    process.env.API_INTERNAL_URL,
  );
  try {
    const response = await fetch(upstream, {
      method: request.method,
      headers,
      body: request.method === "GET" ? undefined : request.body,
      cache: "no-store",
      redirect: "manual",
      signal: AbortSignal.timeout(180_000),
      ...(request.method === "GET" ? {} : {duplex: "half"}),
    } as RequestInit & {duplex?: "half"});
    return new Response(response.body, {
      status: response.status,
      headers: {
        "content-type": response.headers.get("content-type") ?? "application/json",
        "cache-control": "no-store",
        "x-request-id": response.headers.get("x-request-id") ?? requestId,
      },
    });
  } catch {
    return Response.json(
      {
        error: {
          code: "governance_service_unavailable",
          message: "Dịch vụ vận hành tri thức tạm gián đoạn",
        },
        request_id: requestId,
      },
      {status: 503, headers: {"x-request-id": requestId}},
    );
  }
}

export const GET = proxy;
export const POST = proxy;
export const PUT = proxy;
export const PATCH = proxy;
