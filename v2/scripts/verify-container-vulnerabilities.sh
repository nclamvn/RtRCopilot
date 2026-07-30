#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

scanner_image="aquasec/trivy@sha256:086971aaf400beebd94e8300fd8ea623774419597169156cec56eec5b00dfb1e"
target_image="${RTR_SCAN_IMAGE:-rtr-copilot-v2-api:latest}"
scan_dir="$(mktemp -d "${TMPDIR:-/tmp}/rtr-trivy.XXXXXXXX")"
trap 'rm -rf -- "$scan_dir"' EXIT

docker image inspect "$target_image" >/dev/null
docker save --output "$scan_dir/image.tar" "$target_image"
docker run --rm \
  --volume "$scan_dir:/scan:ro" \
  --volume rtr-trivy-cache:/root/.cache/trivy \
  "$scanner_image" image \
  --input /scan/image.tar \
  --scanners vuln \
  --severity HIGH,CRITICAL \
  --ignore-unfixed \
  --exit-code 1 \
  --skip-version-check \
  --no-progress
