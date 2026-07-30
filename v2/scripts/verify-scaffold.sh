#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

pnpm install --frozen-lockfile
pnpm verify:web
if command -v uv >/dev/null 2>&1; then
  (cd apps/backend && uv sync --frozen && uv run ruff check . && uv run mypy && uv run pytest)
else
  docker run --rm \
    -v "$project_root/apps/backend:/app" \
    -w /app \
    python:3.12.4-slim \
    sh -ec 'pip install --no-cache-dir uv==0.8.11 >/dev/null &&
      uv sync --frozen &&
      uv run ruff check . &&
      uv run mypy &&
      uv run pytest'
fi
docker compose config --quiet
docker compose build
./scripts/verify-container-vulnerabilities.sh
./scripts/verify-data-integration.sh
echo "VERIFY PASS"
