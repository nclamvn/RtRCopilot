# COMPLETION REPORT — TIP-024 · Pilot Corpus & Provenance

**Date:** 2026-08-04

**Builder disposition:** **COMPLETE · READY-with-deferred**

**Boundary:** local/dev only; no production identity, secret or owner authority
was fabricated.

## Outcome

TIP-024 converted the previously sparse Files, Templates and Research surfaces
into a governed local pilot corpus while preserving the exact provenance debt
of the active SOT. It delivered all **9/9 requirements** and left the one
human-governance blocker visible instead of promoting or rewriting truth.

## Requirement coverage

| Requirement | Result | Delivery evidence |
|---|---|---|
| REQ-024-01 | PASS | Admin-only `GET /api/v1/admin/pilot-readiness` plus VI/EN responsive Corpus panel derived from live DB state |
| REQ-024-02 | PASS | Strict, caveated, current/stale, named/placeholder owner and high-risk counts remain separate |
| REQ-024-03 | PASS | Read-only CNCL adapter validates source spans and emits one deterministic rooted Research package |
| REQ-024-04 | PASS | Persisted corroboration contract retains 16 corroborated, 24 disputed and 30 uncorroborated records |
| REQ-024-05 | PASS | Four canonical templates adapted deterministically; retired `CAND.*` keys remapped to strict HERA facts |
| REQ-024-06 | PASS | Internal output renders a visible caveat + owner; official/legal binding fails closed with `fact_caveated` |
| REQ-024-07 | PASS | Exact 30-file manifest passed containment, size, MIME and SHA-256 gates and the existing AV/ingestion/rendition/index path |
| REQ-024-08 | PASS | 32 role-labelled questions plus honest evaluator ledger; no provider result claimed |
| REQ-024-09 | PASS | Every activation command refuses production and reports `local_dev_only` |

## Live corpus reconciliation

### Source of Truth

| Measure | Live value |
|---|---:|
| Active/current records | 219 / 219 |
| Strict verified-primary baseline | 8 |
| `needs_double_check` records | 211 |
| Named-owner records | 0 |
| Migration-placeholder-owned records | 219 |
| High-risk records / high-risk caveated | 21 / 13 |
| SOT records outside `source_zone=sot` | 0 |

No SOT record, provenance level, confidence marker or owner was changed by
TIP-024. The readiness gate `caveated_named_owners` therefore remains correctly
**blocked: 0/211** until RtR assigns accountable people.

### Representative files

| Measure | Result |
|---|---:|
| Pilot documents / versions ready | 30 / 30 |
| Manifest bytes | 15,155,639 |
| Ready renditions | 83 |
| Active private file chunks | 3,252 |
| PDF / DOCX / XLSX / PPTX / image | 6 / 7 / 7 / 4 / 6 |
| Original checksum mismatch | 0 |
| Rendition lineage mismatch | 0 |
| Second-run idempotent outcomes | 30/30 |

Manifest fingerprint:
`1579aee012284e9f536c9b5c757598bb6d865eeebc0354926de1c27e840174a7`.
All artifacts remain `private_context`; the six earlier tiny PDF fixtures are
visible in global readiness totals but are not counted toward the 30-file
representative target.

The real corpus exposed and closed two ingestion defects in the shared XLSX
extractor: deterministic JSON conversion for date/time/timedelta values and
coordinate generation for sparse `openpyxl.EmptyCell` values. Regression tests
now cover both cases.

### Templates and document guard

| Template | Source/adapted SHA-256 | Adapter fingerprint |
|---|---|---|
| `congvan` | `18988756d9be4a8a…` | `8201f3a52d1d6b81…` |
| `factsheet` | `21be07bbb47105c3…` | `45191ecac203c8e6…` |
| `salesbrief` | `e356d46b00c753a4…` → `e167aa47642d4aaa…` | `5ad13d52df2d1131…` |
| `slidecard` | `0db2abf0c59bf5e7…` | `7fb816aa8df68efd…` |

- Registry SHA-256:
  `6a04dffe893a29ce3aba2a0b31afff08e4fe150d7e64c64848842190c165e630`.
- Four templates are approved for **internal pilot use only** with 11 locked
  bindings; zero is represented as approved official/legal stationery.
- Deterministic factsheet probe bound strict payload and flight facts from the
  exact active versions. Caveated company/range/IP facts appeared with visible
  owner warnings.
- The integration proof renders the internal warning into DOCX bytes and
  rejects the same caveated locked fact from an official template.

### Research

| Measure | Result |
|---|---:|
| Input claims / verbatim span pass | 124 / 124 |
| Current sourced claims | 110 |
| Research records | 70 |
| Corroborated / disputed / uncorroborated | 16 / 24 / 30 |
| Tier | P: 70 |
| Active source / imported package | 1 / 1 |

Package fingerprint:
`e0047b4fe3d98d3e9079a83f4093d6a022aa9839f9132910e3210b4e575531a5`.
Disputed records retain `value=null` and every contributing claim. Research
never enters an active SOT generation without the existing graduation gate.

### Pilot questions

- 32 questions: SOT 8, file 8, research 8, document 8.
- Personas: staff 15, leader 7, curator 6, admin 4.
- Expected outcomes: grounded 17, honest-null 6, denied 5, blocked-caveat 4.
- Current evaluator ledger: measured 0, untestable 32, failed 0,
  `provider_result_claimed=false`. Each untestable case carries the explicit
  reason `requires_authenticated_live_pilot_observation`.

This ledger is intentionally not a semantic-quality claim. Authenticated user
measurement and any live provider benchmark remain TIP-025 inputs.

## Readiness gates

| Gate | State | Actual / target |
|---|---|---:|
| Strict SOT baseline | met | 8 / 8 |
| Caveated named owners | **blocked** | 0 / 211 |
| Representative files | met | 30 / 30 |
| Viewer families | met | 5 / 4 |
| Approved internal templates | met | 4 / 4 |
| Research records | met | 70 / 50 |
| Pilot questions | met | 32 / 25 |
| Zone integrity findings | met | 0 / 0 |
| Checksum findings | met | 0 / 0 |

## Additional hardening delivered

- Added forward, idempotent Alembic repair `0011_ingestion_pub_deferred` for
  long-lived local databases stamped before the canonical 0008 column existed.
  Clean databases no-op; downgrade deliberately retains the column because it
  logically belongs to 0008.
- Updated every runtime, example, restore and migration verification pin to the
  single new head.
- Kept failed pre-repair upload attempts as auditable failed/quarantined
  history; no destructive cleanup or scanner bypass was used.

## Files of record

- `vibecode_v2/TIP-024_PILOT_CORPUS_PROVENANCE.md`
- `v2/eval/pilot/file_manifest.yaml`
- `v2/eval/pilot/file_campaign_run.json`
- `v2/apps/backend/src/rtr_copilot/pilot/questions.json`
- `v2/eval/pilot/pilot_eval_run.json`
- `vibecode_v2/TIP-024_VERIFY_REPORT.md`

## Deferred checkpoint

`READY-with-deferred` means the local pilot corpus and its controls are ready;
it does **not** mean company-wide production rollout. TIP-025 still requires
real OIDC/group mapping, production secrets/TLS, named SOT owners, an approved
pilot cohort and measured authenticated observations.
