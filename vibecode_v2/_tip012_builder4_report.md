# TIP-012 · Builder 4 Report — CI/CD, migration gate, versioned deploy/rollback, image policy (AC-11, AC-12)

## STATUS

**DONE.** A GitHub Actions gate (`.github/workflows/verify.yml`) mirrors the
local gate stage-by-stage and is `actionlint`-clean. `scripts/ci-local.sh` runs
that identical sequence in this environment and was executed end-to-end — every
stage green (migration-gate, image-policy, backend, web, compose build, Trivy,
containerized data-integration, and the 73 mocked Playwright tests). A
DB-free static `scripts/migration-gate.sh` asserts single-head == config-pin and
is **proven-failing** on both a divergent head and a pin bump (scratch under
`/tmp`, repo untouched). `scripts/verify-image-policy.sh` passes after
digest-pinning the five remaining third-party compose images. `scripts/deploy.sh`
and `scripts/rollback.sh` were **drilled for real** against the hardened stack —
health gate green both times, version ledger correct, schema-not-downgraded
warning emitted. Existing `make verify`/`dev`/`migrate`/`backup`/`restore-drill`/
`hardened-*` recipes are untouched; only additive targets and (outside `v2`) the
`.github/` tree were written. Baseline stays green.

## FILES CHANGED

New:
- `.github/workflows/verify.yml` — CI gate. Pinned runner (`ubuntu-24.04`) +
  SHA-pinned actions. Jobs: `migration-gate`, `image-policy`, `backend`, `web`,
  `stack` (compose config+build → Trivy → data-integration, one runner for image
  locality), `browser` (mocked Playwright), and an `always()` `verify` aggregator
  that fails if any stage failed/was skipped — the single required status check.
- `v2/scripts/ci-common.sh` — sourced helper: stage banners, typed `rtr_die`, and
  the parameterised sandbox build workaround (`RTR_SANDBOX_BUILD=1` →
  `EXPERIMENTAL_BUILDKIT_SOURCE_POLICY` + `--build-arg VOSK_MODEL_URL=…`,
  no-op on a normal machine).
- `v2/scripts/ci-local.sh` — the exact CI sequence runnable here; fail-closed,
  clear stage banners, stage selection via `RTR_CI_STAGES` / `RTR_CI_SKIP_BROWSER`.
- `v2/scripts/migration-gate.sh` — pure-Python static gate (no DB, no alembic, no
  docker): parses `migrations/versions/*.py` revision/down_revision, computes
  heads, reads the `expected_schema_revision` pin from `config.py` via AST. Typed
  exits: 2 multiple/zero heads, 3 pin mismatch, 4 dangling revision, 5 bad inputs.
- `v2/scripts/deploy.sh` — versioned deploy: build → tag `:<version>` →
  migration-gate → migrate → rolling `up -d` (hardened) → health gate
  (wait-ready-hardened) → record. Version from `$1` / `$RTR_DEPLOY_VERSION` /
  `git rev-parse --short HEAD`. Idempotent, fail-closed.
- `v2/scripts/rollback.sh` — re-points `:latest` at a previously-tagged version →
  rolling `up -d` → health gate → record. Prints an explicit
  schema-NOT-auto-downgraded warning pointing at `docs/runbook.md#rollback`.
- `v2/scripts/verify-image-policy.sh` — script assertions: third-party compose
  images digest-pinned; hardened services (api/worker/ingress) declare
  `read_only`+`cap_drop:[ALL]`+`no-new-privileges`; app Dockerfiles run non-root.
  Typed exits 2/3/4.
- `v2/deploy/README.md` + runtime ledger (`current-version`, `previous-version`,
  `versions.log`) — the tracked deploy record (D-012-07).

Modified:
- `v2/compose.yaml` — digest-pinned the five remaining third-party images
  (pgvector, redis, minio, mc, clamav) using the RepoDigests of the images
  already in this environment; tag kept inline for readability
  (`name:tag@sha256:…`). Caddy was already pinned by Builder 1. No other change.
- `v2/Makefile` — additive `.PHONY` + targets `ci-local`, `migration-gate`,
  `image-policy`, `deploy`, `rollback`. No existing recipe touched.

## TEST RESULTS

### actionlint (container `rhysd/actionlint`)
```
docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint:latest .github/workflows/verify.yml
→ exit 0   (one real bug caught + fixed mid-build: expression string literal must be single-quoted)
```

### ci-local.sh — every stage executed green (run in segments to fit tool timeouts)
| Stage | Result |
|---|---|
| migration-gate | PASS · 9 revisions, single head `0009_governance_research` == pin |
| image-policy | PASS (see below) |
| (a) backend | ruff **clean** · mypy **98 files** · pytest **293 passed / 102 skipped** |
| (b) web | eslint+tsc **clean** · vitest **146 passed** · `next build` **OK** |
| (c) compose | `config --quiet` dev **OK** + hardened **OK** · `build` **OK** |
| (d) Trivy | **clean** (fail-closed `--exit-code 1`, HIGH/CRITICAL, ignore-unfixed) |
| (e) data-integration | **DATA INTEGRATION PASS** · 45 tests, migrations=9, 18 runtime denials |
| (f) mocked Playwright | **73 passed (3.1m)** against the running web server, page-level API mocks |

`CI-LOCAL VERIFY PASS` reported for each segment. Chromium was not preinstalled
here; `playwright install chromium` succeeded on demand.

### migration-gate — proven-failing (scratch `/tmp`, repo untouched)
Copied `versions/` + `config.py` to a `mktemp -d` scratch, pointed the gate at it
via `MIGRATION_GATE_VERSIONS_DIR` / `MIGRATION_GATE_CONFIG_FILE`:
```
baseline scratch                              → PASS  (exit 0)
+ 0009b_rogue_head off 0008 (divergent head)  → migration_multiple_heads … exit 2
pin bumped to 0010_not_yet_created            → migration_pin_mismatch    … exit 3
scratch removed; git status on versions/ + config.py = clean
```

### image-policy output
```
third-party images digest-pinned:
  pgvector/pgvector:pg16@sha256:a362508…   redis:7.2.5-alpine@sha256:6aaf3f5…
  quay.io/minio/minio:…@sha256:a1ea29f…   quay.io/minio/mc:…@sha256:aead63c…
  clamav/clamav-debian:1.4.5@sha256:50296b6…  caddy:2.11.4@sha256:844f60b…
hardened containment OK for: api, worker, ingress (read_only + cap_drop ALL + no-new-privileges)
app images non-root: backend.Dockerfile → USER app · web.Dockerfile → USER app
IMAGE POLICY PASS
```

### deploy + rollback drill (hardened stack, fake/dev config)
Ran with `RTR_SANDBOX_BUILD=1 MALWARE_SIGNATURE_MAX_AGE_SECONDS=1209600` (B1 env note):

| Action | Wall clock | Health gate (through ingress) | Ledger after |
|---|---|---|---|
| `deploy.sh drill-a` | **95 s** (cold build ~60 s) | READY https 200 + http→https 308, worker+ClamAV healthy — **3 s** | current=drill-a, previous=none |
| `deploy.sh drill-b` | **38 s** (cached build) | READY — **1 s** | current=drill-b, previous=drill-a |
| `rollback.sh` (→ previous=drill-a) | **34 s** | READY — **3 s** | current=drill-a, previous=drill-b |

Proof the rollback moved the running image (not a no-op):
```
after rollback:  rtr-copilot-v2-api:latest  == rtr-copilot-v2-api:drill-a  (sha256:5e8afee3…)
                 rtr-copilot-v2-api:drill-b  != :latest                     (sha256:341fd14a…)
```
`versions.log` (append-only): 2 deploy lines + 1 `rollback … schema=not_downgraded`
line. The schema-NOT-auto-downgraded warning box printed on rollback and points
to `docs/runbook.md#rollback`. Dev stack restored afterward (all 7 services
healthy) so the default gates work out of the box.

## ISSUES

- **Playwright browser not preinstalled** in this sandbox. `ci-local.sh` installs
  chromium on demand (succeeded through the proxy); the CI `browser` job uses
  `playwright install --with-deps chromium`. If a runner has no browser download,
  set `RTR_CI_SKIP_BROWSER=1` locally (CI has network).
- **ClamAV freshness** (B1's standing note): `database.clamav.net` is unreachable
  here, so the hardened health gate needs `MALWARE_SIGNATURE_MAX_AGE_SECONDS=1209600`.
  I did **not** bake this into deploy/rollback (it's a runtime, not a build,
  concern) — exported it for the drill. Contractor: export the same when driving
  the hardened stack in this sandbox.
- **Drill residue** (harmless, evidence): docker tags `rtr-copilot-v2-*:drill-a`
  / `:drill-b` and a drill `deploy/versions.log`. `git clean` the `deploy/` state
  files for a virgin ledger before re-running.
- Transient `curl: (35/56)` lines at the very start of the health-gate loop are
  just probes before the ingress finishes binding; the loop then reports `READY`.

## DEVIATIONS

1. **Digest-pinned 5 third-party compose images** (postgres/redis/minio/mc/clamav)
   — this is the *fix* for the image-policy gate, not just a report. Used the
   RepoDigests of the images already running here (byte-identical), keeping the
   human tag inline (`name:tag@sha256:…`). It is a compose change only — not app
   code, not a protected recipe. Both `docker compose config` profiles still
   validate and the dev stack came up healthy on the pinned digests.
2. **Migration gate is a pure-Python static analyzer**, not `alembic heads`
   against a DB. Rationale: the gate runs in CI, on the deploy host, and locally —
   a DB-free, tool-free (python3 only) check is maximally portable and
   deterministic. Cross-checked: `uv run alembic heads` reports the same single
   head `0009_governance_research`.
3. **Version model = retag `:latest`.** compose app services have only `build:`
   (no `image:`), so I tag each built image `:<version>` (rollback anchor) and let
   `:latest` be what compose runs; rollback re-points `:latest`. This needs **no**
   compose edit and is idempotent — chosen over adding `image: …:${TAG}` to the
   app services (a shared, more invasive change other builders' scripts assume).
4. **CI `stack` job groups build+Trivy+data-integration as sequential STEPS** in
   one runner because those stages share the compose-built images (which don't
   persist across GH jobs). This mirrors the back half of `verify-scaffold.sh`
   faithfully — each step is a visible stage. `browser` is a separate job (mocked;
   needs only the web build). `backend`/`web`/`migration-gate`/`image-policy`
   parallelise.
5. **Actions pinned to real commit SHAs** resolved via `git ls-remote` on
   2026-08-01: checkout `v6.1.0` (`d23441a…`), setup-node `v6.5.0` (`2499707…`),
   pnpm/action-setup `v6.0.9` (`0083308…`), astral-sh/setup-uv `v8.3.2`
   (`11f9893…`). The workflow cannot RUN here (no GitHub) but is statically valid.
6. **The workflow build step is a plain `docker compose build`** — the sandbox
   source-policy/vosk-mirror workaround lives only in `ci-local.sh` (a hosted
   runner has upstream internet). This satisfies "parameterise so it's a no-op on
   a normal machine".

## SUGGESTIONS (Builder 5 + Contractor)

**For the Contractor**
- **Branch protection must require the `verify` job** for the gate to block merges
  (the workflow can't self-enforce that).
- Refresh the action SHAs if your pinning policy wants newer tags; they were
  resolved live via `git ls-remote` and are current as of 2026-08-01.
- Rerun evidence: `RTR_SANDBOX_BUILD=1 make ci-local` (full), `make migration-gate`,
  `make image-policy`; drill with
  `RTR_SANDBOX_BUILD=1 MALWARE_SIGNATURE_MAX_AGE_SECONDS=1209600 make deploy` then
  `… make rollback`. `docker run --rm -v "$PWD:/repo" -w /repo rhysd/actionlint
  .github/workflows/verify.yml` for actionlint.
- **Two supply-chain items left for a follow-up (out of the stated image-policy
  scope = compose `image:` lines):** `quay.io/minio/mc` is referenced by tag
  literal (2×) inside `verify-data-integration.sh`, and `web.Dockerfile`'s base
  `node:22.14.0-alpine` is tag- not digest-pinned (backend's python already is).
  Neither is scanned by the gate; pin them if you want full coverage.

**For Builder 5 (load/SLO, recovery drills)**
- The **deploy/rollback wall-clock is captured here** (deploy cold **95 s** / warm
  **38 s**; rollback **34 s**; health gates **1–3 s** through the ingress) — this is
  the AC-12 rollback-drill row; you own RPO/RTO for the restore side. `versions.log`
  timestamps are UTC ISO-8601.
- To bring the hardened stack up for k6, use `make hardened-up` or `scripts/deploy.sh`;
  export `MALWARE_SIGNATURE_MAX_AGE_SECONDS=1209600` in this sandbox. The migration
  gate + image policy are orthogonal to your load run and won't interfere.
- `scripts/migration-gate.sh` is safe to call from any of your scripts (no DB, no
  side effects) if you want a schema-consistency assertion before a load baseline.
