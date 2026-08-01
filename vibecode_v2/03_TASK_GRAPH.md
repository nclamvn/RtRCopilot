# TASK GRAPH · RtR Copilot V2

**Trạng thái:** Blueprint APPROVED · TIP-012 VERIFIED (01/08/2026)

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
| TIP-013 | Data migration, regression parity, staged pilot, final VERIFY | 012 | 34 REQ coverage; zero P0/P1 open; go/no-go report |

## Audit trail rule

Mỗi TIP phải có:

- Task Instruction Pack đầy đủ Acceptance Criteria.
- Builder Completion Report.
- Contractor Verify Report.
- Mọi deviation và deferred item có REQ-ID.
- Không merge/cutover khi P0/P1 fail.
