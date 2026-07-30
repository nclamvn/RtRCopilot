#!/usr/bin/env bash
set -euo pipefail

destination="${1:-}"
requested_maintenance="${MAINTENANCE_MODE:-}"
if [[ -z "$destination" ]]; then
  echo "Usage: backup-data.sh /explicit/destination" >&2
  exit 2
fi

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
set -a
. "$project_root/.env"
set +a
if [[ -n "$requested_maintenance" ]]; then
  MAINTENANCE_MODE="$requested_maintenance"
fi
if [[ "${MAINTENANCE_MODE:-false}" != "true" ]]; then
  echo "Backup requires MAINTENANCE_MODE=true (write pause)." >&2
  exit 3
fi
mkdir -p "$destination"
work_dir="$(mktemp -d)"
paused="false"
cleanup() {
  exit_code=$?
  set +e
  if [[ "$paused" == "true" ]]; then
    docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 \
      -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<SQL >/dev/null
BEGIN;
SELECT pg_advisory_xact_lock(827005);
UPDATE maintenance_state
SET enabled=false, reason=NULL, changed_at=now(), changed_by='backup-data.sh'
WHERE singleton;
COMMIT;
SQL
  fi
  rm -rf "$work_dir"
  exit "$exit_code"
}
trap cleanup EXIT
started="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
started_epoch="$(date +%s)"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"

docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 \
  -U "$POSTGRES_USER" -d "$POSTGRES_DB" <<SQL >/dev/null
BEGIN;
SELECT pg_advisory_xact_lock(827005);
UPDATE maintenance_state
SET enabled=true, reason='consistent_backup', changed_at=now(),
    changed_by='backup-data.sh'
WHERE singleton;
COMMIT;
SQL
paused="true"
docker compose --profile tools run --rm migrate \
  python -m rtr_copilot.commands.mutation_probe >/dev/null

docker compose exec -T postgres pg_dump \
  -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc >"$work_dir/database.dump"
database_sha="$(shasum -a 256 "$work_dir/database.dump" | awk '{print $1}')"

docker compose --profile tools run --rm migrate \
  python -m rtr_copilot.commands.object_inventory \
  >"$work_dir/minio-inventory.json"
minio_id="$(docker compose ps -q minio)"
docker run --rm --network "container:$minio_id" \
  -v "$work_dir:/backup" \
  --entrypoint /bin/sh quay.io/minio/mc:RELEASE.2025-04-16T18-13-26Z \
  -ec "mc alias set local http://127.0.0.1:9000 '$S3_ACCESS_KEY' '$S3_SECRET_KEY' >/dev/null
       mkdir -p /backup/objects
       mc mirror --overwrite 'local/$S3_BUCKET' /backup/objects >/dev/null"

revision="$(docker compose exec -T postgres psql -At -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" -c 'SELECT version_num FROM alembic_version')"
audit_summary="$(docker compose exec -T postgres psql -At -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" -c \
  "SELECT json_build_object('count',expected_count,
   'sequence',coalesce(head_sequence,0),'head_hash',head_hash)
   FROM audit_chain_anchor WHERE singleton")"
row_counts="$(docker compose exec -T postgres psql -At -U "$POSTGRES_USER" \
  -d "$POSTGRES_DB" -c \
  "SELECT json_object_agg(name,total) FROM (
   SELECT 'subjects' name,count(*) total FROM subjects UNION ALL
   SELECT 'subject_scopes',count(*) FROM subject_scopes UNION ALL
   SELECT 'resources',count(*) FROM resources UNION ALL
   SELECT 'acl_entries',count(*) FROM acl_entries UNION ALL
   SELECT 'documents',count(*) FROM documents UNION ALL
   SELECT 'document_versions',count(*) FROM document_versions UNION ALL
   SELECT 'renditions',count(*) FROM renditions UNION ALL
   SELECT 'upload_sessions',count(*) FROM upload_sessions UNION ALL
   SELECT 'ingestion_jobs',count(*) FROM ingestion_jobs UNION ALL
   SELECT 'ingestion_outbox',count(*) FROM ingestion_outbox UNION ALL
   SELECT 'object_blobs',count(*) FROM object_blobs UNION ALL
   SELECT 'audit_events',count(*) FROM audit_events) q")"
finished="$(date -u +%Y-%m-%dT%H:%M:%SZ)"
duration="$(( $(date +%s) - started_epoch ))"

python3 - "$work_dir/manifest.json" <<PY
import json, pathlib
inventory = []
path = pathlib.Path("$work_dir/minio-inventory.json")
if path.exists():
    inventory = json.loads(path.read_text())
manifest = {
    "manifest_version": 1,
    "started_at": "$started",
    "finished_at": "$finished",
    "application_version": "0.1.0",
    "alembic_revision": "$revision",
    "database": {"format": "postgres-custom", "sha256": "$database_sha"},
    "minio_inventory": inventory,
    "audit": json.loads('''$audit_summary'''),
    "row_counts": json.loads('''$row_counts'''),
    "duration_seconds": $duration,
    "measured_rpo_window_seconds": $duration,
}
pathlib.Path("$work_dir/manifest.json").write_text(
    json.dumps(manifest, indent=2, sort_keys=True) + "\n"
)
PY

archive="$destination/rtr-copilot-v2-$timestamp.tar.gz"
tar -C "$work_dir" -czf "$archive" database.dump manifest.json minio-inventory.json objects
echo "BACKUP PASS archive=$archive bytes=$(stat -f%z "$archive") duration_seconds=$duration"
