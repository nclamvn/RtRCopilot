import {NextResponse} from "next/server";

/**
 * TIP-012 Task 1: the browser-facing status endpoint reports only the
 * aggregate operational readiness. The per-dependency map from
 * /health/operational names
 * internal services (compose hostnames) and must not cross the ingress;
 * operators read the detail from the API's own /health/ready inside the
 * network. The UI consumes only the aggregate state and the non-sensitive
 * source build identity.
 */
export async function GET() {
  const requestId = crypto.randomUUID();
  const webBuildSha = process.env.RTR_BUILD_SHA ?? "development";
  try {
    const response = await fetch(`${process.env.API_INTERNAL_URL}/health/operational`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
      headers: {"X-Request-ID": requestId},
    });
    const body = await response.json() as {ok?: unknown; status?: unknown; build_sha?: unknown};
    const apiBuildSha = typeof body.build_sha === "string" ? body.build_sha : "unavailable";
    const sameBuild = apiBuildSha === webBuildSha;
    const ok = response.ok && body.ok === true && sameBuild;
    return NextResponse.json(
      {
        ok,
        status: !sameBuild
          ? "version_mismatch"
          : typeof body.status === "string" ? body.status : "unavailable",
        build_sha: webBuildSha,
        request_id: requestId,
      },
      {status: ok ? 200 : 503, headers: {"X-Request-ID": requestId}},
    );
  } catch {
    return NextResponse.json(
      {ok: false, status: "unavailable", build_sha: webBuildSha, request_id: requestId},
      {status: 503, headers: {"X-Request-ID": requestId}},
    );
  }
}
