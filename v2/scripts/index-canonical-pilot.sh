#!/usr/bin/env bash
# Build a fresh embedding index for the isolated 219-record canonical pilot.
# External processing is purpose-bound and requires an explicit environment gate.
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

pilot_env="${PILOT_ENV_FILE:-.env.pilot}"
pilot_project="${PILOT_PROJECT_NAME:-rtr-copilot-pilot}"
[[ -f "$pilot_env" ]] || { echo "PILOT INDEX FAIL · missing $pilot_env" >&2; exit 2; }

provider="$(awk -F= '$1 == "RAG_EMBEDDING_PROVIDER" {value=substr($0,index($0,"=")+1)} END {print value}' "$pilot_env")"
provider="${provider:-offline}"
if [[ "$provider" == "openai" && "${PILOT_APPROVE_EXTERNAL_CORPUS:-0}" != "1" ]]; then
  echo "PILOT INDEX BLOCKED · OpenAI embedding export requires purpose-bound approval" >&2
  exit 2
fi

compose=(docker compose -p "$pilot_project" --env-file "$pilot_env")
postgres_id="$("${compose[@]}" ps -q postgres)"
[[ -n "$postgres_id" ]] || { echo "PILOT INDEX FAIL · postgres is not running" >&2; exit 2; }

psql_value() {
  "${compose[@]}" exec -T postgres sh -lc \
    'exec psql -v ON_ERROR_STOP=1 -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Atc "$1"' sh "$1"
}

canonical_filter="'rtr.boms','rtr.capabilities','rtr.derived_costs','rtr.l3_facts','rtr.prices','rtr.specs'"
record_count="$(psql_value "SELECT count(*) FROM records r JOIN record_versions rv ON rv.version_id=r.current_version_id JOIN sot_active_revisions ar ON ar.source_key=r.source_key WHERE r.lifecycle='active' AND rv.lifecycle='active' AND rv.package_id=ar.package_id AND r.source_key IN (${canonical_filter});")"
noncanonical="$(psql_value "SELECT count(*) FROM records WHERE lifecycle='active' AND source_key NOT IN (${canonical_filter});")"
source_count="$(psql_value "SELECT count(*) FROM sot_active_revisions WHERE source_key IN (${canonical_filter});")"
pending_count="$(psql_value "SELECT count(*) FROM sot_reindex_outbox WHERE status IN ('pending','dispatching') AND source_key IN (${canonical_filter});")"
active_chunks="$(psql_value "SELECT count(*) FROM chunks c JOIN active_search_generations ag ON ag.generation_id=c.generation_id JOIN search_generations sg ON sg.generation_id=ag.generation_id WHERE c.lifecycle='active' AND sg.lifecycle='active' AND c.source_key IN (${canonical_filter});")"

[[ "$record_count" == "219" && "$source_count" == "6" && "$noncanonical" == "0" ]] || {
  echo "PILOT INDEX FAIL · preflight records=$record_count sources=$source_count noncanonical=$noncanonical" >&2
  exit 2
}
if [[ "$pending_count" == "0" && "$active_chunks" == "219" ]]; then
  profiles="$(psql_value "SELECT string_agg(DISTINCT sg.embedding_model||'/'||sg.embedding_dimension::text,',' ORDER BY sg.embedding_model||'/'||sg.embedding_dimension::text) FROM active_search_generations ag JOIN search_generations sg ON sg.generation_id=ag.generation_id WHERE sg.source_key IN (${canonical_filter});")"
  unexpected="$(psql_value "SELECT count(*) FROM active_search_generations ag JOIN search_generations sg ON sg.generation_id=ag.generation_id WHERE sg.source_key NOT IN (${canonical_filter});")"
  [[ "$unexpected" == "0" ]] || {
    echo "PILOT INDEX FAIL · existing index has $unexpected unexpected generations" >&2
    exit 2
  }
  "${compose[@]}" up -d worker >/dev/null
  echo "PILOT INDEX PASS · already complete · chunks=219 · sources=6 · profile=$profiles · unexpected_generations=0"
  exit 0
fi
[[ "$pending_count" == "6" && "$active_chunks" == "0" ]] || {
  echo "PILOT INDEX FAIL · expected six canonical outbox rows, found $pending_count" >&2
  exit 2
}

echo "PILOT INDEX APPROVED · provider=$provider · records=219 · sources=6 · existing_vectors_copied=0"
"${compose[@]}" run --rm -T api python -m rtr_copilot.commands.reembed_corpus

chunk_count="$(psql_value "SELECT count(*) FROM chunks c JOIN active_search_generations ag ON ag.generation_id=c.generation_id JOIN search_generations sg ON sg.generation_id=ag.generation_id WHERE c.lifecycle='active' AND sg.lifecycle='active' AND c.source_key IN (${canonical_filter});")"
unexpected="$(psql_value "SELECT count(*) FROM active_search_generations ag JOIN search_generations sg ON sg.generation_id=ag.generation_id WHERE sg.source_key NOT IN (${canonical_filter});")"
profiles="$(psql_value "SELECT string_agg(DISTINCT sg.embedding_model||'/'||sg.embedding_dimension::text,',' ORDER BY sg.embedding_model||'/'||sg.embedding_dimension::text) FROM active_search_generations ag JOIN search_generations sg ON sg.generation_id=ag.generation_id WHERE sg.source_key IN (${canonical_filter});")"

[[ "$chunk_count" == "219" && "$unexpected" == "0" ]] || {
  echo "PILOT INDEX FAIL · postflight chunks=$chunk_count unexpected_generations=$unexpected" >&2
  exit 2
}

"${compose[@]}" up -d worker >/dev/null
echo "PILOT INDEX PASS · chunks=$chunk_count · sources=6 · profile=$profiles · unexpected_generations=0"
