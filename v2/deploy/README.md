# Deploy ledger (TIP-012 Task 4, D-012-07)

Version state written by `scripts/deploy.sh` and `scripts/rollback.sh`. This is
the authoritative record of what version the hardened stack is running.

## Files

| File | Meaning |
|---|---|
| `current-version` | the version tag the stack is currently running (`:latest` points here) |
| `previous-version` | the last distinct version — the default rollback target |
| `versions.log` | append-only audit ledger; one tab-separated line per deploy/rollback |

## Image-tag model

`docker compose` builds `rtr-copilot-v2-<svc>:latest`. A deploy tags those built
images `rtr-copilot-v2-<svc>:<version>` (the rollback anchor) and runs `:latest`.
`rollback.sh` re-points `:latest` at a previously tagged version and recreates
the app services. No compose edit is needed; both scripts are idempotent and
fail-closed.

## Schema posture

Rollback NEVER auto-downgrades the database schema (D-012-07). A forward
migration applied by a newer version stays applied; rolling code back only moves
the image pointers. A schema downgrade is a separate Homeowner decision — see
`docs/runbook.md#rollback`.

## Note

The values checked in here may be from a drill (e.g. `drill-a` / `drill-b`).
Real deploys overwrite them; `versions.log` keeps the full history.
