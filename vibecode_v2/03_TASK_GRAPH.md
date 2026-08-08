# TASK GRAPH · RtR Copilot V2

**Trạng thái:** TIP-022→027.5 VERIFIED · **GO FOR BOUNDED INTERNAL PILOT** (TIP-027.5) · `main` đang dừng ở TIP-024 — chờ PR #7 merge · audit-gap 025.1/026.4 ĐÃ ĐÓNG bằng retro Completion+Verify (08/08/2026)

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
| TIP-023 ✅ | Admin Workspace: operator-safe identities, research sources, governance settings, gap priority and job health UI | 010,011,022 | VERIFIED: 9/9 AC; Web 162/162; Playwright 92/92; axe 0 critical/serious; full `make verify` PASS; GitHub 8/8; PR #5 merged |
| TIP-024 ✅ | Pilot corpus & provenance: representative Files, internal templates, Research package, readiness truth and role-labelled evaluation set | 006,008,009,010,013B,018,023 | VERIFIED READY-with-deferred: 11/11 AC; 30 real files/5 families; 4 templates; 70 research records; 32 questions; checksum/zone findings 0; 211 caveated owner assignments deferred to humans |
| TIP-024.5 ✅ | UX Recovery & Pilot Readiness: Ask-first entry, universal ask palette, conversation-first/proof-on-demand, role IA, responsive recovery, graphite monochrome premium system | 011,018,023,024 | VERIFIED: 9/9 AC; Web 166/166; Playwright 104/104; axe 0 critical/serious; 390/1280/1365 recovery + achromatic/quiet-focus/collapse-geometry contracts; production build and local visual audit PASS |
| TIP-024.6 ✅ | Answer reliability recovery | 024.5 | VERIFIED READY FOR MERGE: 8/8 acceptance scenarios; adversarial active-corpus 9/9; production answering giữ configuration-gated |
| TIP-024.7 ✅ | Enterprise query intelligence | 024.6 | VERIFIED READY FOR MERGE: 10/10 AC; live query gate 37/37; enterprise ontology population deferred |
| TIP-025 ✅ | Enterprise corpus onboarding | 024 | VERIFIED: backend hermetic 449 passed/119 skipped; data integration 61 passed |
| TIP-025.1 ✅ | Operational grounded evidence mode (`quality_llm`/`evidence_only` tách bạch, verbatim-only, certification không tính evidence-only là quality-configured) | 025 | VERIFIED (retro 08/08): backend full hermetic 568/127; focused 25/22; vitest 182/182; Playwright ask/files/shell 58/58; live inheritance qua 026.8 (HERA 1/1) + 027 (71/77) + 027.5 (12/12, citation 100%) |
| TIP-026 ✅ | Real-world enterprise acceptance campaign | 024,025 | Campaign PASS · **Product verdict trung thực: NOT READY** cho pilot toàn công ty (answer trust dưới ngưỡng — sinh ra chuỗi 026.x); backend 455 passed/119 skipped |
| TIP-026.1 ✅ | RtR company identity recovery | 026 | VERIFIED READY: 6/6 AC (100%); regression 41/41 + live corpus 9/9 |
| TIP-026.2 ✅ | Multiformat viewer fidelity recovery | 026 | VERIFIED: 458 passed/120 skipped; Office Vietnamese/layout/determinism probes PASS |
| TIP-026.3 ✅ | Corpus-wide Office glyph recovery | 026.2 | VERIFIED: 11/11 active previews trên generator 3; checksum/PDF/page/font audit toàn bộ PASS |
| TIP-026.4 ✅ | Application compact density (instrument-panel: topbar 56px, gutter 32px, canvas 470→538px, hit-area ≥44px giữ nguyên) | 024.5,026.3 | VERIFIED (retro 08/08): assertion hình học trong files/shell spec chạy PASS trong 58/58 trên production build; build EXIT 0; downstream 123/123 + 125/125 kế thừa |
| TIP-026.5 ✅ | LLM query planning + coverage-gated answers | 026 | VERIFIED: 469 passed/122 skipped; focused suite 55 passed; đóng đường false-ready khi credential trống |
| TIP-026.6 ✅ | Core answer utility recovery | 026.5 | VERIFIED: backend 485/123; integration 65 passed |
| TIP-026.7 ✅ | Pipeline consolidation + enterprise E2E | 026.6 | VERIFIED: backend 492/124; integration 66 passed |
| TIP-026.8 ✅ | Governed entity profile answers | 026.7 | VERIFIED: backend 499/124; HERA live browser journey (kèm follow-up cùng hội thoại) 1/1 |
| TIP-026.9 ✅ | Utility-first grounded copilot | 026.8 | VERIFIED READY cho authenticated internal testing: REQ 8/8; backend 500/125 |
| TIP-026.10 ✅ | Live processing + evidence inspector | 026.9 | VERIFIED: backend 501/125; data integration 67/67; SSE checkpoint verify trên production browser surface |
| TIP-026.11 ✅ | Conversational workspace + related-context rail | 026.10 | VERIFIED: web 181/181; browser + a11y + responsive 119/119; source tabs chỉ render metadata đã authorized |
| TIP-026.12 ✅ | Conversational UI + runtime integrity | 026.11 | VERIFIED: web 181/181; backend 500/125 |
| TIP-026.13 ✅ | Minimalist workspace + viewport contract | 026.12 | VERIFIED: web 181/181; Playwright 123/123; `grounded_answering=ready` |
| TIP-026.14 ✅ | Composer lifecycle + conversation isolation | 026.13 | VERIFIED: web 182/182; Playwright 125/125 |
| TIP-027 ✅ | Enterprise knowledge fabric foundation: source catalog, deterministic TheSkyWatch adapter, giữ kernel 219-chunk | 006,026 | VERIFIED: HTTP campaign 71/77 (92.2%) grounded; 5/5 live browser; field provenance + honest-null giữ nguyên |
| TIP-027.5 ✅ | Quality-first cost governance: deterministic exact path, router 1-generation-0-review, staged E2E spend guard | 027 | VERIFIED · **GO FOR BOUNDED INTERNAL PILOT**: vitest 182/182; live HTTP 12/12 + browser 5/5; citation accuracy 100%; false-grounded 0; full 77+ live campaign CHỜ duyệt chi phí (không ngầm hiểu là đã duyệt) |
| TIP-028 ✅ | Ledger recovery: bổ sung 21 hàng task-graph 024.6→027.5, phát hiện + đánh dấu 2 audit-gap (025.1, 026.4) | — | docs-only; đối chiếu từng hàng với VERIFY report gốc; không đụng code |

## Audit trail rule

Mỗi TIP phải có:

- Task Instruction Pack đầy đủ Acceptance Criteria.
- Builder Completion Report.
- Contractor Verify Report.
- Mọi deviation và deferred item có REQ-ID.
- Không merge/cutover khi P0/P1 fail.
