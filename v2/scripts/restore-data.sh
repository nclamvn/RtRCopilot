#!/usr/bin/env bash
set -euo pipefail

archive="${1:-}"
target="${2:-}"
confirmation="${3:-}"
project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
set -a
. "$project_root/.env"
set +a

if [[ -z "$archive" || -z "$target" ]]; then
  echo "Usage: restore-data.sh archive target-name RESTORE:target-name" >&2
  exit 2
fi
if [[ ! -f "$archive" || ! -r "$archive" ]]; then
  echo "Restore archive does not exist or is unreadable" >&2
  exit 3
fi
if [[ ! "$target" =~ ^[a-z0-9][a-z0-9-]{1,61}[a-z0-9]$ ]]; then
  echo "Target must satisfy the strict S3 bucket naming subset" >&2
  exit 4
fi
if [[ "$confirmation" != "RESTORE:$target" ]]; then
  echo "Typed confirmation mismatch; expected RESTORE:$target" >&2
  exit 5
fi
if [[ "$target" == "$POSTGRES_DB" || "$target" == "$S3_BUCKET" ]]; then
  echo "Restore target must be isolated from active database and bucket" >&2
  exit 6
fi

work_dir="$(mktemp -d)"
operation_id="$(python3 -c 'import uuid; print(uuid.uuid4())')"
created_database="false"
created_bucket="false"
bucket_claimed="false"
restore_succeeded="false"
cleanup() {
  exit_code=$?
  cleanup_failed="false"
  set +e
  if [[ "$restore_succeeded" != "true" ]]; then
    if [[ "$created_database" == "true" ]]; then
      database_owner="$(docker compose exec -T postgres psql -At \
        -U "$POSTGRES_USER" -d "$target" \
        -c "SELECT operation_id FROM rtr_restore_operation WHERE singleton" \
        2>/dev/null)"
      if [[ "$database_owner" == "$operation_id" ]]; then
        docker compose exec -T postgres dropdb -U "$POSTGRES_USER" "$target" \
          >/dev/null || cleanup_failed="true"
      else
        echo "RECOVERY REQUIRED: database ownership became ambiguous; target quarantined" >&2
        cleanup_failed="true"
      fi
    fi
    if [[ "$bucket_claimed" == "true" ]]; then
      guard_args=(
        --profile tools run --rm
        -e "S3_BUCKET=$target"
        migrate python -m rtr_copilot.commands.restore_bucket_guard cleanup
        --bucket "$target" --operation-id "$operation_id"
      )
      if [[ "$created_bucket" == "true" ]]; then
        guard_args+=(--created-bucket)
      fi
      docker compose "${guard_args[@]}" >/dev/null || cleanup_failed="true"
    fi
    if [[ "${RESTORE_TEST_FORCE_CLEANUP_FAILURE:-false}" == "true" ]]; then
      cleanup_failed="true"
    fi
  fi
  rm -rf "$work_dir"
  if [[ "$cleanup_failed" == "true" ]]; then
    echo "RESTORE CLEANUP FAILED operation_id=$operation_id; explicit recovery required" >&2
    exit_code=90
  fi
  trap - EXIT
  exit "$exit_code"
}
trap cleanup EXIT

# Local archive/checksum/inventory validation is deliberately completed before
# creating a database or bucket.
tar -tzf "$archive" >/dev/null
tar -xzf "$archive" -C "$work_dir"
python3 - "$work_dir" <<'PY'
import hashlib
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
manifest_path = root / "manifest.json"
dump_path = root / "database.dump"
inventory_path = root / "minio-inventory.json"
for required in (manifest_path, dump_path, inventory_path, root / "objects"):
    if not required.exists():
        raise SystemExit(f"archive missing required entry: {required.name}")
manifest = json.loads(manifest_path.read_text())
inventory = json.loads(inventory_path.read_text())
if manifest.get("manifest_version") != 1:
    raise SystemExit("unsupported manifest version")
if inventory != manifest.get("minio_inventory"):
    raise SystemExit("inventory file differs from manifest")
actual_dump = hashlib.sha256(dump_path.read_bytes()).hexdigest()
if actual_dump != manifest["database"]["sha256"]:
    raise SystemExit("dump checksum mismatch")
seen = set()
for item in inventory:
    key = item["key"]
    if key in seen or key.startswith("/") or ".." in pathlib.PurePosixPath(key).parts:
        raise SystemExit(f"unsafe or duplicate object key: {key}")
    seen.add(key)
    path = root / "objects" / pathlib.PurePosixPath(key)
    if not path.is_file():
        raise SystemExit(f"missing object payload: {key}")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != item["sha256"] or path.stat().st_size != item["byte_size"]:
        raise SystemExit(f"object payload mismatch: {key}")
PY

exists="$(docker compose exec -T postgres psql -At -U "$POSTGRES_USER" -d postgres \
  -c "SELECT 1 FROM pg_database WHERE datname='$target'")"
if [[ -n "$exists" ]]; then
  echo "Restore database target already exists" >&2
  exit 7
fi

minio_id="$(docker compose ps -q minio)"
bucket_state="$(docker run --rm --network "container:$minio_id" \
  --entrypoint /bin/sh quay.io/minio/mc:RELEASE.2025-04-16T18-13-26Z \
  -ec "mc alias set local http://127.0.0.1:9000 '$S3_ACCESS_KEY' '$S3_SECRET_KEY' >/dev/null
       if mc stat 'local/$target' >/dev/null 2>&1; then
         if test -n \"\$(mc ls --recursive 'local/$target')\"; then
           echo nonempty
         else
           echo empty
         fi
       else
         echo absent
       fi")"
if [[ "$bucket_state" == "nonempty" ]]; then
  echo "Restore bucket target is not empty" >&2
  exit 8
fi

if [[ -n "${RESTORE_TEST_RACE_OBJECT_KEY:-}" ]]; then
  docker run --rm --network "container:$minio_id" \
    --entrypoint /bin/sh quay.io/minio/mc:RELEASE.2025-04-16T18-13-26Z \
    -ec "mc alias set local http://127.0.0.1:9000 '$S3_ACCESS_KEY' '$S3_SECRET_KEY' >/dev/null
         mc mb --ignore-existing 'local/$target' >/dev/null
         printf third-party-race | mc pipe 'local/$target/$RESTORE_TEST_RACE_OBJECT_KEY' >/dev/null"
fi

started_epoch="$(date +%s)"
if [[ "$bucket_state" == "absent" ]]; then
  docker run --rm --network "container:$minio_id" \
    --entrypoint /bin/sh quay.io/minio/mc:RELEASE.2025-04-16T18-13-26Z \
    -ec "mc alias set local http://127.0.0.1:9000 '$S3_ACCESS_KEY' '$S3_SECRET_KEY' >/dev/null
         mc mb 'local/$target' >/dev/null"
  created_bucket="true"
fi
docker compose --profile tools run --rm \
  -e "S3_BUCKET=$target" \
  migrate python -m rtr_copilot.commands.restore_bucket_guard claim \
  --bucket "$target" --operation-id "$operation_id" >/dev/null
bucket_claimed="true"

docker compose exec -T postgres createdb -U "$POSTGRES_USER" "$target"
created_database="true"
docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 \
  -U "$POSTGRES_USER" -d "$target" <<SQL >/dev/null
CREATE TABLE rtr_restore_operation (
  singleton boolean PRIMARY KEY DEFAULT true CHECK (singleton),
  operation_id uuid NOT NULL,
  state text NOT NULL CHECK (state IN ('restoring','ready','recovery_required')),
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now()
);
INSERT INTO rtr_restore_operation(singleton, operation_id, state)
VALUES (true, '$operation_id', 'restoring');
SQL
if [[ "${RESTORE_TEST_FAIL_AFTER_DATABASE:-false}" == "true" ]]; then
  echo "Injected restore failure after database ownership marker" >&2
  false
fi
docker compose exec -T postgres pg_restore -U "$POSTGRES_USER" \
  -d "$target" --no-owner --no-privileges <"$work_dir/database.dump"

docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 \
  -U "$POSTGRES_USER" -d "$target" <<'SQL' >/dev/null
GRANT USAGE ON SCHEMA public TO rtr_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO rtr_app;
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO rtr_app;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON audit_events FROM rtr_app;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON audit_chain_anchor FROM rtr_app;
REVOKE INSERT, UPDATE, DELETE ON alembic_version FROM rtr_app;
REVOKE DELETE ON
  sot_packages, records, record_versions, evidence_spans, sot_publish_runs,
  sot_active_revisions, sot_reindex_outbox, search_generations,
  active_search_generations, chunks, index_jobs, messages, answer_runs,
  answer_citations, templates, template_versions, template_bindings,
  render_jobs, document_publication_outbox, render_job_bindings, generated_files, approvals,
  document_issuances, research_sources, research_packages, research_records,
  gaps, gap_transitions, review_tasks, graduation_proposals,
  governance_settings
FROM rtr_app;
REVOKE UPDATE ON research_records, gap_transitions, governance_settings
FROM rtr_app;
GRANT EXECUTE ON FUNCTION append_audit_event(
  uuid,timestamptz,text,uuid,text,text,text,text,text,uuid,text,uuid[],
  jsonb,char(64),char(64),integer
) TO rtr_app;
REVOKE CREATE ON SCHEMA public FROM rtr_app;
SQL

while IFS='|' read -r object_key object_sha object_size; do
  [[ -z "$object_key" ]] && continue
  docker run --rm --network "container:$minio_id" \
    -v "$work_dir/objects:/objects:ro" \
    --entrypoint /bin/sh quay.io/minio/mc:RELEASE.2025-04-16T18-13-26Z \
    -ec "mc alias set local http://127.0.0.1:9000 '$S3_ACCESS_KEY' '$S3_SECRET_KEY' >/dev/null
         mc cp --attr 'sha256=$object_sha;byte-size=$object_size;upload-state=restored;restore-operation-id=$operation_id' \
           '/objects/$object_key' 'local/$target/$object_key' >/dev/null"
done < <(python3 - "$work_dir/manifest.json" <<'PY'
import json
import sys
for item in json.load(open(sys.argv[1]))["minio_inventory"]:
    print(f"{item['key']}|{item['sha256']}|{item['byte_size']}")
PY
)

docker compose --profile tools run --rm \
  -v "$work_dir:/restore:ro" \
  -e "S3_BUCKET=$target" \
  migrate python -m rtr_copilot.commands.restore_bucket_guard complete \
  --bucket "$target" --operation-id "$operation_id" \
  --expected-path /restore/minio-inventory.json >/dev/null

revision="$(docker compose exec -T postgres psql -At -U "$POSTGRES_USER" -d "$target" \
  -c 'SELECT version_num FROM alembic_version')"
[[ "$revision" == "0012_enterprise_governance" ]] || exit 10
broken_links="$(docker compose exec -T postgres psql -At -U "$POSTGRES_USER" -d "$target" \
  -c "SELECT count(*) FROM documents d LEFT JOIN document_versions v
      ON v.version_id=d.current_version_id
      WHERE d.current_version_id IS NOT NULL AND v.version_id IS NULL")"
[[ "$broken_links" == "0" ]] || exit 11
sot_broken_links="$(docker compose exec -T postgres psql -At -U "$POSTGRES_USER" -d "$target" \
  -c "SELECT count(*) FROM records r
      LEFT JOIN record_versions rv ON rv.version_id=r.current_version_id
      WHERE r.lifecycle='active' AND (
        rv.version_id IS NULL OR rv.lifecycle<>'active'
      )")"
[[ "$sot_broken_links" == "0" ]] || exit 11
sot_integrity_errors="$(docker compose exec -T postgres psql -At -U "$POSTGRES_USER" -d "$target" \
  -c "SELECT
      (SELECT count(*) FROM evidence_spans e
       LEFT JOIN record_versions rv ON rv.version_id=e.record_version_id
       WHERE rv.version_id IS NULL)
      + (SELECT count(*) FROM sot_active_revisions ar
         LEFT JOIN sot_packages p ON p.package_id=ar.package_id
         WHERE p.package_id IS NULL OR p.lifecycle<>'active'
           OR p.revision<>ar.revision OR p.payload_sha256<>ar.payload_sha256)
      + (SELECT count(*) FROM record_versions
         WHERE content_sha256 !~ '^[0-9a-f]{64}$')
      + (SELECT count(*) FROM evidence_spans
         WHERE evidence_sha256 !~ '^[0-9a-f]{64}$')
      + (SELECT count(*) FROM records r
         JOIN resources rs ON rs.resource_id=r.record_id
         JOIN record_versions rv ON rv.version_id=r.current_version_id
         WHERE r.lifecycle='active' AND (
           rv.owner_subject_id<>r.owner_subject_id
           OR rv.classification<>r.classification
           OR rv.classification<>rs.classification
           OR rv.department_id IS DISTINCT FROM r.department_id
           OR rv.department_id IS DISTINCT FROM rs.department_id
           OR rv.project_id IS DISTINCT FROM r.project_id
           OR rv.project_id IS DISTINCT FROM rs.project_id
         ))")"
[[ "$sot_integrity_errors" == "0" ]] || exit 11
sot_delete_grants="$(docker compose exec -T postgres psql -At -U "$POSTGRES_USER" -d "$target" \
  -c "SELECT count(*) FROM unnest(ARRAY[
      'sot_packages','records','record_versions','evidence_spans',
      'sot_publish_runs','sot_active_revisions','sot_reindex_outbox'
    ]) table_name
    WHERE has_table_privilege('$POSTGRES_RUNTIME_USER',table_name,'DELETE')")"
[[ "$sot_delete_grants" == "0" ]] || exit 11
rag_integrity_errors="$(docker compose exec -T postgres psql -At -U "$POSTGRES_USER" -d "$target" \
  -c "SELECT
      (SELECT count(*) FROM active_search_generations ag
       LEFT JOIN search_generations g ON g.generation_id=ag.generation_id
       WHERE g.generation_id IS NULL OR g.lifecycle<>'active'
         OR g.source_key<>ag.source_key
         OR g.source_revision<>ag.source_revision
         OR g.index_fingerprint<>ag.index_fingerprint)
      + (SELECT count(*) FROM chunks c
         LEFT JOIN search_generations g ON g.generation_id=c.generation_id
         LEFT JOIN record_versions rv ON rv.version_id=c.record_version_id
         WHERE g.generation_id IS NULL OR rv.version_id IS NULL
           OR c.text_sha256 !~ '^[0-9a-f]{64}$'
           OR c.record_checksum !~ '^[0-9a-f]{64}$')
      + (SELECT count(*) FROM answer_citations ac
         LEFT JOIN answer_runs ar ON ar.answer_run_id=ac.answer_run_id
         LEFT JOIN chunks c ON c.chunk_id=ac.chunk_id
         WHERE ar.answer_run_id IS NULL OR c.chunk_id IS NULL
           OR ac.record_checksum<>c.record_checksum
           OR ac.record_version_id<>c.record_version_id)")"
[[ "$rag_integrity_errors" == "0" ]] || exit 11
rag_delete_grants="$(docker compose exec -T postgres psql -At -U "$POSTGRES_USER" -d "$target" \
  -c "SELECT count(*) FROM unnest(ARRAY[
      'search_generations','active_search_generations','chunks','index_jobs',
      'messages','answer_runs','answer_citations'
    ]) table_name
    WHERE has_table_privilege('$POSTGRES_RUNTIME_USER',table_name,'DELETE')")"
[[ "$rag_delete_grants" == "0" ]] || exit 11
document_os_integrity_errors="$(docker compose exec -T postgres psql -At \
  -U "$POSTGRES_USER" -d "$target" -c "SELECT
    (SELECT count(*) FROM template_versions tv
     LEFT JOIN templates t ON t.template_id=tv.template_id
     LEFT JOIN object_blobs o ON o.object_id=tv.source_object_id
     WHERE t.template_id IS NULL OR o.object_id IS NULL
       OR tv.source_sha256<>o.sha256)
    + (SELECT count(*) FROM generated_files g
       LEFT JOIN render_jobs j ON j.render_job_id=g.render_job_id
       LEFT JOIN document_versions v ON v.version_id=g.version_id
       LEFT JOIN object_blobs o ON o.object_id=g.object_id
       WHERE j.render_job_id IS NULL OR v.version_id IS NULL
         OR o.object_id IS NULL OR g.checksum<>v.sha256 OR g.checksum<>o.sha256)
    + (SELECT count(*) FROM document_publication_outbox p
       LEFT JOIN render_jobs j ON j.render_job_id=p.render_job_id
       WHERE j.render_job_id IS NULL
         OR (p.state='finalized' AND p.finalized_at IS NULL))
    + (SELECT count(*) FROM approvals a
       LEFT JOIN generated_files g ON g.generated_file_id=a.generated_file_id
       WHERE g.generated_file_id IS NULL OR a.checksum<>g.checksum)
    + (SELECT count(*) FROM document_issuances i
       LEFT JOIN generated_files g ON g.generated_file_id=i.generated_file_id
       WHERE g.generated_file_id IS NULL OR i.issued_checksum<>g.checksum)")"
[[ "$document_os_integrity_errors" == "0" ]] || exit 11
document_os_delete_grants="$(docker compose exec -T postgres psql -At \
  -U "$POSTGRES_USER" -d "$target" -c "SELECT count(*) FROM unnest(ARRAY[
    'templates','template_versions','template_bindings','render_jobs',
    'document_publication_outbox','render_job_bindings','generated_files',
    'approvals','document_issuances'
  ]) table_name
  WHERE has_table_privilege('$POSTGRES_RUNTIME_USER',table_name,'DELETE')")"
[[ "$document_os_delete_grants" == "0" ]] || exit 11

restored_counts="$(docker compose exec -T postgres psql -At -U "$POSTGRES_USER" \
  -d "$target" -c \
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
   SELECT 'sot_packages',count(*) FROM sot_packages UNION ALL
   SELECT 'records',count(*) FROM records UNION ALL
   SELECT 'record_versions',count(*) FROM record_versions UNION ALL
   SELECT 'evidence_spans',count(*) FROM evidence_spans UNION ALL
   SELECT 'sot_publish_runs',count(*) FROM sot_publish_runs UNION ALL
   SELECT 'sot_active_revisions',count(*) FROM sot_active_revisions UNION ALL
   SELECT 'sot_reindex_outbox',count(*) FROM sot_reindex_outbox UNION ALL
   SELECT 'search_generations',count(*) FROM search_generations UNION ALL
   SELECT 'active_search_generations',count(*) FROM active_search_generations UNION ALL
   SELECT 'chunks',count(*) FROM chunks UNION ALL
   SELECT 'index_jobs',count(*) FROM index_jobs UNION ALL
   SELECT 'conversations',count(*) FROM conversations UNION ALL
   SELECT 'messages',count(*) FROM messages UNION ALL
   SELECT 'answer_runs',count(*) FROM answer_runs UNION ALL
   SELECT 'answer_citations',count(*) FROM answer_citations UNION ALL
   SELECT 'gaps',count(*) FROM gaps UNION ALL
   SELECT 'research_sources',count(*) FROM research_sources UNION ALL
   SELECT 'research_packages',count(*) FROM research_packages UNION ALL
   SELECT 'research_records',count(*) FROM research_records UNION ALL
   SELECT 'gap_transitions',count(*) FROM gap_transitions UNION ALL
   SELECT 'review_tasks',count(*) FROM review_tasks UNION ALL
   SELECT 'graduation_proposals',count(*) FROM graduation_proposals UNION ALL
   SELECT 'governance_settings',count(*) FROM governance_settings UNION ALL
   SELECT 'templates',count(*) FROM templates UNION ALL
   SELECT 'template_versions',count(*) FROM template_versions UNION ALL
   SELECT 'template_bindings',count(*) FROM template_bindings UNION ALL
   SELECT 'render_jobs',count(*) FROM render_jobs UNION ALL
   SELECT 'document_publication_outbox',count(*) FROM document_publication_outbox UNION ALL
   SELECT 'render_job_bindings',count(*) FROM render_job_bindings UNION ALL
   SELECT 'generated_files',count(*) FROM generated_files UNION ALL
   SELECT 'approvals',count(*) FROM approvals UNION ALL
   SELECT 'document_issuances',count(*) FROM document_issuances UNION ALL
   SELECT 'object_blobs',count(*) FROM object_blobs UNION ALL
   SELECT 'audit_events',count(*) FROM audit_events) q")"
restored_audit="$(docker compose exec -T postgres psql -At -U "$POSTGRES_USER" \
  -d "$target" -c \
  "SELECT json_build_object('count',expected_count,
   'sequence',coalesce(head_sequence,0),'head_hash',head_hash)
   FROM audit_chain_anchor WHERE singleton")"
python3 - "$work_dir/manifest.json" "$restored_counts" "$restored_audit" <<'PY'
import json
import sys
manifest = json.load(open(sys.argv[1]))
if manifest["row_counts"] != json.loads(sys.argv[2]):
    raise SystemExit("restored row counts differ from manifest")
if manifest["audit"] != json.loads(sys.argv[3]):
    raise SystemExit("restored audit anchor differs from manifest")
PY

runtime_dsn="postgresql://$POSTGRES_RUNTIME_USER:$POSTGRES_RUNTIME_PASSWORD@postgres:5432/$target"
runtime_sql() {
  docker compose exec -T -e PGPASSWORD="$POSTGRES_RUNTIME_PASSWORD" postgres \
    psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_RUNTIME_USER" \
    -d "$target" -c "$1" >/dev/null 2>&1
}
denied=0
for statement in \
  "CREATE TABLE runtime_must_not_create(id integer)" \
  "ALTER TABLE subjects ADD COLUMN runtime_must_not_alter integer" \
  "DROP TABLE subjects" \
  "INSERT INTO audit_events(event_id,actor_kind,action,result,reason_code,request_id,event_hash)
   VALUES(gen_random_uuid(),'service','bypass','success','bypass','bypass',repeat('0',64))" \
  "UPDATE audit_events SET reason_code='tamper'" \
  "DELETE FROM audit_chain_anchor" \
  "TRUNCATE audit_events" \
  "DELETE FROM record_versions" \
  "DELETE FROM evidence_spans" \
  "DELETE FROM sot_reindex_outbox" \
  "DELETE FROM chunks" \
  "UPDATE chunks SET normalized_text='tamper'" \
  "DELETE FROM answer_citations" \
  "UPDATE answer_citations SET marker='C999'" \
  "DELETE FROM messages" \
  "UPDATE messages SET sanitized_content='tamper'"
do
  if ! runtime_sql "$statement"; then
    denied=$((denied + 1))
  fi
done
[[ "$denied" -eq 16 ]] || { echo "Runtime grants verification failed" >&2; exit 12; }

docker compose --profile tools run --rm \
  -e POSTGRES_DSN="$runtime_dsn" \
  -e S3_BUCKET="$target" \
  migrate python -m rtr_copilot.commands.verify_audit >/dev/null
docker compose --profile tools run --rm \
  -e POSTGRES_DSN="$runtime_dsn" \
  -e S3_BUCKET="$target" \
  migrate python -m rtr_copilot.commands.repository_smoke >/dev/null
docker compose --profile tools run --rm \
  -e S3_BUCKET="$target" \
  migrate python -m rtr_copilot.commands.object_inventory \
  >"$work_dir/restored-inventory.json"
python3 - "$work_dir/manifest.json" "$work_dir/restored-inventory.json" <<'PY'
import json
import sys
expected = json.load(open(sys.argv[1]))["minio_inventory"]
actual = json.load(open(sys.argv[2]))
for item in actual:
    item["bucket"] = expected[0]["bucket"] if expected else item["bucket"]
if expected != actual:
    raise SystemExit("restored object inventory differs from manifest")
PY

docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 \
  -U "$POSTGRES_USER" -d "$target" \
  -c "UPDATE rtr_restore_operation SET state='ready', updated_at=now()
      WHERE singleton AND operation_id='$operation_id'" >/dev/null
restore_succeeded="true"
duration="$(( $(date +%s) - started_epoch ))"
object_count="$(python3 -c "import json; print(len(json.load(open('$work_dir/manifest.json'))['minio_inventory']))")"
echo "RESTORE PASS operation_id=$operation_id target=$target revision=$revision objects=$object_count row_counts=100% checksums=100% audit_chain=valid runtime_denials=16 duration_seconds=$duration"
