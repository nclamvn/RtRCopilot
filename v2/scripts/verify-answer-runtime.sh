#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

env_file="${ANSWER_ENV_FILE:-.env.demo}"
compose_project="${ANSWER_COMPOSE_PROJECT_NAME:-}"
if [[ ! -f "$env_file" ]]; then
  echo "ANSWER RUNTIME FAIL · env file not found: $env_file" >&2
  exit 2
fi

read_env() {
  local key="$1"
  awk -F= -v key="$key" '$1 == key {value=substr($0, index($0, "=") + 1)} END {print value}' \
    "$env_file"
}

desired_provider="$(read_env RAG_PROVIDER_MODE)"
desired_allowlist="$(read_env RAG_EXTERNAL_CLASSIFICATION_ALLOWLIST)"
desired_policy="$(read_env RAG_EXTERNAL_ENDPOINT_POLICY)"
desired_source="$(read_env RAG_EXTERNAL_CREDENTIAL_SOURCE)"
desired_embedding_provider="$(read_env RAG_EMBEDDING_PROVIDER)"
desired_embedding_provider="${desired_embedding_provider:-offline}"
desired_embedding_dimension="$(read_env RAG_EMBEDDING_DIMENSION)"
desired_embedding_dimension="${desired_embedding_dimension:-1536}"
desired_embedding_model="$(read_env RAG_EMBEDDING_OPENAI_MODEL)"
desired_embedding_model="${desired_embedding_model:-text-embedding-3-small}"
desired_review_mode="$(read_env RAG_REVIEW_MODE)"
desired_review_mode="${desired_review_mode:-on_demand}"
desired_routine_reasoning="$(read_env RAG_ANSWER_ROUTINE_REASONING_EFFORT)"
desired_routine_reasoning="${desired_routine_reasoning:-low}"
desired_metadata_page_size="$(read_env RAG_METADATA_PAGE_SIZE)"
desired_metadata_page_size="${desired_metadata_page_size:-1000}"
desired_openai="$(read_env OPENAI_API_KEY)"
desired_anthropic="$(read_env ANTHROPIC_API_KEY)"
# The Makefile exports the checkout SHA and therefore intentionally overrides
# a stale value in an operator env file. Direct script callers get the same
# immutable default instead of silently publishing `development`.
desired_build_sha="${RTR_BUILD_SHA:-$(./scripts/build-identity.sh)}"

compose=(docker compose)
if [[ -n "$compose_project" ]]; then
  compose+=(-p "$compose_project")
fi
compose+=(--env-file "$env_file")

api_id="$("${compose[@]}" ps -q api)"
if [[ -z "$api_id" ]]; then
  echo "ANSWER RUNTIME FAIL · api container is not running" >&2
  exit 1
fi

container_env() {
  local key="$1"
  "${compose[@]}" exec -T api printenv "$key" 2>/dev/null || true
}

actual_provider="$(container_env RAG_PROVIDER_MODE)"
actual_allowlist="$(container_env RAG_EXTERNAL_CLASSIFICATION_ALLOWLIST)"
actual_policy="$(container_env RAG_EXTERNAL_ENDPOINT_POLICY)"
actual_source="$(container_env RAG_EXTERNAL_CREDENTIAL_SOURCE)"
actual_embedding_provider="$(container_env RAG_EMBEDDING_PROVIDER)"
actual_embedding_dimension="$(container_env RAG_EMBEDDING_DIMENSION)"
actual_embedding_model="$(container_env RAG_EMBEDDING_OPENAI_MODEL)"
actual_review_mode="$(container_env RAG_REVIEW_MODE)"
actual_routine_reasoning="$(container_env RAG_ANSWER_ROUTINE_REASONING_EFFORT)"
actual_metadata_page_size="$(container_env RAG_METADATA_PAGE_SIZE)"
actual_build_sha="$(container_env RTR_BUILD_SHA)"

failures=()
compare_value() {
  local key="$1" desired="$2" actual="$3"
  if [[ "$desired" != "$actual" ]]; then
    failures+=("$key differs between $env_file and the api container")
  fi
}

compare_value RAG_PROVIDER_MODE "$desired_provider" "$actual_provider"
compare_value RAG_EXTERNAL_CLASSIFICATION_ALLOWLIST "$desired_allowlist" "$actual_allowlist"
compare_value RAG_EXTERNAL_ENDPOINT_POLICY "$desired_policy" "$actual_policy"
compare_value RAG_EXTERNAL_CREDENTIAL_SOURCE "$desired_source" "$actual_source"
compare_value RAG_EMBEDDING_PROVIDER "$desired_embedding_provider" "$actual_embedding_provider"
compare_value RAG_EMBEDDING_DIMENSION "$desired_embedding_dimension" "$actual_embedding_dimension"
compare_value RAG_EMBEDDING_OPENAI_MODEL "$desired_embedding_model" "$actual_embedding_model"
compare_value RAG_REVIEW_MODE "$desired_review_mode" "$actual_review_mode"
compare_value RAG_ANSWER_ROUTINE_REASONING_EFFORT \
  "$desired_routine_reasoning" "$actual_routine_reasoning"
compare_value RAG_METADATA_PAGE_SIZE "$desired_metadata_page_size" "$actual_metadata_page_size"
compare_value RTR_BUILD_SHA "$desired_build_sha" "$actual_build_sha"

desired_has_credential=false
actual_has_credential=false
[[ -n "$desired_openai" || -n "$desired_anthropic" ]] && desired_has_credential=true
if "${compose[@]}" exec -T api sh -lc \
  'test -n "${OPENAI_API_KEY:-}" || test -n "${ANTHROPIC_API_KEY:-}"'; then
  actual_has_credential=true
fi
if [[ "$desired_has_credential" != "$actual_has_credential" ]]; then
  failures+=("credential presence differs between $env_file and the api container")
fi

if [[ "$desired_provider" == "external" ]]; then
  [[ -n "$desired_allowlist" ]] || failures+=("external classification allowlist is empty")
  [[ -n "$desired_policy" ]] || failures+=("external endpoint policy is empty")
  [[ -n "$desired_source" ]] || failures+=("external credential source is empty")
  [[ "$desired_has_credential" == true ]] || failures+=("no external LLM credential is configured")
fi

# This command certifies the quality runtime, not the deterministic offline
# development fallback. Allow an explicit opt-out only for isolated tests.
if [[ "${ANSWER_REQUIRE_SEMANTIC_EMBEDDING:-true}" == "true" &&
      "$desired_embedding_provider" != "openai" ]]; then
  failures+=("quality runtime requires RAG_EMBEDDING_PROVIDER=openai")
fi
if [[ "$desired_embedding_provider" == "openai" && -z "$desired_openai" ]]; then
  failures+=("OpenAI embedding provider has no OpenAI credential")
fi

# The SOT index records its model and dimension. A numerically compatible
# vector is still invalid when produced by a different model, so compare both.
# file_chunks did not originally persist a model id; its dimensionality is
# checked here and model provenance is closed by TIP-031 P1 migration/tooling.
index_profiles="$("${compose[@]}" exec -T postgres sh -lc \
  'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At' <<'SQL'
SELECT DISTINCT sg.embedding_model || ':' || sg.embedding_dimension::text
FROM search_generations sg
JOIN active_search_generations ag ON ag.generation_id=sg.generation_id
WHERE sg.lifecycle='active'
ORDER BY 1;
SQL
)"
expected_index_profile="$desired_embedding_model:$desired_embedding_dimension"
if [[ "$index_profiles" != "$expected_index_profile" ]]; then
  failures+=("active SOT index profile is '$index_profiles', expected '$expected_index_profile'")
fi

file_dimensions="$("${compose[@]}" exec -T postgres sh -lc \
  'exec psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -At' <<'SQL'
SELECT DISTINCT vector_dims(embedding)::text
FROM file_chunks
WHERE lifecycle='active'
ORDER BY 1;
SQL
)"
if [[ -n "$file_dimensions" && "$file_dimensions" != "$desired_embedding_dimension" ]]; then
  failures+=("active file index dimensions are '$file_dimensions', expected '$desired_embedding_dimension'")
fi

if ((${#failures[@]} > 0)); then
  printf 'ANSWER RUNTIME FAIL · %s\n' "${failures[@]}" >&2
  echo "Run: make answer-runtime-refresh ANSWER_ENV_FILE=$env_file" >&2
  exit 1
fi

api_port="$(read_env API_PORT)"
api_port="${api_port:-8000}"
health=""
for _ in $(seq 1 30); do
  if health="$(curl -fsS "http://127.0.0.1:${api_port}/health/operational" 2>/dev/null)"; then
    break
  fi
  sleep 1
done
if ! printf '%s' "$health" | grep -q '"grounded_answering":"ready"'; then
  echo "ANSWER RUNTIME FAIL · grounded answering is not operational" >&2
  exit 1
fi
if ! printf '%s' "$health" | grep -Fq "\"build_sha\":\"$desired_build_sha\""; then
  echo "ANSWER RUNTIME FAIL · API build SHA is not the checkout SHA" >&2
  exit 1
fi

web_port="$(read_env WEB_PORT)"
web_port="${web_port:-3000}"
web_health=""
for _ in $(seq 1 30); do
  if web_health="$(curl -fsS "http://127.0.0.1:${web_port}/api/status" 2>/dev/null)"; then
    break
  fi
  sleep 1
done
if ! printf '%s' "$web_health" | grep -q '"ok":true'; then
  echo "ANSWER RUNTIME FAIL · browser-facing web/API build is not ready" >&2
  exit 1
fi
if ! printf '%s' "$web_health" | grep -Fq "\"build_sha\":\"$desired_build_sha\""; then
  echo "ANSWER RUNTIME FAIL · web build SHA is not the checkout SHA" >&2
  exit 1
fi

echo "ANSWER RUNTIME PASS · provider=$actual_provider · embedding=$actual_embedding_provider/$actual_embedding_dimension · routine_reasoning=$actual_routine_reasoning · build=$actual_build_sha · credential=$actual_has_credential · policy=loaded · grounded_answering=ready"
