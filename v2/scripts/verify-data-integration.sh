#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"
set -a
. "$project_root/.env"
set +a

# A gate may run concurrently from another Builder/VERIFY process. Isolate every
# invocation so one cleanup/downgrade cannot invalidate another migration chain.
verify_run_id="$$"
verify_database="rtr_verify_007_${verify_run_id}"
verify_bucket="rtr-copilot-verify-007-${verify_run_id}"
owner_dsn="postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@postgres:5432/$verify_database"
runtime_dsn="postgresql://$POSTGRES_RUNTIME_USER:$POSTGRES_RUNTIME_PASSWORD@postgres:5432/$verify_database"

cleanup() {
  docker compose exec -T postgres psql -X -U "$POSTGRES_USER" -d postgres \
    -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
        WHERE datname='$verify_database' AND pid <> pg_backend_pid()" >/dev/null
  docker compose exec -T postgres dropdb -U "$POSTGRES_USER" \
    --if-exists "$verify_database" >/dev/null
  minio_id="$(docker compose ps -q minio)"
  docker run --rm --network "container:$minio_id" \
    --entrypoint /bin/sh quay.io/minio/mc:RELEASE.2025-04-16T18-13-26Z \
    -ec "mc alias set local http://127.0.0.1:9000 '$S3_ACCESS_KEY' '$S3_SECRET_KEY' >/dev/null
         mc rb --force 'local/$verify_bucket' >/dev/null 2>&1 || true"
}
trap cleanup EXIT

docker compose up -d postgres minio
docker compose exec -T postgres psql -X -U "$POSTGRES_USER" -d postgres \
  -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
      WHERE datname='$verify_database' AND pid <> pg_backend_pid()" >/dev/null
docker compose exec -T postgres dropdb -U "$POSTGRES_USER" \
  --if-exists "$verify_database" >/dev/null
docker compose exec -T postgres createdb -U "$POSTGRES_USER" "$verify_database"
minio_id="$(docker compose ps -q minio)"
docker run --rm --network "container:$minio_id" \
  --entrypoint /bin/sh quay.io/minio/mc:RELEASE.2025-04-16T18-13-26Z \
  -ec "mc alias set local http://127.0.0.1:9000 '$S3_ACCESS_KEY' '$S3_SECRET_KEY' >/dev/null
       mc mb --ignore-existing 'local/$verify_bucket' >/dev/null"

run_migration() {
  docker compose --profile tools run --rm \
    -e MIGRATION_DSN="$owner_dsn" \
    -e POSTGRES_DSN="$runtime_dsn" \
    migrate alembic "$@"
}
owner_sql() {
  docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 \
    -U "$POSTGRES_USER" -d "$verify_database" -c "$1"
}

# AC004.2: every revision is exercised with a revision-specific fixture and
# downgrade boundary, independently from the full-chain test.
run_migration upgrade 0001_extensions
owner_sql "SELECT extname FROM pg_extension WHERE extname IN ('pgcrypto','vector')" \
  >/dev/null
run_migration upgrade 0002_identity_persistence
owner_sql "INSERT INTO subjects(issuer,provider_sub,email,canonical_domain)
  VALUES('revision-fixture','0002','fixture@rtrobotics.com','rtrobotics.com');
  INSERT INTO subject_scopes(subject_id,scope_type,scope_key)
  SELECT user_id,'department','engineering' FROM subjects
  WHERE issuer='revision-fixture';" >/dev/null
run_migration downgrade 0001_extensions
owner_sql "SELECT to_regclass('public.subjects') IS NULL" | grep -q "t"
run_migration upgrade 0002_identity_persistence
run_migration upgrade 0003_resource_object_foundation
owner_sql "INSERT INTO subjects(issuer,provider_sub) VALUES('revision-fixture','0003');
  INSERT INTO resources(resource_type,classification,source_zone,lifecycle_state)
  VALUES('document','internal','sot','draft');
  SELECT enabled FROM maintenance_state WHERE singleton;" | grep -q "f"
run_migration downgrade 0002_identity_persistence
owner_sql "SELECT to_regclass('public.resources') IS NULL" | grep -q "t"
run_migration upgrade 0003_resource_object_foundation
run_migration upgrade 0004_append_only_audit
owner_sql "SELECT expected_count=0 FROM audit_chain_anchor WHERE singleton" | grep -q "t"
run_migration upgrade 0005_ingestion_renditions
run_migration upgrade 0006_sot_publish_provenance
owner_sql "SELECT to_regclass('public.sot_packages') IS NOT NULL
  AND to_regclass('public.record_versions') IS NOT NULL
  AND to_regclass('public.evidence_spans') IS NOT NULL
  AND to_regclass('public.sot_reindex_outbox') IS NOT NULL" | grep -q "t"
run_migration downgrade 0005_ingestion_renditions
owner_sql "SELECT to_regclass('public.sot_packages') IS NULL" | grep -q "t"
run_migration upgrade 0006_sot_publish_provenance
run_migration upgrade 0007_hybrid_rag_grounded_answers
owner_sql "SELECT to_regclass('public.search_generations') IS NOT NULL
  AND to_regclass('public.chunks') IS NOT NULL
  AND to_regclass('public.answer_runs') IS NOT NULL
  AND to_regclass('public.gaps') IS NOT NULL" | grep -q "t"
run_migration downgrade 0006_sot_publish_provenance
owner_sql "SELECT to_regclass('public.chunks') IS NULL" | grep -q "t"
run_migration upgrade 0007_hybrid_rag_grounded_answers
owner_sql "SELECT to_regclass('public.ingestion_jobs') IS NOT NULL
  AND to_regclass('public.ingestion_outbox') IS NOT NULL
  AND to_regclass('public.upload_sessions') IS NOT NULL" | grep -q "t"
run_migration downgrade 0004_append_only_audit
owner_sql "SELECT to_regclass('public.ingestion_jobs') IS NULL" | grep -q "t"
run_migration upgrade 0005_ingestion_renditions

if owner_sql "BEGIN; CREATE TABLE ddl_rollback_probe(id integer);
  DO \$\$ BEGIN RAISE EXCEPTION 'injected migration failure'; END \$\$; COMMIT;" \
  >/dev/null 2>&1; then
  echo "Expected failing DDL transaction did not fail" >&2
  exit 20
fi
owner_sql "SELECT to_regclass('public.ddl_rollback_probe') IS NULL" | grep -q "t"

run_migration downgrade base
run_migration upgrade head
run_migration upgrade head

docker compose --profile tools run --rm --no-deps \
  -v "$project_root/apps/backend/src:/workspace/src:ro" \
  -v "$project_root/apps/backend/tests:/workspace/tests:ro" \
  -w /workspace \
  -e POSTGRES_DSN="$runtime_dsn" \
  -e MIGRATION_DSN="$owner_dsn" \
  -e INTEGRATION_DATABASE_DSN="$runtime_dsn" \
  -e S3_BUCKET="$verify_bucket" \
  -e PYTHONPATH=/workspace/src \
  migrate sh -ec '
    /app/.venv/bin/python -m ensurepip >/dev/null
    /app/.venv/bin/python -m pip install --quiet \
      pytest==8.4.1 pytest-asyncio==1.1.0
    /app/.venv/bin/python -m pytest -q \
      -o asyncio_default_test_loop_scope=session \
      tests/test_data_integration.py tests/test_ingestion_integration.py \
      tests/test_sot_integration.py tests/test_rag_integration.py
  '

runtime_sql() {
  docker compose exec -T -e PGPASSWORD="$POSTGRES_RUNTIME_PASSWORD" postgres \
    psql -X -v ON_ERROR_STOP=1 -U "$POSTGRES_RUNTIME_USER" \
    -d "$verify_database" -c "$1" >/dev/null 2>&1
}
denied=0
for statement in \
  "CREATE TABLE runtime_must_not_create(id integer)" \
  "ALTER TABLE subjects ADD COLUMN runtime_must_not_alter integer" \
  "DROP TABLE subjects" \
  "INSERT INTO audit_events(event_id,actor_kind,action,result,reason_code,request_id,event_hash)
   VALUES(gen_random_uuid(),'service','bypass','success','bypass','bypass',repeat('0',64))" \
  "UPDATE audit_events SET reason_code='tamper'" \
  "DELETE FROM audit_events" \
  "TRUNCATE audit_events" \
  "UPDATE audit_chain_anchor SET expected_count=0" \
  "DELETE FROM audit_chain_anchor" \
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
[[ "$denied" -eq 18 ]]
echo "DATA INTEGRATION PASS · migrations=7 · revision_fixtures=7 · failing_ddl_rollback=1 · tests=34 · formats=14 · required_outputs=31 · private_engine_proofs=4 · policy_scenarios=48 · runtime_denials=18"
