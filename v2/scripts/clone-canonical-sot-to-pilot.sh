#!/usr/bin/env bash
# Clone ONLY the six certified TIP-013B canonical SOT revisions into the
# isolated pilot database. Existing vectors are deliberately excluded; the
# target must rebuild them with its own embedding profile after this script.
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

source_env="${SOURCE_ENV_FILE:-.env.demo}"
source_project="${SOURCE_COMPOSE_PROJECT_NAME:-rtr-copilot-v2}"
pilot_env="${PILOT_ENV_FILE:-.env.pilot}"
pilot_project="${PILOT_PROJECT_NAME:-rtr-copilot-pilot}"
expected_records=219

[[ -f "$source_env" ]] || { echo "CANONICAL CLONE FAIL · missing $source_env" >&2; exit 2; }
[[ -f "$pilot_env" ]] || { echo "CANONICAL CLONE FAIL · missing $pilot_env" >&2; exit 2; }

source_compose=(docker compose -p "$source_project" --env-file "$source_env")
pilot_compose=(docker compose -p "$pilot_project" --env-file "$pilot_env")

source_postgres="$("${source_compose[@]}" ps -q postgres)"
pilot_postgres="$("${pilot_compose[@]}" ps -q postgres)"
[[ -n "$source_postgres" ]] || { echo "CANONICAL CLONE FAIL · source postgres not running" >&2; exit 2; }
[[ -n "$pilot_postgres" ]] || { echo "CANONICAL CLONE FAIL · pilot postgres not running" >&2; exit 2; }
[[ "$source_postgres" != "$pilot_postgres" ]] || {
  echo "CANONICAL CLONE FAIL · source and pilot resolve to the same container" >&2
  exit 2
}

source_psql() {
  "${source_compose[@]}" exec -T postgres sh -lc \
    'exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh "$@"
}

pilot_psql() {
  "${pilot_compose[@]}" exec -T postgres sh -lc \
    'exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" "$@"' sh "$@"
}

canonical_filter="'rtr.boms','rtr.capabilities','rtr.derived_costs','rtr.l3_facts','rtr.prices','rtr.specs'"
count_sql="SELECT count(*) FROM records r JOIN record_versions rv ON rv.version_id=r.current_version_id JOIN sot_active_revisions ar ON ar.source_key=r.source_key WHERE r.lifecycle='active' AND rv.lifecycle='active' AND rv.package_id=ar.package_id AND r.source_key IN (${canonical_filter});"

source_count="$(source_psql -Atc "$count_sql")"
[[ "$source_count" == "$expected_records" ]] || {
  echo "CANONICAL CLONE FAIL · source set is $source_count/$expected_records" >&2
  exit 2
}

distribution="$(source_psql -Atc "SELECT string_agg(source_key||'='||n,',' ORDER BY source_key) FROM (SELECT r.source_key,count(*) n FROM records r JOIN record_versions rv ON rv.version_id=r.current_version_id JOIN sot_active_revisions ar ON ar.source_key=r.source_key WHERE r.lifecycle='active' AND rv.lifecycle='active' AND rv.package_id=ar.package_id AND r.source_key IN (${canonical_filter}) GROUP BY r.source_key) counts;")"
expected_distribution="rtr.boms=3,rtr.capabilities=76,rtr.derived_costs=1,rtr.l3_facts=116,rtr.prices=13,rtr.specs=10"
[[ "$distribution" == "$expected_distribution" ]] || {
  echo "CANONICAL CLONE FAIL · source distribution drift: $distribution" >&2
  exit 2
}

pilot_count="$(pilot_psql -Atc "$count_sql")"
if [[ "$pilot_count" == "$expected_records" ]]; then
  echo "CANONICAL CLONE PASS · pilot already contains the exact 219-record canonical set"
  exit 0
fi
[[ "$pilot_count" == "0" ]] || {
  echo "CANONICAL CLONE FAIL · pilot has a partial canonical set: $pilot_count/$expected_records" >&2
  exit 2
}

noncanonical="$(pilot_psql -Atc "SELECT count(*) FROM records WHERE lifecycle='active' AND source_key NOT IN (${canonical_filter});")"
[[ "$noncanonical" == "0" ]] || {
  echo "CANONICAL CLONE FAIL · pilot contains $noncanonical non-canonical active records" >&2
  exit 2
}

# An active worker consumes reindex outbox rows immediately. Stop it before the
# transaction so a local clone can never imply permission to export content to
# an external embedding provider. The purpose-bound index command restarts it
# only after its own approval + exact-count gate passes.
if [[ -n "$("${pilot_compose[@]}" ps -q worker)" ]]; then
  echo "==> Stopping pilot worker until the separate embedding approval gate passes…"
  "${pilot_compose[@]}" stop worker >/dev/null
fi

echo "==> Seeding deterministic migration principals in the isolated pilot…"
"${pilot_compose[@]}" run --rm -T \
  -v "$project_root/eval:/app/eval:ro" api \
  python /app/eval/demo/seed_curator.py >/dev/null

scratch="$(mktemp -d "${TMPDIR:-/tmp}/rtr-canonical-clone.XXXXXX")"
container_stage="/tmp/rtr-canonical-clone-$$"
cleanup() {
  rm -rf -- "$scratch"
  "${pilot_compose[@]}" exec -T postgres rm -rf -- "$container_stage" >/dev/null 2>&1 || true
}
trap cleanup EXIT

export_csv() {
  local name="$1"
  local query="$2"
  source_psql -qAtc "COPY (${query}) TO STDOUT WITH (FORMAT csv)" > "$scratch/$name.csv"
}

echo "==> Exporting only the six active canonical revisions (no chunks/vectors)…"
export_csv sot_packages "SELECT p.package_id,p.source_key,p.revision,p.schema_version,p.trust_zone,p.manifest_sha256,p.payload_sha256,p.producer,p.generated_at,p.ingested_at,p.staging_name,p.lifecycle,p.validation_summary,p.rejection_code,p.record_count,p.evidence_count,p.source_count FROM sot_packages p JOIN sot_active_revisions a ON a.package_id=p.package_id AND a.revision=p.revision WHERE a.source_key IN (${canonical_filter}) ORDER BY p.source_key"
export_csv resources "SELECT res.resource_id,res.resource_type,res.owner_subject_id,res.classification,res.source_zone,res.department_id,res.project_id,res.lifecycle_state,res.created_at,res.updated_at,res.deleted_at,res.retention_until,res.legal_hold FROM resources res JOIN records r ON r.record_id=res.resource_id WHERE r.source_key IN (${canonical_filter}) AND r.lifecycle='active' ORDER BY r.source_key,r.record_key"
export_csv records "SELECT r.record_id,r.record_key,r.source_key,r.owner_subject_id,r.classification,r.department_id,r.project_id,r.lifecycle,r.retention_until,r.legal_hold,r.created_at,r.updated_at FROM records r WHERE r.source_key IN (${canonical_filter}) AND r.lifecycle='active' ORDER BY r.source_key,r.record_key"
export_csv record_versions "SELECT rv.version_id,rv.record_id,rv.package_id,rv.package_revision,rv.version_ordinal,rv.owner_subject_id,rv.classification,rv.department_id,rv.project_id,rv.value_payload,rv.searchable_text,rv.provenance_level,rv.confidence,rv.verification_state,rv.fact_state,rv.effective_from,rv.effective_to,rv.freshness_policy,rv.freshness_due_at,rv.freshness_state,rv.evidence_refs,rv.source_refs,rv.acl_projection,rv.content_sha256,rv.supersedes_version_id,rv.lifecycle,rv.created_at FROM record_versions rv JOIN records r ON r.current_version_id=rv.version_id WHERE r.source_key IN (${canonical_filter}) AND r.lifecycle='active' ORDER BY r.source_key,r.record_key"
export_csv evidence_spans "SELECT e.span_id,e.evidence_key,e.record_version_id,e.package_id,e.source_ref,e.source_document_id,e.source_version_id,e.source_blob_sha256,e.locator,e.quoted_text,e.normalized_text,e.evidence_sha256,e.source_label,e.classification,e.lifecycle,e.created_at FROM evidence_spans e JOIN record_versions rv ON rv.version_id=e.record_version_id JOIN records r ON r.current_version_id=rv.version_id WHERE r.source_key IN (${canonical_filter}) AND r.lifecycle='active' ORDER BY r.source_key,e.evidence_key"
export_csv acl_entries "SELECT a.acl_id,a.resource_id,a.principal_type,a.principal_id,a.action,a.effect,a.conditions,a.valid_from,a.expires_at,a.granted_by,a.reason,a.created_at FROM acl_entries a JOIN records r ON r.record_id=a.resource_id WHERE r.source_key IN (${canonical_filter}) AND r.lifecycle='active' ORDER BY r.source_key,r.record_key,a.acl_id"
export_csv publish_runs "SELECT spr.run_id,spr.package_id,spr.source_key,spr.revision,spr.actor_user_id,spr.request_id,spr.state,spr.validation_report,spr.started_at,spr.finished_at,spr.candidate_checksum,spr.previous_active_revision,spr.previous_active_checksum,spr.record_count,spr.evidence_count,spr.deterministic_checksum,spr.failure_code,spr.failure_fingerprint,NULL::uuid AS audit_event_id FROM sot_publish_runs spr JOIN sot_active_revisions a ON a.activated_run_id=spr.run_id WHERE a.source_key IN (${canonical_filter}) ORDER BY spr.source_key"
export_csv active_revisions "SELECT a.source_key,a.package_id,a.revision,a.payload_sha256,a.activated_run_id,a.activated_at FROM sot_active_revisions a WHERE a.source_key IN (${canonical_filter}) ORDER BY a.source_key"
export_csv current_versions "SELECT r.record_id,r.current_version_id FROM records r WHERE r.source_key IN (${canonical_filter}) AND r.lifecycle='active' ORDER BY r.source_key,r.record_key"

docker cp "$scratch/." "$pilot_postgres:$container_stage"

echo "==> Importing the canonical snapshot in one transaction…"
"${pilot_compose[@]}" exec -T postgres sh -lc \
  'exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB"' <<SQL
BEGIN;
\copy sot_packages(package_id,source_key,revision,schema_version,trust_zone,manifest_sha256,payload_sha256,producer,generated_at,ingested_at,staging_name,lifecycle,validation_summary,rejection_code,record_count,evidence_count,source_count) FROM '$container_stage/sot_packages.csv' WITH (FORMAT csv)
\copy resources(resource_id,resource_type,owner_subject_id,classification,source_zone,department_id,project_id,lifecycle_state,created_at,updated_at,deleted_at,retention_until,legal_hold) FROM '$container_stage/resources.csv' WITH (FORMAT csv)
\copy records(record_id,record_key,source_key,owner_subject_id,classification,department_id,project_id,lifecycle,retention_until,legal_hold,created_at,updated_at) FROM '$container_stage/records.csv' WITH (FORMAT csv)
\copy record_versions(version_id,record_id,package_id,package_revision,version_ordinal,owner_subject_id,classification,department_id,project_id,value_payload,searchable_text,provenance_level,confidence,verification_state,fact_state,effective_from,effective_to,freshness_policy,freshness_due_at,freshness_state,evidence_refs,source_refs,acl_projection,content_sha256,supersedes_version_id,lifecycle,created_at) FROM '$container_stage/record_versions.csv' WITH (FORMAT csv)
\copy evidence_spans(span_id,evidence_key,record_version_id,package_id,source_ref,source_document_id,source_version_id,source_blob_sha256,locator,quoted_text,normalized_text,evidence_sha256,source_label,classification,lifecycle,created_at) FROM '$container_stage/evidence_spans.csv' WITH (FORMAT csv)
\copy acl_entries(acl_id,resource_id,principal_type,principal_id,action,effect,conditions,valid_from,expires_at,granted_by,reason,created_at) FROM '$container_stage/acl_entries.csv' WITH (FORMAT csv)
\copy sot_publish_runs(run_id,package_id,source_key,revision,actor_user_id,request_id,state,validation_report,started_at,finished_at,candidate_checksum,previous_active_revision,previous_active_checksum,record_count,evidence_count,deterministic_checksum,failure_code,failure_fingerprint,audit_event_id) FROM '$container_stage/publish_runs.csv' WITH (FORMAT csv)
\copy sot_active_revisions(source_key,package_id,revision,payload_sha256,activated_run_id,activated_at) FROM '$container_stage/active_revisions.csv' WITH (FORMAT csv)
CREATE TEMP TABLE canonical_current_versions(record_id uuid PRIMARY KEY,current_version_id uuid NOT NULL) ON COMMIT DROP;
\copy canonical_current_versions(record_id,current_version_id) FROM '$container_stage/current_versions.csv' WITH (FORMAT csv)
UPDATE records r SET current_version_id=c.current_version_id
FROM canonical_current_versions c WHERE c.record_id=r.record_id;
INSERT INTO sot_reindex_outbox(run_id,source_key,revision,payload)
SELECT a.activated_run_id,a.source_key,a.revision,
  jsonb_build_object('name','sot.reindex','run_id',a.activated_run_id::text,'source_key',a.source_key,'revision',a.revision)
FROM sot_active_revisions a
WHERE a.source_key IN (${canonical_filter})
ON CONFLICT(run_id) DO NOTHING;
COMMIT;
SQL

pilot_count="$(pilot_psql -Atc "$count_sql")"
pilot_distribution="$(pilot_psql -Atc "SELECT string_agg(source_key||'='||n,',' ORDER BY source_key) FROM (SELECT r.source_key,count(*) n FROM records r JOIN record_versions rv ON rv.version_id=r.current_version_id JOIN sot_active_revisions ar ON ar.source_key=r.source_key WHERE r.lifecycle='active' AND rv.lifecycle='active' AND rv.package_id=ar.package_id AND r.source_key IN (${canonical_filter}) GROUP BY r.source_key) counts;")"
[[ "$pilot_count" == "$expected_records" && "$pilot_distribution" == "$expected_distribution" ]] || {
  echo "CANONICAL CLONE FAIL · target reconciliation failed: count=$pilot_count distribution=$pilot_distribution" >&2
  exit 2
}

source_digest="$(source_psql -Atc "SELECT encode(digest(string_agg(r.record_key||':'||rv.content_sha256,',' ORDER BY r.source_key,r.record_key),'sha256'),'hex') FROM records r JOIN record_versions rv ON rv.version_id=r.current_version_id WHERE r.source_key IN (${canonical_filter}) AND r.lifecycle='active';")"
pilot_digest="$(pilot_psql -Atc "SELECT encode(digest(string_agg(r.record_key||':'||rv.content_sha256,',' ORDER BY r.source_key,r.record_key),'sha256'),'hex') FROM records r JOIN record_versions rv ON rv.version_id=r.current_version_id WHERE r.source_key IN (${canonical_filter}) AND r.lifecycle='active';")"
[[ "$source_digest" == "$pilot_digest" ]] || {
  echo "CANONICAL CLONE FAIL · record digest mismatch" >&2
  exit 2
}

echo "CANONICAL CLONE PASS · records=$pilot_count · sources=6 · digest=$pilot_digest · vectors_copied=0 · worker=stopped_pending_index_gate"
