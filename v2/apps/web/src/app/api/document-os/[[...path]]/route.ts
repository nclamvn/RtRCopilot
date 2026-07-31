import {NextRequest} from "next/server";

type RouteContext = {params: Promise<{path?: string[]}>};

const SAFE_SEGMENT = /^[A-Za-z0-9._~-]+$/;

function valid(segment: string) {
  return SAFE_SEGMENT.test(segment) && segment !== "." && segment !== "..";
}

async function proxy(request: NextRequest, context: RouteContext) {
  const segments = (await context.params).path ?? [];
  if (segments.length === 0 || segments.some(segment => !valid(segment))) {
    return Response.json(
      {error: {code: "invalid_document_path", message: "Document request is invalid"}},
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
      {error: {code: "document_service_unavailable", message: "Dịch vụ tài liệu tạm gián đoạn"}},
      {status: 503, headers: {"x-request-id": requestId}},
    );
  }
}

export const GET = proxy;
export const POST = proxy;
