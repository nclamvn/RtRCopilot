import {NextResponse} from "next/server";

export async function GET() {
  const requestId = crypto.randomUUID();
  try {
    const response = await fetch(`${process.env.API_INTERNAL_URL}/health/ready`, {
      cache: "no-store",
      signal: AbortSignal.timeout(3000),
      headers: {"X-Request-ID": requestId},
    });
    const body = await response.json();
    return NextResponse.json(body, {
      status: response.ok ? 200 : 503,
      headers: {"X-Request-ID": requestId},
    });
  } catch {
    return NextResponse.json(
      {ok: false, status: "unavailable", dependencies: {}, request_id: requestId},
      {status: 503, headers: {"X-Request-ID": requestId}},
    );
  }
}
