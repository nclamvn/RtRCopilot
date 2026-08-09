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
verify_database="rtr_verify_009_${verify_run_id}"
verify_bucket="rtr-copilot-verify-009-${verify_run_id}"
restore_database="${verify_database}_restore"
restore_bucket="${verify_bucket}-restore"
verify_redis_database="${RTR_VERIFY_REDIS_DATABASE:-15}"
if ! [[ "$verify_redis_database" =~ ^([1-9]|1[0-5])$ ]]; then
  echo "RTR_VERIFY_REDIS_DATABASE must be an isolated Redis DB from 1 to 15" >&2
  exit 2
fi
verify_redis_url="redis://redis:6379/${verify_redis_database}"
# AC18 runs against its own database so the pytest phase's deterministic
# residue (templates, render jobs, issuances) can never skew the seeded counts.
ac18_database="${verify_database}_ac18"
owner_dsn="postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@postgres:5432/$verify_database"
runtime_dsn="postgresql://$POSTGRES_RUNTIME_USER:$POSTGRES_RUNTIME_PASSWORD@postgres:5432/$verify_database"

cleanup() {
  # Tolerant: the EXIT trap is armed before `compose up`, so if startup fails
  # (services never became healthy) these teardown calls must not error out
  # under `set -e` and mask the real failure. Best-effort, then restore -e.
  set +e
  docker compose exec -T postgres psql -X -U "$POSTGRES_USER" -d postgres \
    -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
        WHERE datname='$verify_database' AND pid <> pg_backend_pid()" >/dev/null 2>&1
  docker compose exec -T postgres psql -X -U "$POSTGRES_USER" -d postgres \
    -c "SELECT pg_terminate_backend(pid) FROM pg_stat_activity
        WHERE datname='$ac18_database' AND pid <> pg_backend_pid()" >/dev/null 2>&1
  docker compose exec -T postgres dropdb -U "$POSTGRES_USER" \
    --if-exists "$verify_database" >/dev/null 2>&1
  docker compose exec -T postgres dropdb -U "$POSTGRES_USER" \
    --if-exists "$restore_database" >/dev/null 2>&1
  docker compose exec -T postgres dropdb -U "$POSTGRES_USER" \
    --if-exists "$ac18_database" >/dev/null 2>&1
  docker compose exec -T redis redis-cli -n "$verify_redis_database" \
    FLUSHDB >/dev/null 2>&1
  minio_id="$(docker compose ps -q minio 2>/dev/null)"
  if [ -n "$minio_id" ]; then
    docker run --rm --network "container:$minio_id" \
      --entrypoint /bin/sh quay.io/minio/mc:RELEASE.2025-04-16T18-13-26Z \
      -ec "mc alias set local http://127.0.0.1:9000 '$S3_ACCESS_KEY' '$S3_SECRET_KEY' >/dev/null
           mc rb --force 'local/$verify_bucket' >/dev/null 2>&1 || true
           mc rb --force 'local/$restore_bucket' >/dev/null 2>&1 || true"
  fi
  set -e
}
trap cleanup EXIT

# --wait blocks until postgres/minio/redis report *healthy* via the healthchecks
# already declared in compose.yaml (postgres: pg_isready, retries 20×3s). Without
# it, the next `compose exec … psql` races the postmaster and fails with
# "connection to server on socket … .s.PGSQL.5432: No such file or directory".
# On failure the gate must surface evidence (TIP-030 PR #9: postgres reported
# unhealthy on 2/3 cold CI runners and no logs survived to diagnose why) —
# dump container state, the health-probe history and postgres logs, then fail.
if ! docker compose up -d --wait postgres minio redis; then
  echo "verify-data-integration: compose up --wait failed; startup evidence follows" >&2
  docker compose ps -a >&2 || true
  postgres_cid="$(docker compose ps -aq postgres 2>/dev/null || true)"
  if [ -n "$postgres_cid" ]; then
    docker inspect --format \
      '{{.Name}} status={{.State.Status}} exit={{.State.ExitCode}} oom={{.State.OOMKilled}} health={{json .State.Health}}' \
      "$postgres_cid" >&2 || true
  fi
  docker compose logs --no-color --tail 200 postgres >&2 || true
  exit 1
fi
# Breakers, budgets and rate limits are durable runtime state.  The integration
# gate must never inherit them from the developer stack or another prior run.
docker compose exec -T redis redis-cli -n "$verify_redis_database" FLUSHDB \
  >/dev/null
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

run_migration_for() {
  migration_database="$1"
  shift
  docker compose --profile tools run --rm \
    -v "$project_root/apps/backend/migrations:/app/migrations:ro" \
    -e MIGRATION_DSN="postgresql://$POSTGRES_USER:$POSTGRES_PASSWORD@postgres:5432/$migration_database" \
    -e POSTGRES_DSN="postgresql://$POSTGRES_RUNTIME_USER:$POSTGRES_RUNTIME_PASSWORD@postgres:5432/$migration_database" \
    migrate alembic "$@"
}
run_migration() {
  docker compose --profile tools run --rm \
    -v "$project_root/apps/backend/migrations:/app/migrations:ro" \
    -e MIGRATION_DSN="$owner_dsn" \
    -e POSTGRES_DSN="$runtime_dsn" \
    migrate alembic "$@"
}
owner_sql() {
  docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 \
    -U "$POSTGRES_USER" -d "$verify_database" -c "$1"
}
ac18_sql() {
  docker compose exec -T postgres psql -X -v ON_ERROR_STOP=1 \
    -U "$POSTGRES_USER" -d "$ac18_database" -c "$1"
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
run_migration upgrade 0008_document_operating_system
owner_sql "SELECT to_regclass('public.templates') IS NOT NULL
  AND to_regclass('public.template_versions') IS NOT NULL
  AND to_regclass('public.render_jobs') IS NOT NULL
  AND to_regclass('public.generated_files') IS NOT NULL
  AND to_regclass('public.approvals') IS NOT NULL
  AND to_regclass('public.document_issuances') IS NOT NULL" | grep -q "t"
run_migration downgrade 0007_hybrid_rag_grounded_answers
owner_sql "SELECT to_regclass('public.templates') IS NULL" | grep -q "t"
run_migration upgrade 0008_document_operating_system
run_migration upgrade 0009_governance_research
owner_sql "SELECT to_regclass('public.research_sources') IS NOT NULL
  AND to_regclass('public.research_packages') IS NOT NULL
  AND to_regclass('public.research_records') IS NOT NULL
  AND to_regclass('public.gap_transitions') IS NOT NULL
  AND to_regclass('public.review_tasks') IS NOT NULL
  AND to_regclass('public.graduation_proposals') IS NOT NULL
  AND to_regclass('public.governance_settings') IS NOT NULL" | grep -q "t"
run_migration downgrade 0008_document_operating_system
owner_sql "SELECT to_regclass('public.research_records') IS NULL" | grep -q "t"
run_migration upgrade 0009_governance_research
run_migration upgrade 0012_enterprise_governance
owner_sql "SELECT to_regclass('public.file_chunks') IS NOT NULL
  AND EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_name='answer_citations' AND column_name='file_chunk_id'
  )" | grep -q "t"
owner_sql "SELECT to_regclass('public.enterprise_domains') IS NOT NULL
  AND to_regclass('public.enterprise_corpus_manifests') IS NOT NULL
  AND to_regclass('public.enterprise_ontology_revisions') IS NOT NULL
  AND to_regclass('public.enterprise_evaluation_suites') IS NOT NULL
  AND to_regclass('public.enterprise_evaluation_runs') IS NOT NULL
  AND to_regclass('public.enterprise_release_attestations') IS NOT NULL" | grep -q "t"
run_migration downgrade 0011_ingestion_pub_deferred
owner_sql "SELECT to_regclass('public.enterprise_domains') IS NULL" | grep -q "t"
run_migration downgrade 0009_governance_research
owner_sql "SELECT to_regclass('public.file_chunks') IS NULL" | grep -q "t"
run_migration upgrade 0012_enterprise_governance
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

docker compose --profile tools run --rm --no-deps --build \
  -v "$project_root/apps/backend/src:/workspace/src:ro" \
  -v "$project_root/apps/backend/tests:/workspace/tests:ro" \
  -w /workspace \
  -e POSTGRES_DSN="$runtime_dsn" \
  -e MIGRATION_DSN="$owner_dsn" \
  -e INTEGRATION_DATABASE_DSN="$runtime_dsn" \
  -e RAG_BENCHMARK_P95_MS_MAX="${RAG_BENCHMARK_P95_MS_MAX:-500}" \
  -e REDIS_URL="$verify_redis_url" \
  -e S3_BUCKET="$verify_bucket" \
  -e PYTHONPATH=/workspace/src \
  migrate sh -ec '
    /app/.venv/bin/python -m ensurepip >/dev/null
    /app/.venv/bin/python -m pip install --quiet \
      pytest==8.4.1 pytest-asyncio==1.1.0
    /app/.venv/bin/python -m pytest -q \
      -o asyncio_default_test_loop_scope=session \
      tests/test_data_integration.py tests/test_ingestion_integration.py \
      tests/test_documents_integration.py \
      tests/test_sot_integration.py tests/test_rag_integration.py \
      tests/test_tip018_integration.py \
      tests/test_limits_integration.py \
      tests/test_governance_integration.py \
      tests/test_enterprise_governance_integration.py
  '

# AC18: prove a non-empty Document OS database/object backup can be restored
# with exact canonical lineage, checksums and runtime grants. The proof seeds
# a dedicated head-migrated database: the pytest phase above intentionally
# leaves document-OS rows behind in $verify_database, and AC18's count(*)=1
# assertions require an otherwise-empty schema.
docker compose exec -T postgres dropdb -U "$POSTGRES_USER" \
  --if-exists "$ac18_database" >/dev/null
docker compose exec -T postgres createdb -U "$POSTGRES_USER" "$ac18_database"
run_migration_for "$ac18_database" upgrade head
empty_sha="e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
ac18_sql "BEGIN;
  INSERT INTO subjects(user_id,issuer,provider_sub,email,canonical_domain,display_name)
  VALUES('99000000-0000-0000-0000-000000000001','tip009-recovery',
    '$verify_run_id','recovery@rtrobotics.com','rtrobotics.com','TIP-009 Recovery');
  INSERT INTO resources(resource_id,resource_type,owner_subject_id,classification,
    source_zone,lifecycle_state) VALUES
    ('99000000-0000-0000-0000-000000000010','template',
      '99000000-0000-0000-0000-000000000001','internal','sot','active'),
    ('99000000-0000-0000-0000-000000000011','template_version',
      '99000000-0000-0000-0000-000000000001','internal','sot','active'),
    ('99000000-0000-0000-0000-000000000012','object',
      '99000000-0000-0000-0000-000000000001','internal','sot','active'),
    ('99000000-0000-0000-0000-000000000020','document',
      '99000000-0000-0000-0000-000000000001','internal','sot','active'),
    ('99000000-0000-0000-0000-000000000021','document_version',
      '99000000-0000-0000-0000-000000000001','internal','sot','active'),
    ('99000000-0000-0000-0000-000000000022','object',
      '99000000-0000-0000-0000-000000000001','internal','sot','active');
  INSERT INTO object_blobs(object_id,bucket,object_key,sha256,byte_size,mime_type,
    storage_state,created_by,verified_at) VALUES
    ('99000000-0000-0000-0000-000000000012','$verify_bucket',
      'tip009-recovery/template.docx','$empty_sha',0,
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'available','99000000-0000-0000-0000-000000000001',now()),
    ('99000000-0000-0000-0000-000000000022','$verify_bucket',
      'tip009-recovery/output.docx','$empty_sha',0,
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
      'available','99000000-0000-0000-0000-000000000001',now());
  INSERT INTO templates(template_id,stable_key,display_name,category,owner_subject_id,
    classification,document_class,lifecycle)
  VALUES('99000000-0000-0000-0000-000000000010','tip009.recovery',
    'TIP-009 recovery fixture','recovery',
    '99000000-0000-0000-0000-000000000001','internal','official','approved');
  INSERT INTO template_versions(version_id,template_id,version_ordinal,format,
    source_object_id,source_sha256,field_schema,renderer_kind,renderer_version,
    status,created_by,approved_by,approved_at)
  VALUES('99000000-0000-0000-0000-000000000011',
    '99000000-0000-0000-0000-000000000010',1,'docx',
    '99000000-0000-0000-0000-000000000012','$empty_sha',
    '{\"type\":\"object\"}','docx_declarative','tip009-recovery','approved',
    '99000000-0000-0000-0000-000000000001',
    '99000000-0000-0000-0000-000000000001',now());
  UPDATE templates SET current_version_id=
    '99000000-0000-0000-0000-000000000011'
    WHERE template_id='99000000-0000-0000-0000-000000000010';
  INSERT INTO template_bindings(binding_id,template_version_id,field_path,field_type,
    source,required,rules)
  VALUES('99000000-0000-0000-0000-000000000013',
    '99000000-0000-0000-0000-000000000011','customer_name','string',
    'user',true,'{}');
  INSERT INTO documents(document_id,logical_name)
  VALUES('99000000-0000-0000-0000-000000000020','TIP-009 recovery output');
  INSERT INTO document_versions(version_id,document_id,version_no,object_id,
    original_filename,mime_type,sha256,byte_size,created_by)
  VALUES('99000000-0000-0000-0000-000000000021',
    '99000000-0000-0000-0000-000000000020',1,
    '99000000-0000-0000-0000-000000000022','output.docx',
    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '$empty_sha',0,'99000000-0000-0000-0000-000000000001');
  UPDATE documents SET current_version_id=
    '99000000-0000-0000-0000-000000000021'
    WHERE document_id='99000000-0000-0000-0000-000000000020';
  INSERT INTO render_jobs(render_job_id,requester_id,idempotency_key,
    canonical_input_hash,template_version_id,state,progress,request_id,
    started_at,finished_at)
  VALUES('99000000-0000-0000-0000-000000000030',
    '99000000-0000-0000-0000-000000000001','tip009-recovery-$verify_run_id',
    '$empty_sha','99000000-0000-0000-0000-000000000011','completed',100,
    'tip009-recovery',now(),now());
  INSERT INTO document_publication_outbox(outbox_id,render_job_id,state,payload,
    attempts,finalized_at)
  VALUES('99000000-0000-0000-0000-000000000031',
    '99000000-0000-0000-0000-000000000030','finalized',
    '{\"checksum\":\"$empty_sha\"}',1,now());
  INSERT INTO render_job_bindings(render_binding_id,render_job_id,field_path,source,
    canonical_value)
  VALUES('99000000-0000-0000-0000-000000000032',
    '99000000-0000-0000-0000-000000000030','customer_name','user',
    '\"Recovery Customer\"');
  INSERT INTO generated_files(generated_file_id,render_job_id,document_id,version_id,
    object_id,output_format,ordinal,checksum,render_manifest,lifecycle)
  VALUES('99000000-0000-0000-0000-000000000040',
    '99000000-0000-0000-0000-000000000030',
    '99000000-0000-0000-0000-000000000020',
    '99000000-0000-0000-0000-000000000021',
    '99000000-0000-0000-0000-000000000022','docx',1,'$empty_sha',
    '{\"parameters\":{\"customer_name\":{\"canonical_value\":\"Recovery Customer\"}}}',
    'issued');
  INSERT INTO approvals(approval_id,generated_file_id,stage,reviewer_subject_id,
    decision,checksum,attestation_hash,reason)
  VALUES('99000000-0000-0000-0000-000000000050',
    '99000000-0000-0000-0000-000000000040','approval',
    '99000000-0000-0000-0000-000000000001','approved','$empty_sha',
    '$empty_sha','Recovery proof');
  INSERT INTO document_issuances(issuance_id,generated_file_id,issue_number,
    issuer_subject_id,issued_checksum)
  VALUES('99000000-0000-0000-0000-000000000060',
    '99000000-0000-0000-0000-000000000040','RTR-2026-ABCDEF123456',
    '99000000-0000-0000-0000-000000000001','$empty_sha');
  COMMIT;" >/dev/null
docker run --rm --network "container:$minio_id" \
  --entrypoint /bin/sh quay.io/minio/mc:RELEASE.2025-04-16T18-13-26Z \
  -ec "mc alias set local http://127.0.0.1:9000 '$S3_ACCESS_KEY' '$S3_SECRET_KEY' >/dev/null
       printf '' | mc pipe 'local/$verify_bucket/tip009-recovery/template.docx' >/dev/null
       printf '' | mc pipe 'local/$verify_bucket/tip009-recovery/output.docx' >/dev/null
       mc mb --ignore-existing 'local/$restore_bucket' >/dev/null
       mc cp --recursive 'local/$verify_bucket/tip009-recovery/' \
         'local/$restore_bucket/tip009-recovery/' >/dev/null"
recovery_dump="$(mktemp)"
docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" \
  -d "$ac18_database" -Fc >"$recovery_dump"
docker compose exec -T postgres createdb -U "$POSTGRES_USER" "$restore_database"
docker compose exec -T postgres pg_restore -U "$POSTGRES_USER" \
  -d "$restore_database" --no-owner <"$recovery_dump"
rm -f "$recovery_dump"
restore_proof="$(docker compose exec -T postgres psql -X -At \
  -U "$POSTGRES_USER" -d "$restore_database" -c "SELECT
    (SELECT count(*) FROM templates)=1
    AND (SELECT count(*) FROM template_versions)=1
    AND (SELECT count(*) FROM template_bindings)=1
    AND (SELECT count(*) FROM render_jobs)=1
    AND (SELECT count(*) FROM document_publication_outbox)=1
    AND (SELECT count(*) FROM render_job_bindings)=1
    AND (SELECT count(*) FROM generated_files)=1
    AND (SELECT count(*) FROM approvals)=1
    AND (SELECT count(*) FROM document_issuances)=1
    AND NOT EXISTS (
      SELECT 1 FROM generated_files g
      JOIN render_jobs j USING(render_job_id)
      JOIN document_versions v USING(version_id)
      JOIN object_blobs o ON o.object_id=g.object_id
      JOIN document_publication_outbox p USING(render_job_id)
      JOIN approvals a USING(generated_file_id)
      JOIN document_issuances i USING(generated_file_id)
      WHERE g.checksum<>v.sha256 OR g.checksum<>o.sha256
        OR g.checksum<>a.checksum OR g.checksum<>i.issued_checksum
        OR p.state<>'finalized' OR p.finalized_at IS NULL)
    AND NOT EXISTS (
      SELECT 1 FROM unnest(ARRAY['templates','template_versions',
        'template_bindings','render_jobs','document_publication_outbox',
        'render_job_bindings','generated_files','approvals','document_issuances']) t
      WHERE has_table_privilege('$POSTGRES_RUNTIME_USER',t,'DELETE'))")"
[[ "$restore_proof" == "t" ]]
restored_objects="$(docker run --rm --network "container:$minio_id" \
  --entrypoint /bin/sh quay.io/minio/mc:RELEASE.2025-04-16T18-13-26Z \
  -ec "mc alias set local http://127.0.0.1:9000 '$S3_ACCESS_KEY' '$S3_SECRET_KEY' >/dev/null
       mc ls --recursive 'local/$restore_bucket/tip009-recovery/' | wc -l" \
  | tr -d '[:space:]')"
[[ "$restored_objects" == "2" ]]

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
  "DELETE FROM file_chunks" \
  "UPDATE file_chunks SET normalized_text='tamper'" \
  "DELETE FROM answer_citations" \
  "UPDATE answer_citations SET marker='C999'" \
  "DELETE FROM messages" \
  "UPDATE messages SET sanitized_content='tamper'" \
  "DELETE FROM enterprise_domains" \
  "DELETE FROM enterprise_corpus_manifests" \
  "DELETE FROM enterprise_ontology_revisions" \
  "DELETE FROM enterprise_evaluation_suites" \
  "DELETE FROM enterprise_evaluation_runs" \
  "UPDATE enterprise_evaluation_runs SET passed_count=0" \
  "DELETE FROM enterprise_release_attestations"
do
  if ! runtime_sql "$statement"; then
    denied=$((denied + 1))
  fi
done
[[ "$denied" -eq 27 ]]
echo "DATA INTEGRATION PASS · migrations=12 · revision_fixtures=12 · failing_ddl_rollback=1 · tests=61 · document_os_runtime_probes=2 · formats=14 · required_outputs=31 · private_engine_proofs=4 · policy_scenarios=48 · tip009_nonempty_restore=1 · runtime_denials=27"
