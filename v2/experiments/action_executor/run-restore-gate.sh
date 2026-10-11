#!/usr/bin/env bash
# Finite cold logical domain+engine restore only; owned synthetic namespaces.
set -euo pipefail
experiment_dir=$(cd "$(dirname "$0")" && pwd)
run_id=${TIP054_FULL_RUN_ID:-tip054-4b-full-20261006-r1}
native_id=${TIP054_NATIVE_ID:-native_frozen_r1}
gate_id=${TIP054_RESTORE_ID:-restore_r1}
[[ "$native_id" =~ ^[a-z0-9_]{1,24}$ && "$gate_id" =~ ^[a-z0-9_]{1,24}$ ]] || exit 2
runner="$run_id-runner"; pg="$run_id-pg"
original="/evidence/$native_id/after_draft_commit"
evidence="$experiment_dir/raw/$run_id/$gate_id"; container_evidence="/evidence/$gate_id"
[[ ! -e "$evidence" && -f "$experiment_dir/raw/$run_id/$native_id/after_draft_commit/native-proof.json" ]] || exit 2
for target in "$runner" "$pg"; do [[ $(docker inspect --format '{{index .Config.Labels "tip054.executor"}}' "$target") == "$run_id" ]] || exit 2; done
mkdir -p "$evidence"
source_domain="rtr_tip054_n_${native_id}_i3"; source_engine="rtr_tip054_ne_${native_id}_i3"
restored_domain="rtr_tip054_restore_${gate_id}"; restored_engine="rtr_tip054_re_${gate_id}"
base=(PATH=/app/.venv/bin:/usr/local/bin:/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=/qa/packages:/workspace/v2/apps/backend/src TMPDIR=/tmp APP_ENV=test ACTION_EXECUTOR_ENABLED=true
  REDIS_URL=redis://tip054-redis:6379/0 S3_ENDPOINT=http://tip054-minio:9000 S3_ACCESS_KEY=rtr_tip054_local S3_SECRET_KEY=rtr_tip054_synthetic_only S3_BUCKET=rtr-tip054-synthetic RAG_EMBEDDING_PROVIDER=offline RAG_PROVIDER_MODE=local)
exec_source() { docker exec "$runner" env -i "${base[@]}" POSTGRES_DSN="postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/$source_domain" ACTION_WORKFLOW_DSN="postgresql://rtr_tip054_engine:rtr_tip054_synthetic_only@tip054-pg:5432/$source_engine" "$@"; }
exec_restored() { docker exec "$runner" env -i "${base[@]}" POSTGRES_DSN="postgresql://rtr_app:rtr_tip054_synthetic_only@tip054-pg:5432/$restored_domain" ACTION_WORKFLOW_DSN="postgresql://rtr_tip054_engine:rtr_tip054_synthetic_only@tip054-pg:5432/$restored_engine" "$@"; }
exec_source /app/.venv/bin/python /work/source_snapshot.py "$container_evidence/source-before.json" > "$evidence/source-before.stdout.txt"
exec_source TIP054_RESTORE_FINGERPRINT=original-fingerprints.json /app/.venv/bin/python /work/restore_probe.py fingerprint "$container_evidence" > "$evidence/original-fingerprints.stdout.txt" 2> "$evidence/original-fingerprints.stderr.txt"
docker exec "$pg" pg_dump -U rtr_tip054_local -Fc -d "$source_domain" -f "/tmp/${restored_domain}.dump" > "$evidence/domain-dump.stdout.txt" 2> "$evidence/domain-dump.stderr.txt"
docker exec "$pg" pg_dump -U rtr_tip054_local -Fc -d "$source_engine" -f "/tmp/${restored_engine}.dump" > "$evidence/engine-dump.stdout.txt" 2> "$evidence/engine-dump.stderr.txt"
docker exec "$pg" dd "if=/tmp/${restored_domain}.dump" status=none > "$evidence/domain.dump"
docker exec "$pg" dd "if=/tmp/${restored_engine}.dump" status=none > "$evidence/engine.dump"
docker exec "$pg" psql -U rtr_tip054_local -d rtr_tip054_executor_verify -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$restored_domain\";" > "$evidence/databases.txt"
docker exec "$pg" psql -U rtr_tip054_local -d rtr_tip054_executor_verify -v ON_ERROR_STOP=1 -c "CREATE DATABASE \"$restored_engine\" OWNER rtr_tip054_engine;" >> "$evidence/databases.txt"
docker exec "$pg" pg_restore -U rtr_tip054_local --exit-on-error -d "$restored_domain" "/tmp/${restored_domain}.dump" > "$evidence/domain-restore.stdout.txt" 2> "$evidence/domain-restore.stderr.txt"
docker exec "$pg" pg_restore -U rtr_tip054_local --exit-on-error -d "$restored_engine" "/tmp/${restored_engine}.dump" > "$evidence/engine-restore.stdout.txt" 2> "$evidence/engine-restore.stderr.txt"
docker exec "$pg" psql -U rtr_tip054_local -d "$restored_domain" -v ON_ERROR_STOP=1 -c "REVOKE CONNECT ON DATABASE \"$restored_domain\" FROM PUBLIC; GRANT CONNECT ON DATABASE \"$restored_domain\" TO rtr_app; REVOKE CONNECT ON DATABASE \"$restored_engine\" FROM PUBLIC; GRANT CONNECT ON DATABASE \"$restored_engine\" TO rtr_tip054_engine;" >> "$evidence/databases.txt"
exec_restored TIP054_RESTORE_FINGERPRINT=restored-fingerprints.json /app/.venv/bin/python /work/restore_probe.py fingerprint "$container_evidence" > "$evidence/restored-fingerprints.stdout.txt" 2> "$evidence/restored-fingerprints.stderr.txt"
cmp "$evidence/original-fingerprints.json" "$evidence/restored-fingerprints.json" > "$evidence/fingerprint-compare.txt"
exec_restored TIP054_RESTORE_ORIGINAL="$original" /app/.venv/bin/python /work/restore_probe.py resume "$container_evidence" > "$evidence/resume-supervisor.stdout.txt" 2> "$evidence/resume-supervisor.stderr.txt"
exec_restored TIP054_RESTORE_ORIGINAL="$original" /app/.venv/bin/python /work/restore_probe.py incompatible "$container_evidence" > "$evidence/incompatible-supervisor.stdout.txt" 2> "$evidence/incompatible-supervisor.stderr.txt"
exec_restored /app/.venv/bin/python /work/source_snapshot.py "$container_evidence/source-after.json" > "$evidence/source-after.stdout.txt"
cmp "$evidence/source-before.json" "$evidence/source-after.json"
echo 'COLD_LOGICAL_ENGINE_DOMAIN_RESTORE_PASS sourceobjectstoreimmutable_retained_notobjectstoreDR'
