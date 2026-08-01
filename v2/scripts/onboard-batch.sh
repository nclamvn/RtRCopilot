#!/usr/bin/env bash
# TIP-013 Phase A (D-013-03, AC-A2) — curator-gated batch onboarding.
#
# Thin wrapper over the additive backend command
# `rtr_copilot.commands.onboard_batch`. It drives a manifest of SYNTHETIC source
# items through the EXISTING gates only (SOT quarantine->stage->validate->publish,
# and the Refinery import->graduation gate) — never a new ingestion path, never a
# bypass.
#
# Discipline (enforced by the command, restated here for the operator):
#   * DRY-RUN BY DEFAULT. Without --apply the tool only validates and prints the
#     plan; nothing is written.
#   * CURATOR APPROVAL REQUIRED. --apply must be accompanied by --approve, and
#     each SOT package must carry an attestation signed by the manifest curator.
#   * TWO-PHASE, FAIL-CLOSED. Every item is validated before any activation; one
#     defective item rejects the whole batch with zero partial activation.
#   * IDEMPOTENT + AUDITED. Re-running is safe; every gate call is audited and the
#     batch ledger is emitted as JSON.
#
# Usage:
#   scripts/onboard-batch.sh --manifest path/to/manifest.json          # dry-run
#   scripts/onboard-batch.sh --manifest path/to/manifest.json \
#       --apply --approve --report /tmp/ledger.json                    # activate
#
# The database/redis/object-store targets come from the backend settings
# (environment / .env), exactly like every other backend command.
set -euo pipefail

project_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_root/apps/backend"

exec uv run python -m rtr_copilot.commands.onboard_batch "$@"
