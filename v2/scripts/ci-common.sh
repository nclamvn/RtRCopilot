# shellcheck shell=bash
# TIP-012 Task 4 — shared helpers for ci-local.sh, deploy.sh, rollback.sh.
#
# Sourced, never executed. Provides:
#   rtr_stage      — clear stage banners
#   rtr_die        — typed, fail-closed exit with a code
#   rtr_sandbox_prepare — layer the cloud-sandbox compose-build workaround
#                         (buildkit source policy + vosk mirror build-arg) so it
#                         is a no-op on a normal machine.
#
# The sandbox workaround is opt-in and parameterised:
#   RTR_SANDBOX_BUILD=1        convenience switch → fills the two vars below with
#                              this environment's documented defaults.
#   RTR_BUILD_SOURCE_POLICY    path to a buildkit source-policy JSON; when set and
#                              present it is exported as EXPERIMENTAL_BUILDKIT_SOURCE_POLICY.
#   RTR_VOSK_MODEL_URL         value passed as `--build-arg VOSK_MODEL_URL=...`.
#   RTR_MIRROR_PROBE_URL       optional URL asserted reachable before a sandbox build.
# On a normal machine none of these are set → builds run unmodified.

RTR_SANDBOX_MIRROR_DEFAULT_POLICY="/tmp/mirror/source-policy.json"
RTR_SANDBOX_MIRROR_DEFAULT_VOSK="http://172.17.0.1:8123/vosk.zip"
RTR_SANDBOX_MIRROR_DEFAULT_PROBE="http://172.17.0.1:8123/vosk.zip"

# Populated by rtr_sandbox_prepare. Callers must branch on the array length
# before expanding it: Bash 3.2 treats an empty-array expansion as an unbound
# variable under `set -u`.
RTR_COMPOSE_BUILD_ARGS=()

rtr_compose_build() {
  # rtr_compose_build <compose command...>
  # The command is expected to end immediately before its optional build args.
  if [[ ${#RTR_COMPOSE_BUILD_ARGS[@]} -gt 0 ]]; then
    "$@" "${RTR_COMPOSE_BUILD_ARGS[@]}"
  else
    "$@"
  fi
}

rtr_stage() {
  # rtr_stage "<label>" "<description>"
  printf '\n'
  printf '======================================================================\n'
  printf '== %s\n' "$1"
  if [[ -n "${2:-}" ]]; then
    printf '== %s\n' "$2"
  fi
  printf '======================================================================\n'
}

rtr_info() { printf '   • %s\n' "$*"; }

rtr_die() {
  # rtr_die <exit_code> <message...>
  local code="$1"
  shift
  printf 'FAIL(%s): %s\n' "$code" "$*" >&2
  exit "$code"
}

rtr_sandbox_prepare() {
  RTR_COMPOSE_BUILD_ARGS=()

  if [[ "${RTR_SANDBOX_BUILD:-0}" == "1" ]]; then
    : "${RTR_BUILD_SOURCE_POLICY:=$RTR_SANDBOX_MIRROR_DEFAULT_POLICY}"
    : "${RTR_VOSK_MODEL_URL:=$RTR_SANDBOX_MIRROR_DEFAULT_VOSK}"
    : "${RTR_MIRROR_PROBE_URL:=$RTR_SANDBOX_MIRROR_DEFAULT_PROBE}"
  fi

  if [[ -n "${RTR_BUILD_SOURCE_POLICY:-}" ]]; then
    if [[ ! -f "$RTR_BUILD_SOURCE_POLICY" ]]; then
      rtr_die 40 "RTR_BUILD_SOURCE_POLICY set but not found: $RTR_BUILD_SOURCE_POLICY"
    fi
    export EXPERIMENTAL_BUILDKIT_SOURCE_POLICY="$RTR_BUILD_SOURCE_POLICY"
    rtr_info "buildkit source policy: $EXPERIMENTAL_BUILDKIT_SOURCE_POLICY"
  fi

  if [[ -n "${RTR_VOSK_MODEL_URL:-}" ]]; then
    RTR_COMPOSE_BUILD_ARGS+=(--build-arg "VOSK_MODEL_URL=$RTR_VOSK_MODEL_URL")
    rtr_info "vosk model build-arg: $RTR_VOSK_MODEL_URL"
  fi

  if [[ -n "${RTR_MIRROR_PROBE_URL:-}" ]]; then
    if ! curl -fsS -o /dev/null --max-time 5 "$RTR_MIRROR_PROBE_URL"; then
      rtr_die 41 "sandbox mirror unreachable: $RTR_MIRROR_PROBE_URL (start: cd /tmp/mirror && python3 -m http.server 8123)"
    fi
    rtr_info "sandbox mirror reachable: $RTR_MIRROR_PROBE_URL"
  fi

  if [[ ${#RTR_COMPOSE_BUILD_ARGS[@]} -eq 0 ]]; then
    rtr_info "no sandbox build workaround active (normal build)"
  fi
}
