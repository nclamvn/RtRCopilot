# TIP-013 · Deferred Ledger (TIP-007…012 triage)

- **TIP served:** TIP-013 Phase A, item 5 (AC-A5, D-013-07). Closes the deferred
  ledger inherited through TIP-012: every deferred / fix-in-pilot item gets a
  disposition — **fix-now** (a small in-scope fix applied here), **fix-in-pilot**
  (Phase B), or **accept-with-owner+date**.
- **Date:** 01/08/2026 · **Author:** Builder-2 (Phase A tooling).
- **Rule applied:** anything cheap, safe, and NOT touching app semantics or real
  data MAY be fixed now; anything touching app semantics, real data, real
  identity/certs, or that cannot be safely verified here is Phase B or a later TIP.
- Sources: `TIP-0{07,08,09,10,11,12}_VERIFY_REPORT.md` + the TIP-012 builder
  reports (`_tip012_builder{1..5}_report.md`).

## Summary table

| # | Item | Origin | Disposition | Status |
|---|------|--------|-------------|--------|
| D1 | `backup-data.sh` `stat -f%z` BSDism | TIP-012 b5 | **fix-now** | DONE (this TIP) |
| D2 | load/k6 + SLO not wired into CI | TIP-012 b5 / REQ-029 | **fix-now** | DONE (this TIP) |
| D3 | `verify.yml` push-trigger branch | TIP-012 b4 / REQ-029 | **fix-now** | DONE (this TIP) |
| D4 | `restore-data.sh` per-object `mc cp` → `mc mirror` | TIP-012 b5 | **fix-in-pilot** | NOT done — rationale below |
| D5 | File-version/attachment ask retrieval (private-context zone) | TIP-007 → 011/012, REQ-020 | **fix-in-pilot** | Phase B / later TIP |
| D6 | CSP nonce-tightening | TIP-012 b1, REQ-005 | **fix-in-pilot** | Phase B |
| D7 | DB pool sizing re-baseline (5+5 knee ~15 reads/s) | TIP-012 b5, REQ-028 | **fix-in-pilot** | Phase B (real deploy) |
| D8 | Real-provider latency/cost calibration | TIP-012 b2/b5, REQ-031 | **fix-in-pilot** | Phase B (real provider) |
| D9 | ClamAV signature freshness ≤48h | TIP-012, REQ-014 | **fix-in-pilot** | Phase B (real deploy env) |
| D10 | Branch-protection must require the `verify` job | TIP-012 b4 | **accept-with-owner** | Homeowner, at go |
| D11 | External penetration test | TIP-012 verify | **accept-with-owner** | Homeowner, go/no-go input |
| D12 | Full-fidelity Office editing | TIP-008 | **accept-with-owner** | Post-go roadmap TIP |
| D13 | Real SOT/research activation, real OIDC tenant, real TLS certs | TIP-007/010/012, many REQ | **fix-in-pilot** | Phase B (Homeowner-gated) |

Container-image / live-stack gates deferred inside TIP-010 (AC-13/15/16) were
already un-deferred in that TIP's cloud addendum and are **closed**; they are not
re-listed here.

## Fix-now items (applied in this TIP)

### D1 — `backup-data.sh` `stat -f%z` → portable size  ✅ DONE
`scripts/backup-data.sh:160` printed `bytes=$(stat -f%z "$archive")`, a BSD/macOS
form that misreports on the Linux CI runner. Replaced with a portable cascade:
`stat -c%s` (GNU/Linux) → `stat -f%z` (BSD) → `wc -c`. Verified on this Linux host
(4096-byte probe returns 4096). No app semantics touched; the `BACKUP PASS` gate
line is preserved. `bash -n` clean.

### D2 — load/SLO smoke stage in CI  ✅ DONE
The k6 load suite + `evaluate-slo.sh` existed only as a drill (`make load`),
not in `.github/workflows/verify.yml` (REQ-029 gap). Added a `load-smoke` job that
(a) parses every k6 scenario with `k6 inspect` (a broken scenario fails CI) and
(b) runs `evaluate-slo.sh` against committed pass/breach fixtures under
`load/ci-smoke/` — the in-target fixture must exit 0 and the breach fixture must
exit non-zero, so the SLO gate provably has teeth **without** standing up the
heavyweight hardened+load stack (the sustained run stays a drill by design). The
job is added to the required `verify` aggregation. `actionlint` (v1.7.7) exit 0.
Both fixtures verified locally (pass→exit 0, breach→exit 1).

### D3 — `verify.yml` push-trigger branch  ✅ DONE
Push trigger was `[main, tip-012]`. Set to `[main, tip-013]` so the current
integration branch is covered and `main` remains protected. `pull_request` trigger
(covers every PR) is unchanged. `actionlint` clean.

## Fix-in-pilot / accept items (NOT changed here — rationale)

### D4 — `restore-data.sh` `mc cp` loop → `mc mirror`  ❌ NOT a clean swap → fix-in-pilot
The per-object loop at `scripts/restore-data.sh:219-233` restores each object with
`mc cp --attr 'sha256=…;byte-size=…;upload-state=restored;restore-operation-id=…'`,
i.e. it writes **per-object** integrity + ownership metadata. The RESTORE PASS gate
depends on exactly that metadata: `commands/restore_bucket_guard.py::complete`
re-heads every object and rejects the restore unless each carries the matching
`restore-operation-id`, `sha256` and `byte-size` (`restore_bucket_guard.py:79-90`).
`mc mirror` copies object bodies but does **not** set distinct per-object `--attr`
metadata, so a naive swap would drop those markers and the guard would quarantine
the restore ("object ownership/integrity marker mismatch") — turning the drill RED.
It is therefore **not** the clean swap the ledger hoped for; making `mc mirror`
carry equivalent per-object metadata is real restore-path work. Additionally the
restore drill can only be verified end-to-end on the full containerized stack
(MinIO + Postgres + `mc`), which is not safely runnable in this Phase-A sandbox.
**Disposition: fix-in-pilot (Phase B)** — re-implement the object restore as a
single `mc mirror` (or an in-process boto3 client) that preserves the per-object
markers, and re-run the RESTORE PASS drill on the real deployment. RTO impact is
real (TIP-012 b5 measured ~236 s dominated by the one-object-per-`docker run`
loop), so this is worth doing — but not blindly.

### D5 — File-version / attachment ask retrieval (private-context zone) → fix-in-pilot
REQ-020's per-conversation attachment-as-answer-evidence is unbuilt; the Ask
"file scope" ships only in its safe, non-leaking form (ACL-filtered SOT scoping,
TIP-011 AC-05). Inherits the TIP-007 private/attachment retrieval deferral
(D-012-09). Touches answer semantics → **Phase B or a dedicated later TIP**, not a
cheap ops fix.

### D6 — CSP nonce-tightening → fix-in-pilot
The shipped CSP is static; per-response nonces require app-level template/render
changes (TIP-012 b1). Security-hardening semantics → **Phase B**.

### D7 — DB pool sizing re-baseline → fix-in-pilot (real deploy)
`db/engine.py` pools 5+5; TIP-012 b5 documented the read-throughput knee at
~15 reads/s where the pool saturates (p95 → ~1 s). Sizing the pool + Postgres
`max_connections` is a **real-deployment** capacity decision (REQ-028) → **Phase B**.

### D8 — Real-provider latency/cost calibration → fix-in-pilot (real provider)
The offline/fake provider makes the S2 ask-latency SLO optimistic and the cost
budget counts calls, not tokens (TIP-012 b2/b5). Calibration needs the real LLM
provider under the allowlist (REQ-031/007) → **Phase B**.

### D9 — ClamAV signature freshness ≤48h → fix-in-pilot (deploy env)
Sandbox egress prevents a real freshcm update; hardened runs used the documented
`MALWARE_SIGNATURE_MAX_AGE_SECONDS` override (REQ-014). Freshness is a
**real-deployment** operational guarantee → **Phase B**.

### D10 — Branch-protection must require the `verify` job → accept-with-owner
The `verify` aggregation job is the intended single required check, and this TIP
adds `load-smoke` to its `needs`. Actually marking `verify` as a *required status
check* is a GitHub repository-settings action only a repo admin can take.
**Owner: Homeowner/repo-admin, at merge-to-main / go.**

### D11 — External penetration test → accept-with-owner
Only internal adversarial probes ran (TIP-012). An external pen test is a
go/no-go input, not agent-runnable. **Owner: Homeowner, before go.**

### D12 — Full-fidelity Office editing → accept-with-owner
In-app editing beyond view/generate is a product-roadmap feature, out of the
release scope. **Owner: Homeowner, post-go roadmap TIP.**

### D13 — Real data / identity / certs activation → fix-in-pilot (Homeowner-gated)
Real SOT/research/KnowledgeBase batches, real Google Workspace OIDC tenant, real
TLS certs, real pilot questions — the entire Phase-B cutover (AC-B1…B6). The
Phase-A tooling (curator-gated `onboard-batch`, the parity + eval harnesses) is
exactly what Phase B re-runs on the real corpus. **Owner: Homeowner, Phase B.**

## Gate impact of the applied fixes

- `backup-data.sh`: `bash -n` clean; portable size logic verified on Linux.
- `verify.yml`: `actionlint` v1.7.7 exit 0; `evaluate-slo.sh` pass-fixture exit 0,
  breach-fixture exit 1 (teeth proven locally).
- No backend `ruff`/`mypy`/`pytest` surface touched by these ops fixes; the backend
  unit suite stays green (304 passed / 108 skipped).
