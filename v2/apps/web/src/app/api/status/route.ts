import {NextResponse} from "next/server";

/**
 * TIP-012 Task 1: the browser-facing status endpoint reports only the
 * aggregate readiness. The per-dependency map from /health/ready names
 * internal services (compose hostnames) and must not cross the ingress;
 * operators read the detail from the API's own /health/ready inside the
 * network. The UI consumes only {ok, status}.
 */
export async function GET() {
  const requestId = crypto.randomUUID();
  try {
    const response = await fetch(`${process.env.API_INTERNAL_URL}/health/ready`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
      headers: {"X-Request-ID": requestId},
    });
    const body = await response.json() as {ok?: unknown; status?: unknown};
    return NextResponse.json(
      {
        ok: response.ok && body.ok === true,
        status: typeof body.status === "string" ? body.status : "unavailable",
        request_id: requestId,
      },
      {status: response.ok ? 200 : 503, headers: {"X-Request-ID": requestId}},
    );
  } catch {
    return NextResponse.json(
      {ok: false, status: "unavailable", request_id: requestId},
      {status: 503, headers: {"X-Request-ID": requestId}},
    );
  }
}
