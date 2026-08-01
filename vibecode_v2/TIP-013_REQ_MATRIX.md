# TIP-013 · Final 34/34 REQ Coverage Matrix (X-Ray)

- **TIP served:** TIP-013 Phase A, item 1 (AC-A1) — final independent verification.
- **Date:** 01/08/2026
- **Auditor:** Builder (final X-Ray), branch `tip-013`, working tree uncommitted.
- **Method:** each REQ from `vibecode_v2/01_SCAN_RRI_REPORT.md` §5 was turned into a
  testable question and answered against **actual code** under `v2/apps/`, tests
  under `apps/backend/tests` + `apps/web/**` + `apps/web/tests/browser`, migrations
  under `apps/backend/migrations/versions`, and the committed verify reports
  (`TIP-00{1..12}_VERIFY_REPORT.md`). Verify reports were used only to *locate*
  evidence; every claim below is anchored to a source file, test file, migration,
  or a named committed gate line. Two pure-unit gates were re-run live to confirm
  teeth (`test_policy.py` 51 passed; `test_rag_unit.py`+`test_config.py` 23 passed).
- **"implemented" means here:** the *mechanism* is end-to-end in code with a
  passing test/gate that can be named. Per TIP-013 CONTEXT + D-013-05, a mechanism
  proven on **synthetic fixtures** is legitimately `implemented`; where real
  company data / real identity / real certs / real LLM provider proof is still
  owed, that is a **Phase-B** obligation (listed at the end), **not** a defect.
- **"partial"** = a named sub-clause of the REQ is not built (stated explicitly).
- **Paths** in the table are relative to `v2/apps/backend/src/rtr_copilot/` (backend)
  or `v2/apps/web/src/` (web) unless a fuller path is given.

## Coverage table

| REQ | P | Requirement (short) | Status | Evidence (files / tests / ACs / gates) | Gap / Disposition |
|---|---|---|---|---|---|
| REQ-001 | P0 | Data APIs fail-closed; anon only login/health | implemented | Every data router returns 401 when `subject is None` before any work: `rag/api.py:73,116,195,266`; same pattern in `ingestion/api.py`, `sot/api.py`, `documents/api.py`, `governance/api.py`. Only `api/health.py`, `api/main.py:info/ping/metrics`, `auth/api.py:login/callback` are anon. TIP-001 VERIFY 5/5 AC + 25 probes; auth precedes existence check. | None. Phase-B: re-run probes on real deployment (AC-B4). |
| REQ-002 | P0 | Auth/config store corrupt → unhealthy, no fallback | implemented | `config.py:271` `get_settings()` raises `ConfigurationError` on invalid config (no anon/passcode fallback); `production_identity_config` (`config.py:178`) fail-closed on missing OIDC/secrets. `infra/dependencies.py` marks `database_schema_outdated`/`unavailable`. TIP-001 VERIFY (corrupt store→503); TIP-012 AC-03 boot-guard subprocess test. | None. |
| REQ-003 | P0 | Corporate email login via OIDC + deprovisioning | implemented (mechanism) | `auth/oidc.py` (`ProductionOIDCProvider`: discovery/JWKS/RS256/aud/iss/exp/nonce/PKCE); `auth/api.py:148 callback` upserts from claims, `sync_authority`, rejects disabled subject; group→role mapping `auth/api.py:86`. `tests/test_oidc_provider.py`. TIP-003 re-verify: disabled subject + role-remap invalidate live sessions (9/9 prod-OIDC tests). | Phase-B: real Google Workspace tenant + allowed domains (AC-B4). |
| REQ-004 | P0 | RBAC + ABAC by action/record/file/dept/project/classification | implemented | `auth/policy.py` full engine: default-deny, explicit-deny precedence, classification clearance, department/project scoping, temporary entitlements, SoD, admin non-bypass. `tests/test_policy.py` **51 scenarios (re-run: 51 passed)**. TIP-003 AC-003.5/.6. | None. |
| REQ-005 | P0 | HTTPS, secure session, security headers, rate/body/cost limits | implemented (mechanism) | Caddy TLS ingress `v2/infra/ingress/Caddyfile`; HSTS/CSP/XFO/nosniff asserted by `tests/test_ingress_probe.py`; secure cookie `config.py:242 session_cookie_secure_effective`; rate/body via `limits/middleware.py`+`limits/rate_limit.py` (typed 429/413); cost via `limits/budget.py`. TIP-012 AC-01/02/04/05 (15/15 ingress probes). | Phase-B: real TLS certs. Small: CSP nonce-tightening deferred (D-013-07) → fix-in-pilot. |
| REQ-006 | P0 | Append-only audit by immutable user ID; retention/redaction/export | implemented | Migration `0004_append_only_audit.py:46-106` BEFORE UPDATE/DELETE trigger `audit_events is append-only`, chain anchor + head-mismatch + forbidden-material guards; `repositories/audit.py` transactional append; export `governance/audit_export.py` (admin-gated checksummed JSONL). TIP-004 AC-11/12/13; TIP-012 AC-10. | Phase-B: retention window applied to real log import. |
| REQ-007 | P0 | Only ACL-filtered + DLP-checked evidence chunks reach the model | implemented (mechanism) | `rag/retrieval.py`: metadata → `_allowed()` policy filter → content fetch → per-chunk `provider_policy.inspect` DLP before inclusion; `rag/answering.py:710` input-DLP on question + `:775 inspect_context` before provider; provider `system_policy` treats evidence as data. External provider gated by allowlist (`rag/dlp.py:26`). TIP-007 AC-05/07/16 (leak 0). | DLP **blocks** (drops chunk), does not redact (`dlp.py` `redacted=False`) — acceptable; note if redaction ever required. Phase-B: activate real external provider under allowlist. |
| REQ-008 | P0 | SOT answers cite evidence + version + effectivity | implemented | `rag/answering.py:70 verify_grounding` (every factual unit needs a marker + token overlap; blocks "verified" on claim/stale); citations carry `record_version_id`, `provenance_level`, `verification_state`, `freshness_state`, `locator` (`rag/models.py`, `rag/api.py:141`). TIP-007 AC-08/09; `tests/test_rag_unit.py` (re-run: passed). | Phase-B: real-corpus answer quality re-baseline (D-013-05). |
| REQ-009 | P0 | Honest-null; auto gap + owner + enrichment workflow | implemented | `rag/answering.py:263 _honest_null` → `_gap` routes into governed queue via `GovernanceRepository.create_or_increment_gap` (owner `rag_gap_routing_key`, dedupe by digest); no model answer when no evidence. TIP-010 AC-01/02 (gap lifecycle append-only + SLA). | None. |
| REQ-010 | P0 | Hybrid retrieval: metadata ACL → lexical/vector → rerank | implemented | `rag/retrieval.py:190 search`: policy-aware metadata pagination (avoids starvation), then `ts_rank_cd` lexical + `embedding <=> vector` cosine, reciprocal-rank fusion (`:320`). Index: migration `0007…:78` `tsvector` GIN + `0007…:91` `hnsw vector_cosine_ops`. TIP-007 AC-04 (Recall@5 1.00). | Phase-B: 64-dim offline hash embedding is functional, not semantic — real embedding/calibration owed. |
| REQ-011 | P0 | Copilot read-only view of SOT; writes via curator/publish gate | implemented | Only mutation path is `sot/service.py:255 publish` (validate→attest→atomic swap); `commands/mutation_probe.py` proves `MaintenanceActive` denial; `sot/kernel_guard.py` `probe_kernel_read_only` (before==after fingerprint). Migration `0006` DENY DELETE on 7 SOT tables. TIP-006 AC-06/14. | None. |
| REQ-012 | P0 | External corpus segregated, labeled, never masquerades as RtR fact | implemented | `research/service.py` — research lives only in `research_records`; SOT index tables never read/written; every model carries constant `zone_label="research"`; `chunks CHECK source_zone='sot'`. TIP-010 AC-07/08 masquerade probe **0 hits**. | Phase-B: real 587 research records onboarded by curators (AC-B1). |
| REQ-013 | P0 | Canonical catalog: hash, version, owner, ACL, lifecycle | implemented | `repositories/objects.py` (owner_subject_id, classification, sha256, lifecycle_state) + `documents`/resource projection; migration `0003_resource_object_foundation.py`. TIP-008 AC-01 (effective-principal catalog, signed cursor, leak probes). | Phase-B: catalog the real 1.19 GB KnowledgeBase by batch. |
| REQ-014 | P0 | Ingestion → quarantine; MIME sniff, AV, dedupe, size quota | implemented | `ingestion/service.py:125` writes `quarantine/…`, streaming sha256, `ingestion_max_upload_bytes` enforced (`:117,:136`); `ingestion/malware.py` ClamAV fail-closed; magic-byte allowlist `ingestion/validators.py`; dedupe via sha256 + `idempotency_key`. TIP-005 AC-005.1/.2/.4 (real ClamAV clean/infected). | Phase-B: ClamAV signature freshness ≤48h on real deploy (env note). |
| REQ-015 | P0 | Publish txn: validate → provenance → ACL/DLP → index → activate | implemented | `sot/service.py:255 publish` — single UoW: advisory lock, monotonic-revision guard, validate + `verify_attestation`, atomic supersede/activate, `sot_reindex_outbox` insert; `inject_failure` proves atomicity. Migration `0006`. TIP-006 AC-02/03/07/08/12. | None. |
| REQ-016 | P1 | Freshness, expiry, supersedes, conflict, owner review scheduled | implemented | `governance/queues.py:75 freshness_status` (expiring/expired), `:84 conflict_status` (disputed/superseded_ambiguous), `:80 review_status` (due/overdue SLA); surfaced live in `governance/dashboard.py`. Migration `0006` retention/effective_to. TIP-010 AC-02/03/04. | None. |
| REQ-017 | P0 | Upload/open image, PDF, DOCX, XLSX, PPTX, video, audio in app | implemented | `files/viewers.tsx` seven viewer families; `ingestion/extractors.py` 14 formats/31 renditions; browser `tests/browser/files.spec.ts`. TIP-008 AC-09..12 (image/PDF/DOCX/PPTX/XLSX/media). | Phase-B: real files. |
| REQ-018 | P1 | Viewer citation deep to page/sheet/cell/slide/timecode | implemented | `files/viewers.tsx:90-145` locators for page/slide/`start_ms`(timecode)/sheet/cell; citation `locator` dict `rag/api.py:158`; `files/evidence.ts`. TIP-008 AC-11/12/15 (cross-sheet cell locator, transcript timecodes, deep links). | None. |
| REQ-019 | P1 | OCR image/scan-PDF, table extraction, audio/video transcription | implemented (mechanism) | `ingestion/extractors.py` origins `native/ocr/transcript/render`; DOCX/XLSX/PPTX table+grid extraction; OCR (Tesseract) + `ingestion/transcribe_cli.py` (Vosk, sha-pinned model `config.py:132`). TIP-005 re-verify: real private OCR + real offline transcript PASS. | Phase-B: OCR/transcript quality on real corpus. |
| REQ-020 | P0 | Per-conversation attachment = private context, never auto-SOT | **partial** | Non-SOT clause fully enforced (uploads→quarantine→publish gate; nothing auto-SOT). Ask "file scope" (`web/.../ask/page.tsx:304`) only filters **already-published SOT** by `filters.source_key` over the ACL catalog — safe (TIP-011 AC-05, can't leak). The **private-context zone / per-attachment retrieval as answer evidence is NOT built** — explicitly deferred (inherits TIP-007 private/attachment retrieval; D-012-09, D-013-07). | **Gap:** private-context-zone attachment retrieval missing. **Disposition: fix-in-pilot (Phase B)** or a later TIP; ships today only in its safe honest-null form. |
| REQ-021 | P0 | Object store owner/ACL/classification/expiry + authorized download | implemented | `repositories/objects.py:271 presign_download` requires a `download` capability, `ExpiresIn` URL expiry; resources carry owner/classification/`retention_until`/`legal_hold` (migration `0003…:29`); `storage/s3.py`. TIP-008 AC-03 (separate download auth, view-only original opaque 404); TIP-012 AC-15 (no key/URL leak through ingress). | Phase-B: real objects. |
| REQ-022 | P0 | Template registry: schema, version, owner, approval, locked binding | implemented | `documents/service.py` templates+template_versions (field_schema, renderer_kind/version, status draft/in_review/approved/retired, owner, classification), `locked_fact` binding `:94`; `documents/validation.py`. TIP-009 VERIFY (immutable policy-filtered registry; locked-SOT binding). | Phase-B: real company templates. |
| REQ-023 | P1 | Deterministic DOCX/XLSX/PDF/PPTX/report/form generation | implemented | `documents/renderers.py:78/120/142/168` render_docx/xlsx/pptx/pdf (python-docx, openpyxl, python-pptx, reportlab `invariant=1`). TIP-009 VERIFY: deterministic double-render + LibreOffice recalculation + Vietnamese PDF text. | None. |
| REQ-024 | P1 | Real preview, edit params, re-render, save version in-app | implemented | `documents/service.py:807 render_jobs` (idempotent `canonical_input_hash`) → immutable `generated_files` versions; preview via TIP-008 viewer; `web/.../documents/page.tsx`. TIP-009 VERIFY (real preview, immutable generated history + comparison); Documents Playwright 2/2. | Phase-B: real templates/data. |
| REQ-025 | P0 | Official docs: review, approval (SoD), issuance trail | implemented | `documents/service.py` template approve gated to CURATOR/ADMIN (`:387`), document-level review/approve/issue/revoke with audit lineage; SoD from `policy.py:91`. TIP-009 VERIFY (SoD approval, issuance + revocation truth; concurrent → one canonical decision). | Phase-B: real legal-binding issuance. |
| REQ-026 | P1 | Unified workspace: Ask/Files/Documents/SOT/Gaps/Audit/Admin | implemented | `shell/AppShell.tsx` one shell + `NAV_AREAS` (Ask, Files, Documents, Knowledge, Operations, Admin); SOT/Gaps/Audit/Freshness/Conflict/Owner-review consolidated into `knowledge-ops/page.tsx` views. TIP-011 AC-01/02 (one shell, one rail); Playwright 73/73. | Note (not a gap): the 7 blueprint surfaces are hosted under Knowledge-Ops views rather than 7 separate nav items. |
| REQ-027 | P1 | Responsive, keyboard-first, WCAG 2.2 AA, Việt/Anh | implemented | `AppShell.tsx` skip-link + F6 region cycle + route-change focus; `i18n/messages.ts` vi/en (395=395 keys parity); `tests/browser/a11y.spec.ts`, `keyboard.spec.ts`. TIP-011 AC-09/10/11/12 (axe **0 violations** across 5 pages × 4 viewports × 2 locales; 5 keyboard flows). | None. |
| REQ-028 | P0 | DB transactional, object store, background workers, search index | implemented | `db/uow.py` transactional UoW; `worker/main.py` queue worker; `storage/s3.py` MinIO; search index migration `0001_extensions.py:13` `vector` + `0007…` `tsvector` GIN + `hnsw` cosine. TIP-004 (schema/migrations); TIP-007 AC-01. | Phase-B: DB pool sizing re-baseline (D-013-07). |
| REQ-029 | P0 | CI: unit/integration/E2E/a11y/security/load + migration gate | implemented | `.github/workflows/verify.yml`: migration-gate → image-policy → backend(ruff/mypy/pytest) → web(lint/type/vitest/build) → stack(compose build + **Trivy** + data-integration) → **browser(Playwright incl. a11y.spec)**; single required `verify` check. `scripts/migration-gate.sh`, `ci-local.sh`. TIP-012 AC-11. | **Small gap:** load/k6 (`load/*.js`, `scripts/run-load.sh`, `evaluate-slo.sh`) is script/drill-run (TIP-012 AC-13), **not** wired into the GH job; workflow push-trigger lists `tip-012` (not `main`/`tip-013`). **Disposition: fix-now (add a load/SLO smoke step + branch) or accept-with-owner.** |
| REQ-030 | P0 | Metrics, tracing, alert, backup/restore, RPO/RTO, rollback runbook | implemented (mechanism) | `observability/metrics.py`+`http.py`+`worker.py` Prometheus; `infra/observability/alerts.yml`+`prometheus.yml` (promtool 11 rules); `scripts/backup-data.sh`/`restore-data.sh`/`rollback.sh`; `docs/runbook.md`, `docs/slo.md`. TIP-012 AC-08/09/12/13/14 (SLO 10/10; RESTORE PASS RTO~236s; rollback timed). | Phase-B: drills re-run on real deployment; `mc mirror` restore path (D-013-07). |
| REQ-031 | P1 | Per-user + workload quota/cost; no single call blocks the app | implemented | `limits/budget.py` `CostBudget` (subject_daily + global_daily, admin-editable) enforced in `answering.py:493 _enforce_budget`/`_debit_budget`; `limits/breaker.py` circuit-breaker + bounded provider timeout; `limits/backpressure.py` queue caps (`queue_saturated`). TIP-012 AC-04/05/06/07. | Phase-B: real-provider latency/cost calibration (D-013-07). |
| REQ-032 | P1 | Admin manages users/groups/policy/source/template/job; no direct SOT edit | implemented | `governance/admin.py` + `admin_api.py` admin surface; SOT truth untouchable by admin. TIP-010 AC-11 ("admin cannot touch truth" — 7 boundary families typed-403+audit; surface-inventory test pins route set). | None. |
| REQ-033 | P1 | Refinery adapter → dataset into quarantine with graduation policy | implemented | `research/service.py` Refinery import fail-closed (contract violation rejects whole package, **zero rows**, audited, idempotent); graduation builds candidate via `research/candidate.py build_candidate_package` staged through TIP-006 `stage()` — never auto-activates. TIP-010 AC-05/09 (7 violation classes; injection tests). | Phase-B: real datasets graduated by curators (AC-B1). |
| REQ-034 | P1 | Coverage/freshness/gap dashboard from live data, no manual snapshot | implemented | `governance/dashboard.py` — tiles (coverage/freshness/gap_flow/conflict/owner_review) recomputed per request under caller scope; "no stored snapshot serves any number" (`:4`), denied rows never counted. TIP-010 AC-12 (live-reflection, zero-leak stranger); TIP-011 AC-08. | Phase-B: real corpus feeds the tiles. |

## Summary

- **Total: 34** — **implemented: 33** · **partial: 1** · **deferred (outright): 0.**
- The prior status-doc estimate (~23 end-to-end, ~9 partial) is **refuted / superseded**:
  TIP-011 (REQ-026/027) and TIP-012 (REQ-005/029/030/031) moved several rows from
  *foundation* to *implemented mechanism with a runnable gate*. Under the TIP-013
  standard (synthetic-fixture mechanism = implemented), the honest count is 33/1/0.

### Every partial / deferred + disposition

| REQ | Status | Named missing piece | Disposition |
|---|---|---|---|
| REQ-020 | partial | Private-context zone: per-conversation **attachment retrieval as answer evidence** (only ACL-safe SOT file-scoping ships today). Inherits TIP-007 private/attachment retrieval deferral (D-012-09, D-013-07). | **fix-in-pilot (Phase B)** or a dedicated later TIP. Ships now only in its safe honest-null form; not a leak risk. |

### Small in-scope items flagged on otherwise-implemented rows (fix-now candidates)

- **REQ-029:** load/k6 + SLO evaluation not wired into `.github/workflows/verify.yml`
  (exists as `scripts/`+drill); workflow push-trigger is `tip-012`. → **fix-now**
  (add a load/SLO smoke stage; add `main`) or accept-with-owner.
- **REQ-005:** CSP nonce-tightening deferred (D-013-07). → fix-in-pilot.
- **REQ-007:** DLP blocks (drops chunk) rather than redacts (`redacted=False`); fine
  for current policy — revisit only if partial-redaction is ever required.

### REQ-IDs with NO real-data proof yet (Phase B re-baseline — mechanism proven only on synthetic fixtures)

Per TIP-013 D-013-05 / AC-B1..B5, every answer-quality, retrieval, ingestion,
identity, cert, provider and governance REQ is proven **only on synthetic fixtures**
and owes a real-data proof in Phase B:

- **Identity/certs:** REQ-003 (real Google Workspace OIDC tenant + domains), REQ-005 (real TLS certs).
- **Answer/retrieval/provider:** REQ-007 (real external provider under allowlist), REQ-008, REQ-009, REQ-010 (real semantic embedding + calibration), REQ-031 (real-provider cost/latency).
- **Data/ingest/governance:** REQ-011, REQ-012, REQ-013 (real KnowledgeBase catalog), REQ-014 (ClamAV freshness on real deploy), REQ-015, REQ-016, REQ-017, REQ-019 (OCR/transcript quality), REQ-020, REQ-021, REQ-022, REQ-024, REQ-025, REQ-033, REQ-034.
- **Ops:** REQ-028 (DB pool re-baseline), REQ-030 (drills + `mc mirror` restore on real deployment).

These are Phase-B obligations, **not** defects: the mechanism is implemented and
gated on synthetic data; only the real corpus / identity / certs / provider proof
is outstanding, which by TIP-013 design is Homeowner-gated.

## Confidence notes

- **High confidence** on REQ-001..018, 021..034: each maps to a concrete module +
  named committed gate; policy/RAG/config gates were re-run live (74 tests passed)
  and the append-only trigger, publish transaction, retrieval fusion, and CI stages
  were read directly in source.
- **REQ-019 (medium-high):** OCR/transcript code + sha-pinned Vosk model are present
  and TIP-005 re-verify claims real private OCR + offline transcript PASS; I confirmed
  the code paths but did not re-execute the ClamAV/OCR/transcript containers here
  (needs full stack). Trusted via committed TIP-005 gate.
- **REQ-020 (high confidence it is partial):** I read both the Ask page scoping code
  and the TIP-007/011/012 deferral chain; the private-context/attachment retrieval is
  genuinely unbuilt (safe-form only). This is the one honest downgrade in the matrix.
- **REQ-029 (high):** I read `verify.yml` in full — load/k6 is verifiably absent from
  the CI job and the push trigger is `tip-012`; both are minor and named above.
- I did **not** run the heavy gates (compose build, Trivy, data-integration,
  Playwright, load) — those are the Contractor's AC-A6 rerun. Where I relied on a
  committed gate rather than my own execution, I said so.
