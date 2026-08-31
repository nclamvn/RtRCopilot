#!/usr/bin/env bash
# Hermetic production-build browser gate (TIP-043.1).
#
# The caller must create apps/web/.next/standalone first. This runner owns a
# disposable standalone copy, an ephemeral loopback port, readiness, Playwright
# output and teardown. It never falls back to a dev server or an existing app.
set -Eeuo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
standalone_source="$project_root/apps/web/.next/standalone"
static_source="$project_root/apps/web/.next/static"
runs="${BROWSER_QA_RUNS:-1}"
server_pid=""
qa_root="$(mktemp -d "${TMPDIR:-/tmp}/rtr-browser-production.XXXXXX")"
server_log="$qa_root/next.log"

cleanup() {
  local status=$?
  trap - EXIT INT TERM
  if [[ -n "$server_pid" ]] && kill -0 "$server_pid" 2>/dev/null; then
    kill "$server_pid" 2>/dev/null || true
    wait "$server_pid" 2>/dev/null || true
  fi
  rm -rf "$qa_root"
  exit "$status"
}
trap cleanup EXIT
trap 'exit 130' INT
trap 'exit 143' TERM

if ! [[ "$runs" =~ ^[1-9][0-9]*$ ]]; then
  echo "BROWSER_QA_RUNS must be a positive integer" >&2
  exit 2
fi
if [[ ! -f "$standalone_source/apps/web/server.js" ]] || [[ ! -d "$static_source" ]]; then
  echo "Production standalone build is missing; run pnpm --filter @rtr/web build" >&2
  exit 3
fi

# Keep the checked-out build immutable and all generated Playwright artifacts
# disposable. The standalone trace is small enough to copy locally (~23 MB).
cp -R "$standalone_source" "$qa_root/standalone"
mkdir -p "$qa_root/standalone/apps/web/.next"
if [[ ! -d "$qa_root/standalone/apps/web/.next/static" ]]; then
  cp -R "$static_source" "$qa_root/standalone/apps/web/.next/static"
fi
if [[ -d "$project_root/apps/web/public" ]] \
  && [[ ! -d "$qa_root/standalone/apps/web/public" ]]; then
  cp -R "$project_root/apps/web/public" "$qa_root/standalone/apps/web/public"
fi

if [[ -n "${PLAYWRIGHT_PORT:-}" ]]; then
  port="$PLAYWRIGHT_PORT"
else
  port="$(node -e '
    const net = require("node:net");
    const server = net.createServer();
    server.listen(0, "127.0.0.1", () => {
      process.stdout.write(String(server.address().port));
      server.close();
    });
  ')"
fi
if ! [[ "$port" =~ ^[0-9]+$ ]] || ((port < 1 || port > 65535)); then
  echo "PLAYWRIGHT_PORT must be an integer from 1 to 65535" >&2
  exit 4
fi

base_url="http://127.0.0.1:$port"
echo "BROWSER PRODUCTION QA · start=$base_url · runs=$runs"
(
  cd "$qa_root/standalone"
  exec env \
    API_INTERNAL_URL="${BROWSER_QA_API_INTERNAL_URL:-http://127.0.0.1:9}" \
    HOSTNAME=127.0.0.1 \
    PORT="$port" \
    node apps/web/server.js
) >"$server_log" 2>&1 &
server_pid=$!

deadline=$((SECONDS + 60))
until curl -fs -o /dev/null --max-time 3 "$base_url/ask"; do
  if ! kill -0 "$server_pid" 2>/dev/null; then
    cat "$server_log" >&2 || true
    echo "Production web server exited before readiness" >&2
    exit 5
  fi
  if ((SECONDS >= deadline)); then
    cat "$server_log" >&2 || true
    echo "Production web server readiness timed out" >&2
    exit 6
  fi
  sleep 1
done

for ((run = 1; run <= runs; run += 1)); do
  echo "BROWSER PRODUCTION QA · run=$run/$runs"
  env -u NO_COLOR -u FORCE_COLOR \
    PLAYWRIGHT_BASE_URL="$base_url" \
    PLAYWRIGHT_OUTPUT_DIR="$qa_root/test-results-$run" \
    pnpm --dir "$project_root" --filter @rtr/web test:browser
done

kill "$server_pid"
wait "$server_pid" 2>/dev/null || true
if kill -0 "$server_pid" 2>/dev/null; then
  echo "Production web server survived teardown" >&2
  exit 7
fi
server_pid=""
echo "BROWSER PRODUCTION QA PASS · runs=$runs · teardown=clean"
