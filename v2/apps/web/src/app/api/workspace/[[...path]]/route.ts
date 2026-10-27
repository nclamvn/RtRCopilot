import {NextRequest} from "next/server";

type Context = {params: Promise<{path?: string[]}>};
const families = new Set(["session", "status", "workspaces", "artifacts", "runs"]);
export function workspaceUpstream(value: string | undefined): URL {
  const url = new URL(value ?? "http://127.0.0.1:8110");
  if (url.protocol !== "http:" || !["localhost", "127.0.0.1", "[::1]"].includes(url.hostname)
    || url.username || url.password || url.pathname !== "/" || url.search || url.hash) throw new Error("Invalid workspace upstream");
  return url;
}
async function proxy(request: NextRequest, context: Context) {
  if (process.env.WORKSPACE_UI_ENABLED !== "1") return Response.json({detail: "workspace_disabled"}, {status: 404});
  // Defense against browser DNS rebinding; the supported workspace launcher
  // also binds Next to loopback. Host/Origin are not proof of peer locality.
  try {
    const host = new URL(`http://${request.headers.get("host") ?? request.nextUrl.host}`);
    if (!["localhost", "127.0.0.1", "[::1]"].includes(host.hostname) || host.username || host.password || host.pathname !== "/") throw new Error("Host denied");
  } catch {return Response.json({detail: "workspace_host_denied"}, {status: 403});}
  const path = (await context.params).path ?? [];
  if (!families.has(path[0]) || path.some(part => !/^[a-zA-Z0-9_-]+$/.test(part))) {
    return Response.json({detail: "invalid_workspace_path"}, {status: 400});
  }
  const headers = new Headers({accept: request.headers.get("accept")?.includes("text/event-stream") ? "text/event-stream" : "application/json"});
  for (const key of ["content-type", "origin", "last-event-id"]) {const value = request.headers.get(key); if (value) headers.set(key, value);}
  // Never relay legacy sessions or caller-supplied identity headers.
  const session = request.cookies.get("workspace_session")?.value;
  if (session) headers.set("cookie", `workspace_session=${encodeURIComponent(session)}`);
  try {
    const upstream = new URL(`/api/workspace/${path.join("/")}${request.nextUrl.search}`, workspaceUpstream(process.env.WORKSPACE_API_INTERNAL_URL));
    const result = await fetch(upstream, {method: request.method, headers, cache: "no-store", redirect: "manual",
      body: request.method === "GET" ? undefined : request.body,
      // Aborting this subscription does not issue a cancellation command.
      signal: request.signal, ...(request.method === "GET" ? {} : {duplex: "half"})} as RequestInit & {duplex?: "half"});
    const responseHeaders = new Headers({"cache-control": "no-store, no-transform", "x-accel-buffering": "no"});
    for (const key of ["content-type", "content-disposition"]) {const value = result.headers.get(key); if (value) responseHeaders.set(key, value);}
    for (const cookie of result.headers.getSetCookie()) responseHeaders.append("set-cookie", cookie);
    return new Response(result.body, {status: result.status, headers: responseHeaders});
  } catch {
    return Response.json({detail: "workspace_service_unavailable"}, {status: 503});
  }
}
export const GET = proxy;
export const POST = proxy;
