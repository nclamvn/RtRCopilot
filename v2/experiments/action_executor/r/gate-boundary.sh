#!/usr/bin/env bash
# Manual source-wheel or scripted gate boundary; never performs the child gate.
set -euo pipefail
r_dir=$(cd "$(dirname "$0")" && pwd)
experiment_dir=$(cd "$r_dir/.." && pwd)
repo_root=$(cd "$experiment_dir/../../.." && pwd)
run_id=${TIP054_FULL_RUN_ID:?explicit new owned fixture id required}
gate_id=${1:?unique gate id required}; phase=${2:?begin or end required}
expected=${TIP054_PRODUCT_FROZEN_SHA256:?explicit Contractor product freeze required}
[[ "$run_id" =~ ^tip054-4b-full-[a-z0-9-]{1,30}$ ]] || exit 2
[[ "$gate_id" =~ ^[a-z0-9_]{1,24}$ ]] || exit 2
[[ "$expected" =~ ^[a-f0-9]{64}$ ]] || exit 2
[[ "$phase" == begin || "$phase" == end ]] || exit 2
runner="$run_id-runner"; pg="$run_id-pg"
for target in "$runner" "$pg"; do
  [[ $(docker inspect --format '{{index .Config.Labels "tip054.executor"}}' "$target") == "$run_id" ]] || exit 2
done
evidence="$experiment_dir/raw/$run_id/r_bind_$gate_id"
output="/evidence/r_bind_$gate_id"
cd "$repo_root"
if [[ "$phase" == begin ]]; then
  [[ ! -e "$evidence" ]] || exit 2
  mkdir -p "$evidence"
  printf '%s\n' "$expected" > "$evidence/expected-product.sha256"
  docker exec "$pg" df -k /var/lib/postgresql/data > "$evidence/capacity-before.txt"
  free_kib=$(awk 'NR==2 {print $4}' "$evidence/capacity-before.txt")
  [[ "$free_kib" =~ ^[0-9]+$ && "$free_kib" -ge 524288 ]] || exit 66
  rg --files v2/apps/backend/src v2/apps/backend/migrations v2/apps/backend/pyproject.toml v2/apps/backend/uv.lock v2/.env.example | LC_ALL=C sort | xargs shasum -a 256 | shasum -a 256 > "$evidence/product-before.sha256"
  read -r actual ignored < "$evidence/product-before.sha256"
  [[ "$actual" == "$expected" ]] || exit 2
  docker exec "$runner" env -i PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 /app/.venv/bin/python /work/r/source_snapshot.py "$output/source-before.json" > "$evidence/source-before.stdout.txt"
else
  [[ -e "$evidence/source-before.json" && ! -e "$evidence/source-after.json" ]] || exit 2
  docker exec "$runner" env -i PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 /app/.venv/bin/python /work/r/source_snapshot.py "$output/source-after.json" > "$evidence/source-after.stdout.txt"
  rg --files v2/apps/backend/src v2/apps/backend/migrations v2/apps/backend/pyproject.toml v2/apps/backend/uv.lock v2/.env.example | LC_ALL=C sort | xargs shasum -a 256 | shasum -a 256 > "$evidence/product-after.sha256"
  docker exec "$pg" df -k /var/lib/postgresql/data > "$evidence/capacity-after.txt"
  docker exec "$runner" env -i PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 /app/.venv/bin/python /work/r/finish_boundary.py "$output" "${3:-unknown}" > "$evidence/binding.stdout.txt"
fi
