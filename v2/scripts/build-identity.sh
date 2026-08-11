#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

head_sha="$(git rev-parse --short=12 HEAD 2>/dev/null || printf development)"
untracked_files="$(git ls-files --others --exclude-standard -- .)"
if git diff --quiet HEAD -- . && [[ -z "$untracked_files" ]]; then
  printf '%s\n' "$head_sha"
  exit 0
fi

# A development build can legitimately include tracked changes before commit.
# Attach a deterministic content fingerprint so two different dirty builds can
# never both report the same checkout SHA. Production deployment remains clean
# and therefore reports the plain immutable commit SHA.
worktree_sha="$({
  git diff --no-ext-diff --binary HEAD -- .
  while IFS= read -r path; do
    [[ -n "$path" ]] || continue
    printf 'untracked:%s:' "$path"
    shasum -a 256 -- "$path"
  done <<<"$untracked_files"
} | shasum -a 256 | cut -c1-12)"
printf '%s+%s\n' "$head_sha" "$worktree_sha"
