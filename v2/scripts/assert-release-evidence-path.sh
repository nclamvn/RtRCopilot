#!/usr/bin/env bash
# Release evidence is generated after a candidate is built.  It must never be
# written into tracked candidate source, otherwise the capture itself changes
# build identity and invalidates its own provenance binding.
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
runtime_root="$project_root/eval/runtime"
target="${1:-}"
if [[ -z "$target" ]]; then
  echo "RELEASE EVIDENCE PATH FAIL · target is required" >&2
  exit 2
fi

resolved="$({
  cd "$project_root"
  python3 - "$target" <<'PY'
import sys
from pathlib import Path

print(Path(sys.argv[1]).resolve())
PY
})"

case "$resolved" in
  "$project_root"/*)
    if [[ "$resolved" != "$runtime_root"/* ]]; then
      relative="${resolved#"$project_root"/}"
      echo "RELEASE EVIDENCE PATH FAIL · in-repository target must stay under eval/runtime: $relative" >&2
      exit 2
    fi
    ;;
esac

printf '%s\n' "$resolved"
