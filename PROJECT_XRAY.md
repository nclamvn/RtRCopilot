# RtR Copilot — Project X-Ray

> **Snapshot:** 04/08/2026 · Asia/Ho_Chi_Minh
> **Method:** Vibecode Kit v6.1 — SCAN → ANALYZE → DOCUMENT → TRACE → VERIFY
> **Repository:** `nclamvn/RtRCopilot` (private) · `main`
> **HEAD audited:** `0d8f9e0392dc9dc1eb23e7a8befcb53bda4933da`
> **Supersedes:** `PROJECT_STATUS_2026-08-01.md` and `PROJECT_STATUS_2026-08-02.md` as the canonical technical handover.

---

## 1. Overview

RtR Copilot is an internal **Enterprise Intelligence & Action OS** for Real-time
Robotics. Its current product promise is:

> One governed workspace to ask, find, inspect, verify and create from company
> truth; every important statement remains traceable to evidence, version,
> classification and authorization.

The project now contains two generations:

- **V1 / Phase 1 Pilot:** the behavioral oracle that proved kernel-wins,
  honest-null, two-tier packs, regression questions, individual login, error
  feedback and deterministic template generation.
- **V2:** a production-oriented platform that inherits V1's doctrine, content,
  design DNA and regression lessons while replacing the monolith with explicit
  identity, policy, data, object, retrieval, governance and audit boundaries.

V2 is no longer only a foundation. It includes:

- corporate identity/OIDC mechanism, RBAC + ABAC and session revocation;
- PostgreSQL/pgvector, MinIO, Redis, worker and tamper-evident audit;
- quarantine, malware scan, extraction, OCR, transcript and renditions;
- SOT package validation, provenance, freshness, atomic publish and reindex;
- hybrid retrieval, DLP, grounded answers, honest-null and deep citations;
- Files workspace and seven viewer families;
- Document Operating System with approval, issuance and revocation;
- governance/research queues, live dashboard and graduation gate;
- one shared shell for Ask, Files, Documents, Knowledge Ops and Admin;
- TLS hardening mechanism, quotas, metrics, CI/CD, load/SLO and recovery drills;
- local activation tooling for real kernel data;
- query understanding and a premium light/dark, keyboard-first UI.

### Current objective verdict

| Dimension | Assessment | Evidence-based interpretation |
|---|---:|---|
| Core architecture | **90–95%** | All major trust boundaries exist and CI is green |
| Core engineering mechanism | **88–92%** | TIP-001…012 verified; TIP-013 Phase A verified |
| Source-level product UX | **85–90%** | Unified shell and premium UI exist; Admin remains placeholder |
| Current local runtime | **PARTIAL / NOT RELEASE-CANDIDATE** | Web image is stale and worker is not running |
| Real-data rollout | **40–50%** | 219 facts activated locally; Files/Templates/Research still empty |
| Production environment activation | **55–65%** | Mechanism verified; real OIDC/TLS/secrets/pilot not activated |
| Long-term Intelligence & Action OS | **45–50%** | Evidence OS is strong; enterprise connectors and actions remain future work |

The right statement today is:

> **The production mechanism is advanced and mostly proven. The currently
> running local deployment is not synchronized with HEAD, and the product is
> not yet ready for company-wide rollout.**

---

## 2. Scan report

### 2.1 Repository metrics

| Metric | Current |
|---|---:|
| Git commits | 97 |
| First-parent commits | 68 |
| Commits after the 31/07 atlas snapshot | 71 |
| Git-tracked files | 1,411 |
| V2 backend source LOC | ~23,892 |
| V2 web source LOC | ~9,120 |
| Backend test LOC | ~16,462 |
| Web/browser test LOC | ~2,469 |
| Backend migrations | 9 |
| Live OpenAPI paths / operations | 72 / 75 |
| Local repository size | ~1.7 GB |
| Git database size | ~50 MB |

The apparent file-growth number is distorted by **902 tracked files under
`_to_delete/`**. They occupy about 34 MB and are mostly stale Git lock/object
artifacts plus transfer bundles, not product source.

### 2.2 Technology stack

| Layer | Implementation |
|---|---|
| Web | Next.js 16.2.11, React 19, TypeScript 5.9 strict |
| API | FastAPI 0.141.1, Python 3.12 |
| Persistence | PostgreSQL 16 + pgvector, SQLAlchemy async, Alembic |
| Object storage | MinIO / S3-compatible |
| Coordination | Redis + Python worker |
| File/media | PyMuPDF, pypdf, Pillow, python-docx, openpyxl, python-pptx, FFmpeg, Vosk, ClamAV |
| Documents | ReportLab + OOXML renderers + LibreOffice validation path |
| Web QA | Vitest, Testing Library, Playwright, axe-core |
| Backend QA | pytest, Ruff, strict mypy |
| Runtime | Docker Compose; optional Caddy hardened profile |
| CI/CD | GitHub Actions with migration, image policy, backend, web, stack, browser and load-smoke gates |

### 2.3 Code-health indicators

Healthy:

- strict TypeScript and strict mypy;
- 148 web unit tests pass locally;
- current Next production build passes;
- latest GitHub `verify` workflow on HEAD is green across all seven jobs;
- no tracked private-key/API-token signature was found by the bounded pattern scan;
- 9 migrations form one configured head;
- request IDs, typed errors, DLP, authorization and audit are cross-cutting;
- no debug `console.log`, `debugger`, critical TODO or FIXME was found in product paths.

Needs attention:

- local `make verify` fallback fails when `uv` is unavailable;
- the running Web container is stale relative to HEAD;
- worker container is only `Created`, not running;
- browser suite on current source is 87/88 due one ambiguous heading selector;
- `_to_delete/` is committed to `main`;
- `v2/.env.demo` is tracked and contains a non-placeholder SOT signing value;
- several status documents are stale or contradictory;
- TIP-014 has Builder reports but no independent Verify Report;
- commits labeled TIP-020/TIP-021 have no Vibecode TIP/Completion/Verify paper trail.

---

## 3. Quick start

### 3.1 Normal development profile

```bash
cd /Users/os/RtR/KnowledgeBase/RtR_Copilot/v2
cp .env.example .env
# Replace every change-this-* value.
make dev
```

Expected:

- Web: `http://127.0.0.1:3000`
- API/OpenAPI: `http://127.0.0.1:8000/docs`
- MinIO console: `http://127.0.0.1:9001`

### 3.2 Local real-kernel demo

```bash
cd /Users/os/RtR/KnowledgeBase/RtR_Copilot/v2
scripts/local-demo.sh --kernel-root /path/to/read-only-kernel
```

This path activates the curated local set through the real publish gate. It is
dev-OIDC and local signing only; it is not a production deployment.

### 3.3 Hardened profile

```bash
cd /Users/os/RtR/KnowledgeBase/RtR_Copilot/v2
make hardened-up
make hardened-probe
```

Real production still requires a real hostname/certificate, corporate OIDC,
secret injection, operator ownership and a signed go/no-go.

---

## 4. Architecture

```text
Browser
└── Unified Next.js shell
    ├── Ask
    ├── Files
    ├── Documents
    ├── Knowledge Ops
    └── Admin (placeholder UI)
          │ same-origin /api/* proxies
          ▼
FastAPI policy boundary
├── Identity / sessions / OIDC
├── RBAC + ABAC + effective principals
├── Limits / budget / breaker / backpressure
├── SOT / provenance / publish
├── RAG / query understanding / grounding
├── Ingestion / renditions
├── Document OS
├── Governance / research
└── Audit / metrics
          │
          ├── PostgreSQL + pgvector
          ├── MinIO private object storage
          └── Redis + worker
```

### Trust-zone flow

```text
External research ──► Research registry ──► Graduation proposal ─┐
                                                                │
Company kernel ─────► SOT package validation/publish gate ──────┼─► Active SOT
                                                                │       │
Private upload ─────► Quarantine/renditions/private context ─────┘       ▼
                                                                    Hybrid RAG
                                                                         │
                                                              Grounded answer/citation
```

Current gap: private file versions do not yet enter a real version-scoped
retrieval index. Ask file scope still maps the selected file to
`filters.source_key`, which is safe but only searches published SOT chunks.

---

## 5. Key components

### Identity and policy

- OIDC discovery/JWKS/RS256/audience/issuer/nonce/PKCE.
- Immutable subject IDs.
- Security-version invalidation for disabled/downgraded users.
- User/group/role/department/project effective principals.
- Explicit deny precedence and admin non-bypass.
- Policy decision audit for sensitive actions.

### SOT and provenance

- Rooted, checksummed packages.
- HMAC attestation and curator authorization.
- Typed provenance/verification/freshness.
- Atomic activation and immutable revision history.
- Durable reindex outbox.
- Live-kernel read-only fingerprint guard.

### Retrieval and answering

- Lexical + vector candidates and reciprocal-rank fusion.
- Policy metadata filtering before content access.
- DLP before provider invocation.
- Citation-per-factual-unit grounding.
- Honest-null and governed gap creation.
- Product alias/entity resolution.
- Optional Anthropic → OpenAI query-rewrite chain with deterministic fallback.

Important limitation: indexing and querying still instantiate
`OfflineHashEmbedding`. A real semantic embedding adapter has not yet replaced
the 64-dimensional functional stub.

### File workspace

- 14 accepted inputs and 31 required rendition outputs.
- Quarantine, MIME sniffing, archive checks and ClamAV.
- OCR, transcript, semantic Office views and byte ranges.
- Deep locators for page/sheet/cell/slide/timecode.
- Separate `view` and `download` authorization.

### Document OS

- Immutable template/version registry.
- Typed user/derived/locked-SOT bindings.
- Deterministic DOCX/XLSX/PPTX/PDF rendering.
- Generated-file history and Files viewer reuse.
- Review, separation of duties, issuance and revocation.

### Governance and research

- Gap, freshness, conflict and owner-review queues.
- Research source/package/record registry.
- Zone-label enforcement and masquerade probes.
- Graduation proposal that stops at the SOT publish gate.
- Live policy-filtered dashboard.

### Production controls

- Caddy TLS profile and security headers.
- Rate/body/cost limits, circuit breaker and backpressure.
- Prometheus metrics/alerts and audit export.
- Backup/restore, deploy/rollback and measured SLO drills.
- GitHub Actions required aggregate gate.

---

## 6. API reference

Live OpenAPI at the audited runtime reports:

- OpenAPI 3.1.0;
- 72 paths;
- 75 operations;
- tags: auth, audit-export, documents, files, governance,
  governance-admin, knowledge, research, SOT and system.

Primary API families:

| Family | Prefix | Purpose |
|---|---|---|
| Identity | `/auth/*` | login, callback, session, dev identity |
| Ask/RAG | `/api/v1/search`, `/api/v1/ask`, conversations | retrieval and grounded answers |
| Files | `/api/v1/files/*` | catalog, upload, manifest, rendition, original |
| SOT | `/api/v1/sot/*` | stage, validate, publish, status, active records |
| Documents | `/api/v1/templates/*`, `/api/v1/documents/*` | template and generated-file lifecycle |
| Governance | `/api/v1/governance/*` | gaps, queues, dashboard and pickers |
| Admin | `/api/v1/admin/*` | subjects, settings, sources, priority and job health |
| Research | `/api/v1/research/*` | research search and scope |
| Operations | `/health/*`, `/metrics`, `/system/ping` | health, metrics and worker probe |

The browser only calls same-origin Next proxies. It must never receive object
keys, internal hostnames or provider credentials.

---

## 7. Database schema

Migration head: `0009_governance_research`.

Domain groups:

| Domain | Principal tables |
|---|---|
| Identity/policy | subjects, groups, roles, policies, entitlements, subject_* |
| Data/object | sources, documents, document_versions, object_blobs, resources, acl_entries |
| Ingestion | upload_sessions, ingestion_jobs/outbox, renditions |
| SOT | sot_packages, sot_publish_runs, records, record_versions, evidence_spans, sot_active_revisions |
| RAG | chunks, search_generations, active_search_generations, conversations, messages, answer_runs/citations |
| Documents | templates, template_versions/bindings, render_jobs/bindings, generated_files, approvals, issuances |
| Governance | gaps/transitions, review_tasks, governance_settings |
| Research | research_sources, research_packages, research_records, graduation_proposals |
| Audit/recovery | audit_events, audit_chain_anchor, maintenance_state, reconciliation intents |

### Current local data snapshot

| Table/domain | Count |
|---|---:|
| Subjects | 3 |
| Active corpus records / versions | 219 / 219 |
| Search chunks | 219 |
| Formal evidence spans | 8 |
| SOT packages | 6 |
| Conversations / answer runs | 9 / 10 |
| Gaps | 1 |
| Documents / document versions | 0 / 0 |
| Templates / generated files | 0 / 0 |
| Research records | 0 |

The 219 facts are a meaningful local activation, but only 8 are strict. The
remaining ready facts are primarily soft/strategic and carry a
`needs_double_check` caveat. Files, real templates and research have not yet
been onboarded into this local database.

---

## 8. Environment variables

The canonical catalog is `v2/.env.example`. Groups include:

- PostgreSQL owner/runtime DSNs;
- Redis and S3/MinIO;
- ports and public/internal URLs;
- OIDC issuer/client/secret/domain/group mapping;
- session and secure-cookie policy;
- expected migration revision;
- SOT staging/signing;
- RAG model, chunking, retrieval, provider, timeout and DLP policy;
- quota, cost, breaker and job capacity;
- observability, retention, backup and hardened ingress;
- optional LLM rewrite keys/models.

Rules:

- production secrets must never be committed;
- `.env.demo` is dev-only and any committed signing value must never be reused;
- real OIDC and provider keys stay in the secret injection system;
- local demo and production must use different signing/session/storage credentials.

---

## 9. Build history and TIP traceability

### Original production sequence

| TIP | Status | Main output |
|---|---|---|
| 001–005 | VERIFIED | containment, platform, identity, data/object/audit, ingestion |
| 006–009 | VERIFIED | SOT, RAG, Files, Document OS |
| 010 | VERIFIED | Governance & Research |
| 011 | VERIFIED | Unified UX and shared Evidence Rail |
| 012 | VERIFIED | Production Hardening |
| 013 | Phase A VERIFIED | 34-REQ matrix, migration/parity/eval harness, go/no-go |
| 013B | Mechanism VERIFIED; local activation performed | 259 dispositions; 219 ready/activated locally |

### Later product iterations

| TIP | Audit status | Reality |
|---|---|---|
| 014 Query Understanding | **BUILT, not independently VERIFIED** | deterministic aliases + optional LLM rewrite; no formal Verify Report; real embedding still absent |
| 015 Premium UI | VERIFIED (cloud scope) | shell/Ask reskin, command palette, composer and citation keyboard nav |
| 016 UI Completion | VERIFIED (cloud scope) | mobile dock, light mode and scope chips |
| 017 Keyboard/Theming | VERIFIED (cloud scope) | shortcuts dialog and wider a11y matrix |
| 018 Per-file Retrieval | **DESIGN ONLY** | build was blocked in prior sandbox; current machine now has the required stack |
| 019 Theming Zero-Debt | VERIFIED (cloud scope) | tokenized overlays and OS theme default |
| 020/021 labels | **Code fixes only** | CI asyncio/readiness fixes exist, but formal Vibecode artifacts are absent |

Traceability debt:

- `03_TASK_GRAPH.md` marks TIP-014 ✅ without a Verify Report.
- TIP-018 still says infrastructure-blocked although Docker is now available.
- Blueprint header still says waiting for approval, while Task Graph says approved.
- TIP-010/011 task packets still say awaiting builders although Verify Reports are final.

---

## 10. Requirements traceability

The TIP-013 matrix recorded 33 implemented and one partial requirement:

- **REQ-020 partial:** private/per-conversation file retrieval is not implemented.
- All other mechanisms are represented in code/test.

X-Ray qualification:

- **REQ-032 is backend-complete but product-UI partial.** The Admin page is an
  explicit placeholder listing APIs; it does not yet let an operator manage
  subjects, settings, sources or jobs.
- **REQ-029 is CI-complete on GitHub, but local verification portability is
  currently broken** when `uv` is missing.
- Every “implemented” production mechanism still requires Phase-B evidence on
  real identity, real TLS, real files/templates/research and real provider quality.

---

## 11. Deployment

### Verified deployment mechanisms

- dev Compose profile;
- hardened Caddy profile;
- migration gate;
- image/runtime policy;
- versioned deploy and rollback ledger;
- backup/restore and SLO drills;
- GitHub Actions aggregate `verify` gate.

### Current local runtime state

| Check | Result |
|---|---|
| Docker daemon | available, server 29.4.0 |
| PostgreSQL/Redis/MinIO/ClamAV/API | running/healthy |
| Web | running and HTTP 200 on `/files` and `/ask` |
| API readiness | 200; PostgreSQL/Redis/object storage ready |
| Worker | **not running — container state Created** |
| `POST /system/ping` | **503 worker_unavailable** |
| HTTPS hardened ingress | not running |
| Corporate OIDC | not configured in demo profile |
| Web image vs HEAD | **stale** |

The API readiness endpoint does not include the worker heartbeat. A green
`/health/ready` therefore does not prove asynchronous ingestion/rendering is
available.

---

## 12. Verification snapshot

### Latest committed CI

GitHub Actions run `30795005597` on HEAD completed successfully:

- migration gate;
- image policy;
- backend;
- web;
- stack build/Trivy/data integration;
- browser;
- load smoke;
- aggregate verify.

### Independent local checks on 04/08

| Gate | Result |
|---|---|
| ESLint / TypeScript / Vitest | PASS |
| Web unit tests | 148/148 PASS |
| Next production build | PASS |
| Ruff | PASS |
| Strict mypy | PASS on 102 source files |
| Local `make verify` | **FAIL during backend collection** |
| Root cause | Docker fallback mounts only backend; TIP-013 tests need sibling `v2/eval` |
| Browser against stale container :3000 | 67/88 PASS, 21 fail |
| Browser against current source build :3001 | 87/88 PASS, 1 fail |
| Remaining source-build failure | ambiguous `heading[name="Hội thoại"]` selector; sibling heading “Hội thoại của bạn” also matches |

The 21 stale-runtime failures are deployment drift, not 21 independent UI
regressions. The one 87/88 failure is a test-selector defect, not evidence of an
end-user flow failure; it still keeps the local gate red and must be fixed.

---

## 13. Common tasks

```bash
# Status and logs
cd /Users/os/RtR/KnowledgeBase/RtR_Copilot/v2
make ps
make logs

# Full source gate
make verify

# Data and migration checks
make migration-check
make db-verify

# Browser matrix against current running Web
PLAYWRIGHT_BASE_URL=http://127.0.0.1:3000 pnpm --filter @rtr/web test:browser

# Hardened profile
make hardened-up
make hardened-probe

# Migration/pilot harness
make onboard-batch ARGS='...'
make parity
make eval

# Recovery drills
make backup BACKUP_DESTINATION=/validated/path
make restore-drill BACKUP_ARCHIVE=/validated/archive RESTORE_TARGET=... CONFIRM_TARGET=...
```

Never use `make reset` as a repair shortcut; it deletes named volumes and
requires explicit `RESET-V2`.

---

## 14. Troubleshooting

### API ready but jobs do not progress

Run:

```bash
docker compose ps -a worker
curl -X POST http://127.0.0.1:8000/system/ping
```

If the worker is not running, API readiness alone is insufficient.

### Browser tests report many missing new controls

Compare source and container age/image. Rebuild/force-recreate the Web service
before treating missing textarea/theme/help/sidebar controls as code regression.

### `make verify` fails with `Path.parents[3] IndexError`

The `uv`-absent Docker fallback currently mounts only `apps/backend`.
TIP-013 tests need the sibling `v2/eval` directory. This is a known X-Ray
finding and belongs to the first recovery TIP.

### Local standalone Next logs `Invalid URL`

Set an absolute `API_INTERNAL_URL`. The same-origin proxy cannot construct an
upstream URL from a bare `/api/v1/*` path.

---

## 15. Gaps and risk register

| ID | Severity | Finding | Disposition |
|---|---:|---|---|
| XR-01 | P1 | Worker not running in current local deployment | Repair/redeploy before any runtime demo |
| XR-02 | P1 | Web runtime image is stale relative to HEAD | Add build SHA visibility and deployment convergence gate |
| XR-03 | P1 | REQ-020 / TIP-018 real per-file retrieval missing | Implement now; infra is available |
| XR-04 | P1 | Real semantic embedding adapter absent | Complete TIP-014 quality path before representative pilot |
| XR-05 | P1 | Real identity/TLS/secrets and production cutover not done | Phase-B controlled activation |
| XR-06 | P2 | Local `make verify` fallback broken | Fix mount/workdir and add regression |
| XR-07 | P2 | Browser source gate 87/88 due selector ambiguity | Make selector exact and rerun |
| XR-08 | P2 | Admin UI is placeholder | Build operator workspace before broad rollout |
| XR-09 | P2 | 211/219 ready facts are caveated soft/strategic | Domain-owner verification campaign |
| XR-10 | P2 | Local Files/Templates/Research counts are zero | Onboard representative pilot corpus |
| XR-11 | P2 | 902 tracked files under `_to_delete` | Remove from Git history going forward after target review |
| XR-12 | P2 | Tracked demo environment contains signing material | Untrack/replace with example; rotate if reused |
| XR-13 | P2 | TIP/doc status contradictions and missing paper trail | Reconcile Task Graph and add retroactive factual reports |
| XR-14 | P2 | Runtime has no visible build SHA | Expose release/version identity in health/status/UI |

Open P0: **0**. Open P1 findings are bounded and actionable; they block a
release-candidate claim, not continued development.

---

## 16. Future improvements

The approved continuation plan is maintained separately at:

[`vibecode_v2/04_CONTINUATION_PLAN_2026-08-04.md`](./vibecode_v2/04_CONTINUATION_PLAN_2026-08-04.md)

Strategic sequence:

1. recover one reproducible green baseline and synchronize runtime;
2. finish TIP-018 private/per-file retrieval;
3. close TIP-014 with real semantic embeddings and independent verification;
4. build the Admin workspace and onboard real pilot files/templates/research;
5. activate real OIDC/TLS/secrets and run a measured pilot;
6. only then add read connectors for MRP/CRM/HRM/IP/Workspace/chat;
7. add approved action workflows after read-side governance proves reliable.

---

## 17. Handover checklist

- [x] Project overview and architecture documented.
- [x] Quick start and deployment paths documented.
- [x] API families and schema domains documented.
- [x] TIP and requirement traceability documented.
- [x] Current runtime/data snapshot measured.
- [x] Latest CI result checked.
- [x] Local source and browser gates independently rerun.
- [ ] One-command local verification works without preinstalled `uv`.
- [ ] Runtime image and worker match HEAD.
- [ ] TIP-018 is built and verified.
- [ ] TIP-014 has independent Verify Report and real embedding evidence.
- [ ] Admin UI is operational.
- [ ] Real pilot corpus and production identity/ingress are activated.

---

*This X-Ray describes what exists at commit `0d8f9e0` and the observed local
runtime on 04/08/2026. Historical Verify Reports remain immutable evidence; stale
status headers should be corrected prospectively, not rewritten to erase history.*
