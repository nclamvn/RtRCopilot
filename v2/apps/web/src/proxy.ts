import {NextRequest, NextResponse} from "next/server";

export function hasTraversalPath(pathname: string) {
  let decoded = pathname;
  for (let attempt = 0; attempt < 4; attempt += 1) {
    const segments = decoded.replaceAll("\\", "/").split("/");
    if (segments.some(segment => segment === "." || segment === "..")) return true;
    try {
      const next = decodeURIComponent(decoded);
      if (next === decoded) return false;
      decoded = next;
    } catch {
      return true;
    }
  }
  return true;
}

export function proxy(request: NextRequest) {
  if (hasTraversalPath(request.nextUrl.pathname)) {
    return NextResponse.json(
      {error: {code: "invalid_request_path", message: "Request path is invalid"}},
      {status: 400},
    );
  }
  return NextResponse.next();
}

export const config = {
  matcher: "/api/:path*",
};
