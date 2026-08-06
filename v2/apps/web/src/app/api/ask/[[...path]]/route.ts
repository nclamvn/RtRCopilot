import {NextRequest} from "next/server";

type RouteContext = {params: Promise<{path?: string[]}>};

const SAFE_SEGMENT = /^[A-Za-z0-9._~-]+$/;
/**
 * TIP-011 Task 2: same-origin proxy for the TIP-007 knowledge plane,
 * mirroring the governance proxy boundary. Only the ask/conversation
 * families the Ask workspace actually consumes may cross; the backend
 * enforces authorization, but the web edge still refuses to become a
 * generic relay into /api/v1 (files, auth, document and governance paths
 * have their own proxies).
 */
const FAMILIES = new Set(["ask", "conversations"]);

function valid(segment: string) {
  return SAFE_SEGMENT.test(segment) && segment !== "." && segment !== "..";
}

async function proxy(request: NextRequest, context: RouteContext) {
  const segments = (await context.params).path ?? [];
  if (segments.length === 0 || segments.some(segment => !valid(segment))
      || !FAMILIES.has(segments[0])) {
    return Response.json(
      {error: {code: "invalid_ask_path", message: "Ask request is invalid"}},
      {status: 400},
    );
  }
  const requestId = request.headers.get("x-request-id") ?? crypto.randomUUID();
  const requestedAccept = request.headers.get("accept") ?? "application/json";
  const accept = requestedAccept.includes("text/event-stream")
    ? "text/event-stream" : "application/json";
  const headers = new Headers({
    accept,
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
    const streaming = response.headers.get("content-type")
      ?.includes("text/event-stream") === true;
    return new Response(response.body, {
      status: response.status,
      headers: {
        "content-type": response.headers.get("content-type") ?? "application/json",
        "cache-control": streaming
          ? "no-cache, no-store, no-transform" : "no-store",
        "x-request-id": response.headers.get("x-request-id") ?? requestId,
        ...(streaming ? {"x-accel-buffering": "no"} : {}),
      },
    });
  } catch {
    return Response.json(
      {
        error: {
          code: "ask_service_unavailable",
          message: "Dịch vụ hỏi đáp tri thức tạm gián đoạn",
        },
        request_id: requestId,
      },
      {status: 503, headers: {"x-request-id": requestId}},
    );
  }
}

export const GET = proxy;
export const POST = proxy;
