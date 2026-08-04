#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
repository_root="$(cd "$project_root/.." && pwd)"
cd "$project_root"

pnpm install --frozen-lockfile
pnpm verify:web
if command -v uv >/dev/null 2>&1; then
  (cd apps/backend && uv sync --frozen && uv run ruff check . && uv run mypy && uv run pytest)
else
  docker run --rm \
    -v "$repository_root:/workspace" \
    -v rtr-copilot-verify-uv-cache:/root/.cache/uv \
    -w /workspace/v2/apps/backend \
    python:3.12.4-slim \
    sh -ec 'apt-get update -qq &&
      apt-get install --no-install-recommends --yes fonts-dejavu-core=2.37-6 >/dev/null &&
      pip install --no-cache-dir uv==0.8.11 >/dev/null &&
      export UV_PROJECT_ENVIRONMENT=/tmp/rtr-verify-venv &&
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
