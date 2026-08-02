# TIP-013B — Builder 6 Report · LOCAL activation + end-to-end Q&A proof + one-command runner

## STATUS
**DONE — all 7 tasks completed and verified in the cloud sandbox.** The curated
real-kernel batch (219 facts) was activated for REAL into a LOCAL dev database
through the actual curator-gated publish gate, RAG was reindexed, and the Copilot
answers real RtR questions with real citations + the soft-fact confidence caveat.
A one-command runner + README lets the Homeowner reproduce a reachable
`http://localhost:3000` on their own machine. Gates stay green; backend/web `src/`
untouched (additive only). This is a LOCAL/dev activation (dev-OIDC, a
locally-generated signing secret) — **NOT production**.

> The cloud sandbox's localhost is not reachable from the Homeowner's browser, so
> the primary browser deliverable is the runner `scripts/local-demo.sh`. The
> in-cloud proof (activation ledger + real Q&A JSON + web end-to-end) is captured
> as evidence below. No clickable cloud link is claimed.

## FILES CHANGED (additive only; no `src/` changes)
**Modified**
- `v2/eval/migrate/kernel_adapter.py` — `write_package()` / `emit_packages()` take
  an optional `signing_secret` (defaults to the existing dry-run `ADAPTER_SECRET`,
  so the 41 migrate-unit tests are unaffected). A real secret makes the emitted
  attestation verify at the `--apply` publish gate — the ONLY change vs a dry-run
  package.
- `v2/eval/migrate/run_migration.py` — added `--emit` / `--manifest-out` /
  `--signing-secret-env`. `--emit` reads the real `SOT_SIGNING_SECRET` from the
  env (fails loud if absent/<32 chars), signs the ready packages with it, and
  writes the `onboard_batch.BatchManifest`. Default (no `--emit`) is the unchanged
  DRY-RUN.

**New**
- `v2/eval/demo/seed_curator.py` — idempotent seed of the migration curator + owner
  subjects (FK for `records.owner_subject_id` / audit `actor_user_id`), mirroring
  the onboard integration test.
- `v2/eval/demo/run_reindex.py` — drains the SOT reindex outbox by calling the
  worker's own `ReindexService.process_next()` in a bounded loop.
- `v2/eval/demo/capture_qa.py` — drives the real dev-OIDC login and asks the real
  questions, dumping full responses to `/tmp/rtr-demo/qa_capture.json`.
- `v2/eval/demo/DEMO_QA_EVIDENCE.md` — the money-shot Q&A evidence (below).
- `v2/eval/demo/README_LOCAL_DEMO.md` — Homeowner-facing LOCAL demo guide.
- `v2/scripts/local-demo.sh` — the one-command Docker runner (idempotent).

## RESULTS

### Activation ledger (`/tmp/rtr-demo/ledger.json`)
- `status = onboarded`, `apply = true`, `approved = true`
- **`activated_count = 6` SOT revisions**, **0 rejected** (all items `state=active`,
  `idempotent=false` on first apply)
- Gate: real two-phase, fail-closed publish gate (quarantine→stage→validate→
  publish) with curator-signed attestations verified against the running api's
  `SOT_SIGNING_SECRET`.
- **219 active records / 219 active chunks** in `rtr_local_demo`:

| source_key | records | tier make-up |
|---|---|---|
| rtr.specs | 10 | 8 strict + 2 soft |
| rtr.capabilities | 76 | soft |
| rtr.prices | 13 | soft |
| rtr.l3_facts | 116 | 110 soft + 6 strategic |
| rtr.boms | 3 | soft (restricted / leader-only) |
| rtr.derived_costs | 1 | soft |
| **TOTAL** | **219** | **8 strict + 205 soft + 6 strategic** |

- Classification split: **216 internal + 3 restricted**. Governance spot-check: a
  `staff` session asking scoped to `rtr.boms` (leader-only) gets **honest-null / 0
  hits** — restricted facts are correctly invisible to staff.
- Reindex: 6 outbox rows drained → 219 active chunks (RAG sees every fact).

### REAL Q&A evidence (dev-OIDC `staff@rtrobotics.com`, role `staff`)
Full JSON: `/tmp/rtr-demo/qa_capture.json`; narrative: `v2/eval/demo/DEMO_QA_EVIDENCE.md`.

| # | Question | State | Answer (real) | Top citation | Caveat |
|---|---|---|---|---|---|
| 1 | "Maximum payload capacity" | grounded | **Maximum payload capacity: 15 kg** | `SPEC.HERA.PAYLOAD.MAX` (verified_primary / **strict**) | true* |
| 2 | "Payload đồng thời" (HERA signature 1-4-14) | grounded | **Payload đồng thời: 4 count** | `SPEC.HERA.SIGNATURE.PAYLOAD_SIMUL` (**soft**) | **true** |
| 3 | "HERA MTOW" | grounded | **HERA MTOW per Capability Matrix HC-001: 30.5 lb (+)** | `SPEC.HERA.MTOW.HC001` (**HC-001**, soft) | **true** |
| 4 | "VEGA giá bao nhiêu" | grounded | **VEGA US list price: 109 900 USD** | `PRICE.VEGA.MSRP.US` (**soft**) | **true** |
| 5 | "motors" | grounded | **4 motors** | `SPEC.HERA.MOTORS` (**strict** only) | **false** |
| 6 | "Ai là tổng giám đốc điều hành của công ty" | **honest_null** | refuses (no evidence) | — (gap routed) | false |
| 7 | "VEGA tải trọng tối đa" | **honest_null** | see note | — | false |

\*#1 cites strict `PAYLOAD.MAX` (dc=false) but a co-retrieved soft fact drives
`confidence_caveat=true`. Every citation carries `zone_label="sot"`,
`verification_state`, `freshness_state="current"`, and the per-record
`needs_double_check` flag. **Strict-only answers return `confidence_caveat=false`
(#5); any soft citation flips it to true — proven live.**

**#7 honesty note:** the VEGA payload fact **IS** activated — `POST /api/v1/search`
returns `L3R.1.010` ("VEGA … 44 lbs payload, MTOW 82.4 lbs…", approved_internal).
`/ask` returns honest-null only because the LOCAL `local` provider is the offline
extractive stub, which fail-closes on multi-sentence L3 prose (per-sentence
grounding guard) rather than emit a partly-cited answer. It is a provider
limitation, **not a data gap** (reported honestly, not faked).

### Web-serve status
**Serves.** Native `next start` on the prebuilt `.next` came up and the **full
browser path worked end-to-end on :3000 against the demo data**: dev-OIDC login
through `/api/auth/*` set the session, `/api/auth/me` → `staff@rtrobotics.com`, and
`POST /api/ask/ask` returned a grounded answer citing **HC-001** with
`confidence_caveat=true`. `/api/status` → 200, `/` → 307 (auth redirect). This is a
**cloud-side** proof only — that localhost is not reachable from the Homeowner's
browser; the runner reproduces it on their machine (compose `web` service runs the
standalone server, avoiding the `next start` standalone warning seen natively).

### Gates
- `ruff check` on all changed/new files → **All checks passed**
- `mypy` on the 4 changed/new Python modules → **Success: no issues**
- `pytest tests/test_tip013_migrate_unit.py tests/test_tip013_onboard_unit.py` →
  **48 passed** (signing-secret change did not regress). No `src/` files touched, so
  the backend one-DB suite is unaffected.

## ISSUES
- The offline `local` RAG provider cannot verbatim-answer multi-sentence L3
  narrative facts (grounding guard fail-closes) — short spec/price facts answer
  cleanly; long prose needs `RAG_PROVIDER_MODE=external`. (#7 above.)
- `next start` warns it "does not work with output: standalone" yet still served
  here; the compose `web` service uses `node .next/standalone/server.js`, which is
  the correct standalone entry.
- The cloud-sandbox localhost is unreachable from the Homeowner's browser (expected
  per the task framing) — hence the runner is the browser deliverable.

## DEVIATIONS
- **Retrieval phrasing.** SOT spec chunks store the value phrase
  ("Maximum payload capacity: 15 kg"); the product name lives in the record key,
  not the chunk body. The demo scopes questions with the existing
  `filters.source_key` (a normal public-API use) so retrieval focuses on the right
  package. Retrieval/ranking/DLP/grounding code is unchanged.
- **Source fingerprint.** The adapter fingerprints the kernel's *recorded* source
  identity, not the real source blob (the source tree isn't in the snapshot), and
  deliberately leaves `evidence.source_blob_sha256` unset so the validator never
  compares an invented hash. A production `--apply` must recompute this from the
  real blob. (Pre-existing adapter behavior, carried into `--emit`.)
- **Curator identity.** Activation used the deterministic migration curator
  (`kernel_adapter.CURATOR_ID`) seeded as a subject; production binds a real
  authenticated curator.

## SUGGESTIONS

### Exact commands the Homeowner runs on THEIR machine (reachable localhost:3000)
```bash
cd v2
scripts/local-demo.sh --kernel-root /path/to/kernel-real
# ... builds + starts infra, migrates, generates a local SOT_SIGNING_SECRET,
#     emits+activates the 219 curated facts through the real gate, reindexes,
#     starts api+web, and prints:  http://localhost:3000
# Login: click "Sign in" -> dev-OIDC logs in as staff@rtrobotics.com (no password).
# Try:  "Maximum payload capacity" · "HERA MTOW" · "VEGA giá bao nhiêu"
scripts/local-demo.sh --down     # tear down (keeps the stable secret)
```
The runner is idempotent (re-uses the generated secret; `--apply` never
double-activates; reindex is a no-op once drained). A proven **native** fallback
(the exact sequence verified in-cloud) is documented in
`v2/eval/demo/README_LOCAL_DEMO.md`.

### What remains for a PRODUCTION activation (vs this LOCAL demo)
1. **Identity/config:** real corporate OIDC (issuer/client), `APP_ENV=production`,
   `DEV_OIDC_ENABLED=false`, HTTPS `PUBLIC_BASE_URL` — config refuses to boot
   otherwise.
2. **Signing:** a dedicated, secret-managed `SOT_SIGNING_SECRET` (≥32 bytes),
   distinct from S3/OIDC secrets.
3. **Real curators** bound to authenticated sessions sign the attestations (not the
   deterministic migration curator).
4. **Real source fingerprints** recomputed from source blobs at `--apply`; a
   composing LLM provider (`RAG_PROVIDER_MODE=external`) if verbatim multi-sentence
   answers are required.
5. **Curate the remaining 39** needs-curation + claim facts through the curator
   queue before activating them (only the 219 ready set is activated here).
