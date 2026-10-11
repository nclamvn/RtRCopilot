#!/usr/bin/env bash
# Serial finite native→cold restore→resume/deadline keeps the original120s window.
set -euo pipefail
experiment_dir=$(cd "$(dirname "$0")" && pwd)
run_id=${TIP054_FULL_RUN_ID:-tip054-4b-full-20261006-r2}
native_id=${TIP054_NATIVE_ID:-native_frozen_r4}
restore_id=${TIP054_RESTORE_ID:-restore_frozen_r4}
[[ "$native_id" =~ ^[a-z0-9_]{1,24}$ && "$restore_id" =~ ^[a-z0-9_]{1,24}$ ]] || exit 2
runner="$run_id-runner"
[[ $(docker inspect --format '{{index .Config.Labels "tip054.executor"}}' "$runner") == "$run_id" ]] || exit 2
TIP054_FULL_RUN_ID="$run_id" TIP054_NATIVE_ID="$native_id" TIP054_NATIVE_ONLY_MODE=after_draft_commit bash "$experiment_dir/run-native-gates.sh"
TIP054_FULL_RUN_ID="$run_id" TIP054_NATIVE_ID="$native_id" TIP054_RESTORE_ID="$restore_id" bash "$experiment_dir/run-restore-gate.sh"
evidence="$experiment_dir/raw/$run_id/$restore_id"; container_evidence="/evidence/$restore_id"
base=(PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/qa/packages:/workspace/v2/apps/backend/src TMPDIR=/tmp APP_ENV=test ACTION_EXECUTOR_ENABLED=true
  POSTGRES_DSN="postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/rtr_tip054_restore_$restore_id"
  ACTION_WORKFLOW_DSN="postgresql://rtr_tip054_engine:rtr_tip054_synthetic_only@tip054-pg:5432/rtr_tip054_re_$restore_id"
  TIP054_RESTORE_ORIGINAL="/evidence/$native_id/after_draft_commit"
  REDIS_URL=redis://tip054-redis:6379/0 S3_ENDPOINT=http://tip054-minio:9000 S3_ACCESS_KEY=rtr_tip054_local S3_SECRET_KEY=rtr_tip054_synthetic_only S3_BUCKET=rtr-tip054-synthetic RAG_EMBEDDING_PROVIDER=offline RAG_PROVIDER_MODE=local)
exec_runner() { docker exec "$runner" env -i "${base[@]}" "$@"; }
exec_runner /app/.venv/bin/python /work/source_snapshot.py "$container_evidence/pause-source-before.json" > "$evidence/pause-source-before.stdout.txt"
set +e
exec_runner /app/.venv/bin/python /work/pause_probe.py proof "$container_evidence" > "$evidence/pause-supervisor.stdout.txt" 2> "$evidence/pause-supervisor.stderr.txt"
code=$?
set -e
exec_runner /app/.venv/bin/python /work/source_snapshot.py "$container_evidence/pause-source-after.json" > "$evidence/pause-source-after.stdout.txt"
printf '{"returncode":%d}\n' "$code" > "$evidence/pause-returncode.json"
cmp "$evidence/pause-source-before.json" "$evidence/pause-source-after.json"
exit "$code"
