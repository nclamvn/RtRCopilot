# TASK GRAPH · RtR Copilot V2

**Trạng thái (ledger cập nhật · 21/09/2026):** TIP-022→049 ghi sổ; hàng 039→045 chép từ header packet/Verify report của từng TIP, không suy verdict. Số TIP 041/042 từng bị cấp trùng ngày 16/09 cho hai gói mới, đã đổi thành 046/047. PR #10 (014RE) đã merge; chuỗi TIP-031→035 (+ 035.1→.19 hardening) và TIP-036→038 đã có Completion + Verify report. Verdict hiện hành: **IMPLEMENTATION LOCALLY VERIFIED tới TIP-038 (backend 717 passed) · COMPANY-WIDE RELEASE NOT YET CERTIFIED** — release path fail-loud đã dựng xong; các gate còn mở đều là gate người/Homeowner: TIP-034 usefulness với nhân viên thật (đang HUMAN_EVALUATION_PENDING), `production_configuration` (cần operator profile/OIDC/TLS thật), drill + attestation, và Homeowner GO. Promotion trước khi đóng các gate này là governance failure.

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
| TIP-029 ✅ | Approved full live campaign ×3 run (spend 08/08): run 3 **8/8 gate — 73/77 (94.8%), citation 95.7%, false-grounded 0, honest-null 100%, p95 35.8s, browser 5/5** | 027.5 | **VERIFIED · VERDICT NÂNG: GO FOR COMPANY-WIDE INTERNAL PILOT.** Kèm 2 fix hạ tầng (bash-3.2 e2e array, stale-summary guard). Đuôi 4 case = backlog chất lượng, không phải nợ an toàn |
| TIP-029.1 ✅ | Colloquial recall recovery: tokenizer edge-punctuation (normalize_query strip mép token, giữ next.js/L3R.2.005) + exhaustive partial-over-refusal (coverage_state=partial thay honest-null) | 029 | VERIFIED: 4/7 case gốc phục hồi live; 572/127/0 hermetic; ruff/mypy 0; browser exhaustive-catalog 5/5 |
| TIP-029.2 ✅ | Weak-alias ambiguity guard: tầng `weak_aliases` (hr→HERA chỉ khi có ngữ cảnh; bare → clarification_required, chặn trước provider, đóng cả đường LLM-confirmation) | 029.1 | VERIFIED: SAFE-007 deterministic (run 3 safety 8/8, false-grounded 0); 579/127/0 hermetic; 1 contract TIP-014 phân xử spec-mới-thắng; data diff 2 dòng |
| TIP-014RE ✅ | Real embedding (đóng AC-2 của TIP-014): adapter OpenAI `text-embedding-3-small`/1536 (trust-surface fail-closed key+allowlist, default offline), migration 0013 widen vector(64)→(1536), reembed command, sàn ngữ nghĩa 0.48 (hiệu chỉnh harness trước campaign), **fix van gốc `_merge_enterprise_hits`** (dossier entity nuốt câu trả lời thuộc tính — gated intent+floor), oracle MTH-004 → proper-noun (Homeowner duyệt) | 029.2, 030 | **VERIFIED · RE-4 full campaign embedding thật: 8/8 gate — 76/77 (98.7%, +2), false-grounded 0, honest-null 1.0, methods+systems 100%, browser 5/5.** SYS-007/MTH-004/OPS-010 grounded cite đúng oracle ×2 vòng. 604/0 hermetic. Chuỗi 5 bug gốc lộ qua probe/instrumentation. CHAT-004-T1 regression an toàn → follow-up TIP-014RE.1. **Verdict nâng 98.7%** |
| TIP-030 ✅ | Quality tail 4 case: PRD-016 + COM-008 FIXED (5 vòng targeted chẩn đoán rẻ); SYS-007 + MTH-004 CLASSIFIED → acceptance test TIP-014; kênh diag `decision_diagnostic` env-gated (mặc định TẮT) + 5 cải tiến cấu trúc (relevance chấm câu gốc, llm_declined không đánh oan breaker, nhãn exhaustion mang class lỗi, checker locale-tolerant, runner capture diag) | 029.2 | **VERIFIED · Re-cert run 4: 8/8 gate — 74/77 (96.1%), false-grounded 0, honest-null 100% lần 4 liên tiếp, p95 32.2s (kỷ lục), browser 5/5.** 586/127/0 hermetic; ruff/mypy 0. Điểm trừ: OPS-010 variance planner (1-key fragility) → acceptance case thứ 3 TIP-014; key provider thứ hai NÂNG ưu tiên cao |

| TIP-031 ✅ | Pilot & production recovery | 014RE,025,029,030 | VERIFIED: PASS kỹ thuật · **CONDITIONAL PILOT GO · PRODUCTION ECOSYSTEM NOT READY**; backend 613/128; web `make verify` PASS; Trivy/pinned-image PASS |
| TIP-032 ✅ | Bounded pilot, latency recovery & CRM canary | 024.7,025,027.5,029,030,031 | VERIFIED: backend 625 + data integration 69; web 182; browser/a11y/responsive 125/125 |
| TIP-033 ✅ | Latency tail & streaming UX | 032 | VERIFIED: 12/12 AC; immutable candidate `9b019832e08a`; P95 ≈23.0s; `tip033_latency=pass` ghi vào preflight TIP-035 (không hàm ý release readiness) |
| TIP-034 ◐ | Enterprise pilot operations & usefulness campaign | 033 | **TECHNICAL_CAPTURE_PASS · HUMAN_EVALUATION_PENDING**: 27/27 case immutable, grounded success 1.0; GO usefulness bắt buộc quan sát nhân viên thật — zero-observation campaign không thể pass |
| TIP-035 ◐ | Enterprise pilot certification & production cutover (kèm chuỗi hardening 035.1→.19: runtime convergence, recertification, isolated pilot, provenance digest binding, RC + simulated-employee E2E, external recert, evidence boundary, answer stability, AI-surrogate operator E2E, conversational entity stability, release data integrity, release automation nounset, restore RTO 49s≤300s, semantic planner tail, production configuration closure, conversation anchor grounding — mỗi sub-TIP có packet + Completion + Verify riêng) | 033,034 | **IMPLEMENTATION LOCALLY VERIFIED · COMPANY RELEASE NOT YET CERTIFIED.** Release preflight fail-loud vận hành được; gate còn mở: TIP-034 usefulness (người thật), `production_configuration` (operator profile thật), drill + Homeowner attestation, Homeowner GO. Không secret/leak; corpus không gửi provider ngoài |
| TIP-036 ✅ | Ask-to-Artifact orchestration | 035.19 (`7644563`) | VERIFIED: action-boundary probes PASS — câu hỏi thường không thành action, bare create verb → clarification, template draft/retired/denied bị loại, `view`/`render` authz độc lập, không prompt/evidence trong URL/storage |
| TIP-037 ✅ | Multimodal composer & attachment-to-context | 036 | VERIFIED `PASS_LOCAL`: pytest 706/132 skip; data integration 73; Playwright browser/a11y/responsive 127/127; mypy 146 files |
| TIP-038 ✅ | Proactive enterprise intelligence (`/intelligence`: company changes, connector-governed records, publish reports) | 036,037 (`b249a20`) | VERIFIED `PASS_LOCAL`: pytest 717/132 skip; data integration 73/73; focused + shell Playwright 17/17; mypy 150 files |
| TIP-039 ◐ | Production cutover execution: đường AI-surrogate cho usefulness (tip034), lùi test người thật | 035,038 | PLANNED · chờ 6 input Homeowner Phase A0; verdict cutover sẽ mang nhãn surrogate, không thay chứng nhận người thật |
| TIP-040 ◐ | Tây Ninh corpus: Chiến lược UAV + KH 4002 + bộ ghi hiện trường; payload 14 kg (phân xử 24/08); cờ `--revision` cho run_migration | 038 (`0cf2c91`) | Phase 1+2 DONE: kernel `f0ab59a`/`8847e72`, SOT rev 3 → 4, reindex active. Phase 3 eval PENDING. Follow-up 040.1 worker poison-pill outbox, 040.2 dev DB hygiene |
| TIP-041 ✅ | US Proclamation 11055 SOT update: L3F.REG.010→015 (biểu thuế Section 232, FCC DA 26-761 Conditional Approval HERA/VEGA, correction guard policy brief), 3 hash `vanban_hoaky/*` | 040 | COMPLETE 28/08 · runtime **revision 6** active, outbox 6 dispatched. Kernel curation 28/08 chưa commit tới 16/09 (commit ở bước 0 của TIP-046) |
| TIP-042 ✅ | Product hardening: pool semantic rewriter theo fingerprint không secret + ontology digest; composer mobile 44 px | 040 (`0cf2c91`) | VERIFY `PASS_LOCAL` 31/08 |
| TIP-043 ✅ | Safe technical-debt reduction: 043.1 deterministic QA runner + warning hygiene, 043.2 implemented; 043.3 deferred | 042 | VERIFY `PASS_LOCAL` 31/08 · `DEFAULT_STOP_POINT_COMPLETE_LOCAL` |
| TIP-044 ◐ | In-app browser real-user operational E2E: 57 scenario, pilot `:3100` (`d81c1e5`) | 042,043 | VERIFY **`NOT READY`** 31/08: 2 P1 (staff thấy control curator-only, UI chỉ; Knowledge Ops trống ở 390×844), 2 P2, 1 P3; external Ask chưa chạy. Re-run P1 trên SHA rebuilt trước khi đổi verdict |
| TIP-045 ◐ | KnowledgeBase delta admission: 75 tệp delta rà soát, retire lineage test (49 → 6 active generation, 285 → 235 chunk), 2 tài liệu restricted khóa checksum, mở CONF-11 (ATOM-025 gộp NDAA/candidate/Blue UAS) | 041 (`cb6b639`) | `LOCAL SOURCES CURATED · PRIMARY RUNTIME CLEAN` 03/09 · re-embedding ngoài + kích hoạt 2 tài liệu chờ phê duyệt riêng |
| TIP-046 ◐ | Master Specification sync: 9 workbook MASTER (07/2026) → kernel (specs 19 → 107 fact strict, HC-001/002/015/020, L3F.REG.016, L3R.K.007) → Copilot; 3 phân xử Homeowner 16/09 (tầm 10 km chuẩn / 15 km @8 dBi chờ Quoc Luong; 14 kg = làm tròn 30 lb; Xavier NX 21 TOPS chuẩn, Orin 100 TOPS tùy chọn) | 040,041 | Phase 1 BUILT 16/09: dry-run validate 0 issue, A3 sạch, adapter ready 235 → 325. Chờ Homeowner áp + commit registry; Phase 2 onboarding `--revision 7`; Phase 3 eval MS-001→008. Deferred 046.D1→D4 (xem Completion report). Sai lệch ghi nhận: bộ ghi hiện trường 24/08 ghi "15 km" trần. **Phase 2 DONE 16/09:** onboarding rev 7 → 9, vá chunker TIP-046.1 (`compose_chunk_base`, `rtr-evidence-chunker/2`) vì record strict chỉ băm câu trích tiếng Anh nên câu tiếng Việt trượt; 7/8 acceptance PASS, MS-006 (so sánh hai biến thể HeraSight) chuyển TIP-046.2 chờ quyết định embedding của Homeowner |
| TIP-047 ◐ | State of New Jersey Third-Party Information Security Questionnaire 2024 (NJCCIC v1.5, 30 control area, 220 trường form) | 046 | PLANNED 16/09 · chờ Homeowner Phase A (gói thầu, cơ quan, on-prem/cloud, ISO, nhân sự VN truy cập). Nguyên tắc: không "Yes" khi không có tài liệu |
| TIP-048 ◐ | Nới kỷ luật SOT theo thực tế kinh doanh: thêm tầng `attested_practice` (lời chứng có người đứng tên + ngày) và `roadmap_commitment` (cam kết có chủ + mốc), trục `use_class` ba ngữ cảnh lồng nhau (attestation ⊂ proposal ⊂ sales), sàn cứng năm nhóm không nới; nạp 52 fact hạ tầng CNTT từ bản trả lời NJ của team phần mềm; đóng cổng bằng chứng Blue UAS; sổ chứng nhận L3F.CERT.* | 046,047 (kernel `e99624f`, app `c708ff0`) | Phase 1 đến 4 DONE 18/09: guard sạch (A3 + use-class), registry 421 entry 0 issue, adapter ready 325 → 380, **runtime revision 10 active** (l3_facts 134 → 189 chunk). Kích hoạt từ đối chiếu bản team phần mềm với bản SOT cho hồ sơ NJ: trùng thô 46,7%, nguyên nhân là lệch tiền đề kiến trúc + kernel không phủ hạ tầng CNTT. **Phát hiện phụ:** `L3F.RES.003` mang nhãn `verified_primary` cho tuyên bố Blue UAS không có tài liệu, đã sửa thành bản ghi trạng thái bằng chứng neo vào FCC DA 26-761. **Chưa qua VERIFY:** BU-001→006 chờ chạy trên UI; BU-002 chưa kiểm được vì answer layer chưa lọc theo `use_class` (deviation D3) |
| TIP-048.1 ✅ | Sửa lỗi adapter phát giá trị ngoài `Literal` của `PackageRecord` (`attested_practice`, `attested`), làm chết `run_migration --revision 10` | 048 | FIXED 18/09: ánh xạ hai tầng mới về `approved_internal` thay vì đổi schema và migration; phân biệt TIP-048 đi trong `value` qua `sot_tier` + `use_class`, `use_class` tính theo tầng kernel gốc. **Nguyên nhân để lọt: dry-run dùng backend giả nên không kiểm hợp đồng schema.** Đã dựng lại bàn thử bằng `models.py`/`package.py` thật, chạy trọn đường phát gói có ký: 380 ready, 6 gói đủ manifest + attestation + records |
| TIP-049 ◐ | Đối chiếu thư mục master mới (bản 14/09) với SOT hiện trạng trước khi đồng bộ: rà từng ô 1189 cell của 9 workbook, chỉ 3 ô đổi thật; nạp delta vào kernel (specs 107 → 124 fact: NETD bốn biến thể HeraSight, atomize HeraSight61 Standard; l3_facts 153 → 157 với sổ chứng nhận L3F.CERT.001→003 và quy ước phiên bản L3F.STD.001); ban hành 2 nghĩa vụ HARD `OBLIG.RTR.VERSION.HARDWARE_MAJOR_ONLY` và `OBLIG.RTR.MASTER_SPEC.HISTORY_LOG` | 046,048 | Phase 1 + 2 DONE 21/09: `check.sh` PASS exit 0 (441 entry, 0 issue; guard 158 verified_primary, 47 attested_practice, 10 approved_internal, 9 derived_from_verified, 5 roadmap_commitment, 26 nghĩa vụ HARD), adapter ready 398, **runtime revision 11 active** cả 6 nguồn (specs 117 chunk, l3_facts 190 chunk). Ba phân xử Homeowner 21/09: phần cứng chỉ dùng phiên bản lớn v1.0/v2.0 (phiên bản con chỉ cho phần mềm); VEGA hỗ trợ cả RTK tích hợp và RTK tương thích tùy yêu cầu khách; ban hành quy ước kèm log history vì tiến trình cũng là tài sản. **Sai lệch tự bắt:** `SPEC.RTR.VERSION_SCHEME` bị chính cổng sàn cứng chặn (tiền tố `SPEC.` cần tài liệu gốc, phân xử Homeowner không phải tài liệu) nên chuyển sang `L3F.STD.001`; cổng đúng, phân loại của Builder sai. Deferred 049.1 (HERA có cấu hình RTK tích hợp như VEGA không, chờ Quoc Luong), 049.2 (`L3R.1.015` DualSight NETD ≤ 20 mK không có master đối chứng), 049.3 (đổi tên file master theo quy ước mới) |

## Audit trail rule

Mỗi TIP phải có:

- Task Instruction Pack đầy đủ Acceptance Criteria.
- Builder Completion Report.
- Contractor Verify Report.
- Mọi deviation và deferred item có REQ-ID.
- Không merge/cutover khi P0/P1 fail.
