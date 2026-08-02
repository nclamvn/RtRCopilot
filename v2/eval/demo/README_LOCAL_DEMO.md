# RtR Copilot v2 — LOCAL demo (TIP-013B)

Run the whole thing on **your own machine** and get a real, clickable
`http://localhost:3000` with **219 real kernel facts** live and answerable — with
citations and the soft-fact confidence caveat.

> **This is LOCAL/dev, not production.** Identity is dev-OIDC (a password-less
> click-through login as `staff@rtrobotics.com`), signing uses a random
> `SOT_SIGNING_SECRET` generated on first run, and the database is a throwaway
> compose volume. No production credentials are created and no production
> readiness is claimed. See "Going to production" at the bottom.

---

## Prerequisites

- **Docker + Docker Compose v2** — check with `docker compose version`
- This repo checked out
- The **read-only kernel snapshot** (the directory containing
  `registry/specs.yaml`, `registry/l3_facts.yaml`, …). Point `--kernel-root` at it.

## One command

```bash
cd v2
scripts/local-demo.sh --kernel-root /path/to/kernel-real
```

That single command:

1. builds the images and starts **postgres + redis + minio** (and the bucket);
2. **migrates** the database to head (`alembic upgrade head`);
3. **emits** the curated batch as SOT packages **signed with your local
   `SOT_SIGNING_SECRET`** (219 ready: 8 strict + 205 soft + 6 strategic; the
   facts held/gap/claim/excluded are deliberately NOT emitted);
4. **seeds** the curator/owner subjects and **activates** the batch through the
   REAL curator-gated publish gate (`onboard-batch.sh --apply --approve`);
5. **reindexes** so RAG can answer;
6. starts **api + worker + web** and prints `http://localhost:3000`.

It is **idempotent**: the generated secret is reused, `--apply` never
double-activates, and reindex is a no-op once drained.

Tear down (removes the demo database volume, keeps the secret):

```bash
scripts/local-demo.sh --down
```

## Logging in (dev-OIDC)

Open `http://localhost:3000`, click **Sign in**. Dev-OIDC logs you straight in as
`staff@rtrobotics.com` (role `staff`) with **no password** — it is a local
developer identity, not a corporate account. `staff` clearance sees the
`internal` facts (HERA/VEGA specs, prices, capabilities, L3 facts). The 3
leader-only (`restricted`) BOM facts are correctly hidden from `staff`.

## Ask these (real grounded answers)

In the Copilot ask box (or `POST /api/v1/ask`):

| Ask | You get | Caveat? |
|---|---|---|
| `Maximum payload capacity` | HERA max payload **15 kg** (`SPEC.HERA.PAYLOAD.MAX`, strict) | yes (soft co-cite) |
| `HERA MTOW` | `SPEC.HERA.MTOW.HC001` → **HC-001** (soft) | **yes** |
| `Payload đồng thời` | HERA signature — 4 bays (`SPEC.HERA.SIGNATURE.PAYLOAD_SIMUL`, soft) | **yes** |
| `VEGA giá bao nhiêu` | VEGA US list price **109,900 USD** (`PRICE.VEGA.MSRP.US`, soft) | **yes** |
| `motors` | HERA **4 motors** (`SPEC.HERA.MOTORS`, strict only) | **no** |
| `Ai là tổng giám đốc điều hành của công ty` | honest-null (no evidence → refuses) | — |

`confidence_caveat = true` whenever any cited fact is **soft** (verified
provenance but no formal evidence span); strict-only answers stay
`confidence_caveat = false`. Full captured evidence: `DEMO_QA_EVIDENCE.md`.

> Tip: SOT spec chunks store the value phrase ("Maximum payload capacity: 15 kg"),
> so the product name lives in the record key, not the chunk body. Scope a query
> with the existing filter, e.g.
> `{"question":"HERA payload","filters":{"source_key":"rtr.specs"}}`, to focus
> retrieval on the right package. The offline `local` answer provider grounds
> short single-phrase facts cleanly; long multi-sentence L3 narrative facts need
> `RAG_PROVIDER_MODE=external` (a composing LLM) to be answered verbatim — they
> are still activated and retrievable via `POST /api/v1/search`.

---

## What the runner does under the hood (and how it was verified)

The exact activation sequence below was **run and verified natively in the
cloud sandbox** (native Postgres :5432, Redis :6380, MinIO :9002/bucket
`rtr-test`). `local-demo.sh` wraps the same steps in Docker Compose so they run
unchanged on your machine. If you prefer to run them by hand against your own
infra (with the backend `uv` env and env vars pointing at your Postgres/Redis/
MinIO):

```bash
cd v2/apps/backend
export SOT_SIGNING_SECRET="$(python -c 'import secrets;print(secrets.token_hex(32))')"
export SOT_STAGING_ROOT=/tmp/rtr-demo/sot-staging
# ... plus POSTGRES_DSN / MIGRATION_DSN / REDIS_URL / S3_* for your infra ...

uv run alembic upgrade head

# emit the curated batch as REAL-signed packages + the onboarding manifest
uv run python ../../eval/migrate/run_migration.py \
  --curated --emit \
  --kernel-root /path/to/kernel-real/registry \
  --out "$SOT_STAGING_ROOT" \
  --manifest-out /tmp/rtr-demo/manifest.json

# seed the curator/owner subjects (FK for records.owner / audit.actor)
uv run python ../../eval/demo/seed_curator.py

# activate through the REAL gate (two-phase, fail-closed, idempotent)
(cd ../.. && bash scripts/onboard-batch.sh \
  --manifest /tmp/rtr-demo/manifest.json --apply --approve \
  --report /tmp/rtr-demo/ledger.json)

# make RAG see them
uv run python ../../eval/demo/run_reindex.py

# start the API and prove Q&A
uv run uvicorn rtr_copilot.api.main:app --host 127.0.0.1 --port 8000 &
uv run python ../../eval/demo/capture_qa.py     # writes /tmp/rtr-demo/qa_capture.json
```

Verified result: ledger `status = onboarded`, `activated_count = 6` SOT
revisions, **0 rejected**, **219 active records / 219 active chunks**.

## Going to production (what this LOCAL demo is NOT)

This demo is deliberately dev-only. A production activation additionally needs:

- **Real identity**: a corporate OIDC issuer/client (`DEV_OIDC_ENABLED=false`,
  `APP_ENV=production`, HTTPS `PUBLIC_BASE_URL`) — the config refuses to boot
  in production while dev-OIDC is on or a known-default secret is present.
- **A dedicated, secret-managed `SOT_SIGNING_SECRET`** (≥32 bytes) held in a
  real secret store, distinct from the S3/OIDC secrets.
- **Real curator identities** bound to authenticated sessions (not the
  deterministic migration curator seeded here) signing the attestations.
- **Recomputed source fingerprints** from the real source blobs at `--apply`
  (this demo fingerprints the kernel's recorded source identity — see the
  adapter deviation note), and a composing LLM provider
  (`RAG_PROVIDER_MODE=external`) if verbatim multi-sentence answers are required.
- The **39 needs-curation + claim facts** worked through the curator queue
  before they can be activated (only the 219 ready set is activated here).
