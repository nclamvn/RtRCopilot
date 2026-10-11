#!/usr/bin/env bash
# R-only bindings around ORIGINAL unchanged gate scripts. Unique IDs only.
set -euo pipefail
r_dir=$(cd "$(dirname "$0")" && pwd)
experiment_dir=$(cd "$r_dir/.." && pwd)
run_id=${TIP054_FULL_RUN_ID:?explicit R fixture required}
kind=${1:?full migration native restoration live latency nonleaf required}
gate_id=${2:?new unique gate id required}
[[ "$gate_id" =~ ^[a-z0-9_]{1,24}$ ]] || exit 2
export TIP054_FULL_RUN_ID="$run_id"
TIP054_REAL_DOCKER=$(command -v docker)
export TIP054_REAL_DOCKER
[[ "$TIP054_REAL_DOCKER" == /* && -x "$TIP054_REAL_DOCKER" ]] || exit 2
case "$kind" in
  full) child=(bash "$experiment_dir/run-full-gates.sh"); export TIP054_GATE_ID="$gate_id" ;;
  migration) child=(bash "$experiment_dir/run-migration-gate.sh"); export TIP054_MIGRATION_ID="$gate_id" ;;
  native) child=(bash "$experiment_dir/run-native-gates.sh"); export TIP054_NATIVE_ID="$gate_id" ;;
  restoration) [[ ${#gate_id} -le 22 ]] || exit 2; child=(bash "$experiment_dir/run-restoration-campaign.sh"); export TIP054_RESTORE_ID="$gate_id" TIP054_NATIVE_ID="p_$gate_id" ;;
  live) child=(bash "$experiment_dir/run-live-owner-gate.sh"); export TIP054_LIVE_OWNER_ID="$gate_id" ;;
  latency) child=(bash "$r_dir/run-baseline.sh"); export TIP054_R_GATE_ID="$gate_id"; : "${TIP054_R_OBSERVER:?explicit off or on}" ;;
  nonleaf) child=(bash "$r_dir/run-nonleaf-proof.sh"); export TIP054_GATE_ID="$gate_id" ;;
  *) exit 2 ;;
esac
# The shim checks capacity BEFORE each actual owned CREATE DATABASE, then
# forwards every original Docker argument/result verbatim to the genuine CLI.
export TIP054_CAPACITY_TRACE="$experiment_dir/raw/$run_id/r_bind_$gate_id/capacity-create.jsonl"
export PATH="$r_dir/bin:$PATH"
bash "$r_dir/gate-boundary.sh" "$gate_id" begin
set +e
"${child[@]}"
child_code=$?
set -e
set +e
bash "$r_dir/gate-boundary.sh" "$gate_id" end "$child_code"
binding_code=$?
set -e
if [[ "$binding_code" != 0 ]]; then exit "$binding_code"; fi
exit "$child_code"
