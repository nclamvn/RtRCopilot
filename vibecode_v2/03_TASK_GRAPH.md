# TASK GRAPH · RtR Copilot V2

**Trạng thái:** TIP-022 + TIP-018 VERIFIED · TIP-014 SAFE CORE VERIFIED / REAL EMBEDDING PENDING · TIP-023 LOCAL VERIFIED / CI PENDING (04/08/2026)

```text
TIP-001 Security containment
        │
        ▼
TIP-002 Platform scaffold ───────┬──────► TIP-003 Identity & policy
        │                        │
        ├──────► TIP-004 Data/object/audit foundation
        │                        │
        │                        ├──────► TIP-005 Ingestion & renditions
        │                        └──────► TIP-006 SOT publish & provenance
        │                                           │
        │                               ┌───────────┴───────────┐
        │                               ▼                       ▼
        │                        TIP-007 Hybrid RAG       TIP-008 File workspace
        │                               │                       │
        └───────────────────────────────┴───────────┬───────────┘
                                                    ▼
                                           TIP-009 Document OS
                                                    │
                           ┌────────────────────────┴────────────────────┐
                           ▼                                             ▼
                 TIP-010 Governance/research                  TIP-011 Unified UX
                           └────────────────────────┬────────────────────┘
                                                    ▼
                                         TIP-012 Production hardening
                                                    │
                                                    ▼
                                         TIP-013 Migration & VERIFY
```

| TIP | Deliverable | Depends | Gate chính |
|---|---|---|---|
| TIP-001 ✅ | Vá auth P0 trên pilot + regression matrix | None | VERIFIED: 288 regression + 25 independent probes, 0 fail |
| TIP-002 ✅ | V2 monorepo, manifests, local compose, API/web/worker skeleton | 001 | VERIFIED: 12/12 AC; 7 services; audit clean; browser 2/2 |
| TIP-003 ✅ | OIDC, immutable user IDs, RBAC/ABAC policy service | 002 | VERIFIED: 11/11 AC; 86 tests; stale-session invalidation |
| TIP-004 ✅ | PostgreSQL schema, migrations, object store, audit events | 002,003 | VERIFIED: 16/16 AC; 100 tests; race-safe restore |
| TIP-005 ✅ | Upload quarantine, MIME/AV, extraction, OCR/transcript, renditions | 003,004 | VERIFIED: 18/18 AC; 14 formats; 31 renditions; private engines |
| TIP-006 ✅ | SOT adapter, full provenance, freshness, atomic publish/reindex | 003,004 | VERIFIED: 16/16 AC; 153 backend + 20 integration tests; live kernel blocked read-only |
| TIP-007 ✅ | ACL-filtered hybrid retrieval, grounded answer, deep citations | 006 | VERIFIED: 17/17 AC; leak 0; Recall@5 1.00; runtime grounded + honest-null |
| TIP-008 ✅ | Files UI + viewers cho image/PDF/DOCX/XLSX/PPTX/video/audio | 005 | VERIFIED: 18/18 AC; web 28 + browser 15; backend 159 + integration 34; leak 0 |
| TIP-009 ✅ | Template registry, structured binding, render/preview/approval | 006,008 | VERIFIED: deterministic 4-format Document OS; locked SOT; approval/issuance trail |
| TIP-010 ✅ | Curator/admin flows, gaps/freshness, Refinery research adapter | 006,007 | VERIFIED: 16/16 AC; full 278/3; masquerade 0 hit; Trivy clean; restore drill PASS |
| TIP-011 ✅ | Unified Design DNA UI, Evidence Rail, responsive/WCAG/i18n | 007,008,009 | VERIFIED: 14/14 AC; axe 0 violations; keyboard E2E; full 292/3; Playwright 73/73 |
| TIP-012 ✅ | HTTPS, quotas, observability, CI/CD, security/load, backup/DR | 010,011 | VERIFIED: 16/16 AC; SLO 10/10; ingress 15/15; full 377/18/0; drills timed |
| TIP-013B ✅ | Local curated-kernel activation and pilot corpus | 013 | VERIFIED: 219 records activated in local/dev; 8 strict, 205 soft, 6 strategic; production cutover remains separate |
| TIP-014 ◐ | Query understanding: deterministic product-alias resolution + env-gated LLM rewrite (Anthropic→OpenAI fallback) | 007 | CONTRACTOR VERIFIED PARTIAL: alias + guarded rewrite + timeout/fallback + external allowlist + cost debit PASS; 413 backend/114 skipped, 57 live data tests, wrong-entity 0. Phase 0 real embedding/live benchmark remains open pending provider contract + credential |
| TIP-015 ✅ | Premium UI rebuild (PRD UI/UX v1.0): design tokens light+dark, shell/sidebar/ask/rail reskin, ⌘K palette, composer textarea, citation keyboard nav | 011 | VERIFIED: 12/12 AC; axe 0 crit/serious (5×4×2 + 10 stateful); Playwright 75/75; vitest 148; next build EXIT 0; no backend/migration change |
| TIP-016 ✅ | UI completion: mobile bottom-dock nav (§13), full light-mode for frozen pages (theming only), composer scope chips (§11) | 015 | VERIFIED: 7/7 AC; axe 0 crit/serious **both themes** (dark 5×4×2 + light 5×4 + 10 stateful); Playwright 80/80; vitest 148; next build EXIT 0; no backend/migration change |
| TIP-017 ✅ | Keyboard & theming completeness: shortcuts help dialog (`?`), light-axe extended to EN | 015,016 | VERIFIED: 6/6 AC; axe 0 crit/serious **both themes × both locales** (+ help dialog); Playwright 87/87; vitest 148; next build EXIT 0; no backend/migration change |
| TIP-018 ✅ | Real per-file retrieval: immutable version scope, private chunk plane, ACL-isolated grounding and deep citations | 007,008,011,022 | VERIFIED: schema 0010; 411 backend + 150 Web unit; DB 48/48; leak/ACL/replay probes 2/2; Playwright/axe 88/88; Trivy 0 HIGH/CRITICAL |
| TIP-019 ✅ | Theming zero-debt: rgba overlays → color-mix tokens; prefers-color-scheme default (no flash) | 016,017 | VERIFIED: 6/6 AC; axe 0 crit/serious both themes × both locales; Playwright 88/88; vitest 148; next build EXIT 0; no backend/migration change |
| TIP-020 ◇ | Pytest async-loop CI stabilization | 012 | RECOVERED / MERGED / BASELINE-VERIFIED at `356f9ac`; see traceability recovery record |
| TIP-021 ◇ | Compose readiness and tolerant cleanup stabilization | 012 | RECOVERED / MERGED / BASELINE-VERIFIED at `f816dca`; see traceability recovery record |
| TIP-022 ✅ | Recovery gate: reproducible verify, runtime/build convergence, worker operational readiness, repository hygiene | 012,013B,019 | VERIFIED: 8/8 AC; local `make verify` PASS; Playwright 88/88; Trivy 0 HIGH/CRITICAL; runtime Git/API/Web SHA converged; GitHub aggregate green |
| TIP-023 ◐ | Admin Workspace: operator-safe identities, research sources, governance settings, gap priority and job health UI | 010,011,022 | LOCAL VERIFIED: 9/9 AC; Web 162/162; Playwright 92/92; axe 0 critical/serious; full `make verify` PASS; PR/CI pending |

## Audit trail rule

Mỗi TIP phải có:

- Task Instruction Pack đầy đủ Acceptance Criteria.
- Builder Completion Report.
- Contractor Verify Report.
- Mọi deviation và deferred item có REQ-ID.
- Không merge/cutover khi P0/P1 fail.
