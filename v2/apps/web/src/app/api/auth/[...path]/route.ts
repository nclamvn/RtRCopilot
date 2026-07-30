import {NextRequest} from "next/server";

type RouteContext = {params: Promise<{path: string[]}>};

async function proxy(request: NextRequest, context: RouteContext) {
  const {path} = await context.params;
  const requestId = request.headers.get("X-Request-ID") ?? crypto.randomUUID();
  const headers = new Headers({"X-Request-ID": requestId});
  const cookie = request.headers.get("cookie");
  const contentType = request.headers.get("content-type");
  if (cookie) headers.set("cookie", cookie);
  if (contentType) headers.set("content-type", contentType);

  const upstream = new URL(
    `/auth/${path.join("/")}${request.nextUrl.search}`,
    process.env.API_INTERNAL_URL,
  );
  const response = await fetch(upstream, {
    method: request.method,
    headers,
    body: request.method === "GET" || request.method === "HEAD"
      ? undefined
      : await request.arrayBuffer(),
    cache: "no-store",
    redirect: "manual",
    signal: AbortSignal.timeout(5000),
  });
  const responseHeaders = new Headers();
  for (const name of ["content-type", "location", "set-cookie", "x-request-id"]) {
    const value = response.headers.get(name);
    if (value) responseHeaders.set(name, value);
  }
  return new Response(response.body, {
    status: response.status,
    headers: responseHeaders,
  });
}

export const GET = proxy;
export const POST = proxy;
