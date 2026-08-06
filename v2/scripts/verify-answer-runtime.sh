#!/usr/bin/env bash
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root"

env_file="${ANSWER_ENV_FILE:-.env.demo}"
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
desired_openai="$(read_env OPENAI_API_KEY)"
desired_anthropic="$(read_env ANTHROPIC_API_KEY)"

api_id="$(docker compose --env-file "$env_file" ps -q api)"
if [[ -z "$api_id" ]]; then
  echo "ANSWER RUNTIME FAIL · api container is not running" >&2
  exit 1
fi

container_env() {
  local key="$1"
  docker compose --env-file "$env_file" exec -T api printenv "$key" 2>/dev/null || true
}

actual_provider="$(container_env RAG_PROVIDER_MODE)"
actual_allowlist="$(container_env RAG_EXTERNAL_CLASSIFICATION_ALLOWLIST)"
actual_policy="$(container_env RAG_EXTERNAL_ENDPOINT_POLICY)"
actual_source="$(container_env RAG_EXTERNAL_CREDENTIAL_SOURCE)"

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

desired_has_credential=false
actual_has_credential=false
[[ -n "$desired_openai" || -n "$desired_anthropic" ]] && desired_has_credential=true
if docker compose --env-file "$env_file" exec -T api sh -lc \
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

echo "ANSWER RUNTIME PASS · provider=$actual_provider · credential=$actual_has_credential · policy=loaded · grounded_answering=ready"
