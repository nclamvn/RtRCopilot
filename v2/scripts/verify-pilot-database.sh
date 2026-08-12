#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

pilot_project="${PILOT_PROJECT_NAME:-rtr-copilot-pilot}"
pilot_env="${PILOT_ENV_FILE:-.env.pilot}"
if [[ ! -f "$pilot_env" ]]; then
  echo "PILOT DATABASE FAIL · missing $pilot_env" >&2
  exit 2
fi

compose=(docker compose -p "$pilot_project" --env-file "$pilot_env")
postgres_id="$("${compose[@]}" ps -q postgres)"
if [[ -z "$postgres_id" ]]; then
  echo "PILOT DATABASE FAIL · isolated postgres is not running" >&2
  exit 1
fi

unexpected_sources="$("${compose[@]}" exec -T postgres sh -lc \
  'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At' <<'SQL'
SELECT string_agg(source_key, ',' ORDER BY source_key)
FROM (
  SELECT DISTINCT sg.source_key
  FROM search_generations sg
  JOIN active_search_generations ag ON ag.generation_id=sg.generation_id
  WHERE sg.lifecycle='active'
    AND sg.source_key NOT IN (
      'rtr.boms','rtr.capabilities','rtr.derived_costs',
      'rtr.l3_facts','rtr.prices','rtr.specs'
    )
) unexpected;
SQL
)"
if [[ -n "$unexpected_sources" ]]; then
  echo "PILOT DATABASE FAIL · non-canonical active SOT sources: $unexpected_sources" >&2
  exit 1
fi

schema_revision="$("${compose[@]}" exec -T postgres sh -lc \
  'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "SELECT version_num FROM alembic_version"')"
canonical_records="$("${compose[@]}" exec -T postgres sh -lc \
  'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At' <<'SQL'
SELECT count(*)
FROM records r
JOIN record_versions rv ON rv.version_id=r.current_version_id
JOIN sot_active_revisions ar ON ar.source_key=r.source_key
JOIN sot_packages p ON p.package_id=ar.package_id
  AND p.revision=ar.revision
WHERE r.lifecycle='active'
  AND rv.lifecycle='active'
  AND rv.package_id=ar.package_id
  AND r.source_key IN (
    'rtr.boms','rtr.capabilities','rtr.derived_costs',
    'rtr.l3_facts','rtr.prices','rtr.specs'
  );
SQL
)"
if [[ "$canonical_records" != "219" ]]; then
  echo "PILOT DATABASE FAIL · canonical SOT incomplete: $canonical_records/219" >&2
  exit 1
fi

canonical_chunks="$("${compose[@]}" exec -T postgres sh -lc \
  'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At' <<'SQL'
SELECT count(*)
FROM chunks c
JOIN active_search_generations ag ON ag.generation_id=c.generation_id
JOIN search_generations sg ON sg.generation_id=ag.generation_id
WHERE c.lifecycle='active'
  AND sg.lifecycle='active'
  AND c.source_key IN (
    'rtr.boms','rtr.capabilities','rtr.derived_costs',
    'rtr.l3_facts','rtr.prices','rtr.specs'
  );
SQL
)"
if [[ "$canonical_chunks" != "219" ]]; then
  echo "PILOT DATABASE FAIL · canonical index incomplete: $canonical_chunks/219" >&2
  exit 1
fi

# Certify the answer-quality runtime inside the same isolated Compose project;
# checking the default dev stack here would create a false pilot PASS.
ANSWER_ENV_FILE="$pilot_env" \
ANSWER_COMPOSE_PROJECT_NAME="$pilot_project" \
  ./scripts/verify-answer-runtime.sh

active_connectors="$("${compose[@]}" run --rm -T \
  -v "${RTR_ECOSYSTEM_ROOT:-$(cd ../../.. && pwd)}:/ecosystem:ro" api \
  python -m rtr_copilot.commands.snapshot_connector_readiness \
  --rtr-root /ecosystem | jq -r '.counts.active')"
if [[ "$active_connectors" != "0" ]]; then
  echo "PILOT DATABASE FAIL · unexpected active enterprise connectors: $active_connectors" >&2
  exit 1
fi

echo "PILOT DATABASE PASS · project=$pilot_project · schema=$schema_revision · canonical_records=$canonical_records · canonical_chunks=$canonical_chunks · unexpected_sources=0 · active_connectors=0 · answer_runtime=ready"
