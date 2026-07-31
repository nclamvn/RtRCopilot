import http from "node:http";

const publicPort = Number.parseInt(process.env.PORT ?? "3000", 10);
const internalPort = publicPort + 1;

function hasTraversal(rawUrl) {
  let decoded = rawUrl.split("?", 1)[0];
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

process.env.PORT = String(internalPort);
process.env.HOSTNAME = "127.0.0.1";
await import("./apps/web/server.js");

http.createServer((request, response) => {
  if (hasTraversal(request.url ?? "/")) {
    response.writeHead(400, {
      "content-type": "application/json; charset=utf-8",
      "cache-control": "no-store",
      "x-content-type-options": "nosniff",
    });
    response.end(JSON.stringify({
      error: {code: "invalid_request_path", message: "Request path is invalid"},
    }));
    return;
  }
  const upstream = http.request({
    hostname: "127.0.0.1",
    port: internalPort,
    path: request.url,
    method: request.method,
    headers: request.headers,
  }, upstreamResponse => {
    response.writeHead(upstreamResponse.statusCode ?? 502, upstreamResponse.headers);
    upstreamResponse.pipe(response);
  });
  upstream.on("error", () => {
    if (!response.headersSent) {
      response.writeHead(503, {
        "content-type": "application/json; charset=utf-8",
        "cache-control": "no-store",
      });
    }
    response.end(JSON.stringify({
      error: {code: "web_upstream_unavailable", message: "Web service unavailable"},
    }));
  });
  request.pipe(upstream);
}).listen(publicPort, "0.0.0.0");
