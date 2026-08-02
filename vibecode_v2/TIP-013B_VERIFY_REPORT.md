# VERIFY REPORT — TIP-013B · Phase B Work Package

**Date:** 02/08/2026
**Verifier:** Contractor (independent of the two builders)
**Scope:** the three Homeowner directives — relaxed migration policy + curation
scaffold (DRY-RUN), answer-time confidence caveat feature, real-activation
prep. Real activation itself remains Homeowner-gated.

---

## Verdict

**VERIFIED · READY** (mechanism), with one environment-deferred browser check.

- Acceptance: **AC-1…AC-3, AC-5, AC-6 PASS**; **AC-4 PASS in unit/jsdom scope**,
  browser Playwright run of the caveat spec deferred to open-egress env (the
  recurring next-server sandbox constraint — render proven by component test).
- P0/P1 open: **0**. No real data activated.

## SCENARIO RESULTS (independently rerun)

| AC | Verdict | Evidence |
|---|---|---|
| AC-1 relaxed-ready + soft tier | PASS | independent dry-run reproduced: **38 ready (5 strict + 33 soft) / 221 needs-curation, 0 activation**; 6 packages pass the real gate; deterministic; soft marker rides in `record.value.confidence_signal` with honest source note (real `raw_text`, no fabrication) |
| AC-2 curation worklist | PASS | `TIP-013B_CURATION_WORKLIST.md`: 41 finite `curate` facts by gap (32 kernel_refs, 3 unit-drift, 3 flag, 3 derived) + 180 claim as a separate promotion bucket |
| AC-3 answer caveat flag | PASS | backend: `confidence_caveat` + per-citation `needs_double_check` set iff a soft record is cited; false for strict-only and honest-null; RAG integration 14 passed on fresh DB |
| AC-4 web caveat render | PASS (unit/jsdom) · browser deferred | vitest: caveat renders iff flagged, `role="note"`, contrast ~15.4:1 (WCAG AA), vi/en i18n; Playwright spec compiles (13 tests); **browser run deferred** — next-server unresponsive in sandbox (env, not code) |
| AC-5 no regression | PASS | backend full **394+** class green (unit 324/109); web vitest 148 + build; the 73 prior Playwright + axe stand (web change is one additive caveat line, unit-covered); one transient vitest flake did not reproduce (148/148 ×2) |
| AC-6 activation runbook | PASS | `TIP-013B_ACTIVATION_RUNBOOK.md`: turnkey `--apply` sequence + the exact Homeowner-supplied values (H1 OIDC, H2 certs, H6 secrets incl. `SOT_SIGNING_SECRET`); agent runs no `--apply` |

## TECHNICAL HEALTH (independent)

backend ruff/mypy(99)/pytest unit **324 passed / 109 skipped**; relaxed dry-run
reproduced (38 ready, 0 activation, deterministic checksum); web lint/tsc clean,
vitest **148**, build PASS; no schema migration (soft marker + caveat flag are
metadata/response fields); no retrieval/grounding/DLP change; hermetic.

## WHAT THIS DELIVERS

The Homeowner's relaxed provenance policy is now real code: `verified_primary`
facts with a real source but no formal span are ready as **soft** — carrying an
honest short source note — and the platform is honest about it: any answer
grounded on a soft fact surfaces a small, legible "cần kiểm chứng lại" caveat,
shown ONLY on those answers (exactly the composer-disclaimer pattern requested).
Ready facts went **5 → 38** on the real kernel, and the remaining curation is a
finite, itemized worklist. The activation runbook makes the real cutover a
single reviewed step gated on the Homeowner's credentials.

## DEFERRED / NOTES

- **Browser run of the caveat Playwright spec** — env-blocked (next-server
  unresponsive in sandbox); render proven by jsdom component test; re-run on the
  Homeowner's machine. Same class as the ClamAV-freshness env note.
- **Per-citation rail chip** for soft citations — backend flag exposed, web chip
  deliberately not added (scope); clean follow-up.
- **Conversation-history replay** does not re-derive the caveat (answer-time
  only) — addable later, no migration.
- Real activation, real credentials, curation completion, go/no-go signature —
  all Homeowner, per `TIP-013B_ACTIVATION_RUNBOOK.md` + `TIP-013_GO_NO_GO.md`.

## DECISIONS / NEXT

Agent can continue autonomously on the **mechanical curation** of the 41
`curate` facts (read-only kernel, dry-run until clean) and the 180 `claim`
promotion triage on request. Real `--apply` awaits the Homeowner's H1/H2/H6
values.

*Không sửa ngược sau khi commit.*
