# TIP-027 · Enterprise Knowledge Fabric Foundation

## HEADER

- **TIP-ID:** TIP-027
- **Project:** RtR Copilot V2
- **Module:** Enterprise source inventory, company-kernel admission, TheSkyWatch
  Research adapter, provenance gates and domain-stratified evaluation
- **Depends on:** TIP-010, TIP-013B, TIP-024.7, TIP-025, TIP-026.14
- **Priority:** P0
- **Status:** IMPLEMENTED · LOCAL QA PASS · FINAL LIVE ACCEPTANCE PENDING
- **Working directory:** `/Users/os/RtR/KnowledgeBase/RtR_Copilot/v2`
- **Gate:** *More data must increase utility without weakening source identity.*

## CONTEXT

The conversational surface is now useful for the activated company facts, but
the active knowledge plane is still much narrower than the RtR ecosystem. The
company owns a canonical kernel, project and capability repositories, CRM, MRP,
IP, an internal KnowledgeBase and TheSkyWatch. TheSkyWatch alone currently
publishes a normalized registry of 518 UAV variants and 296 manufacturers plus
editorial material with field-level source tiers.

The product must therefore stop treating corpus growth as ad-hoc file upload.
It needs a repeatable knowledge-fabric contract: inventory first, explicit trust
zone, deterministic adapter, content fingerprint, evidence span, admission gate,
idempotent import, drift report and domain-specific acceptance tests.

## DECISIONS LOG

| ID | Decision | Rationale |
|---|---|---|
| D-027-01 | Company-owned canonical facts enter only through the existing kernel → SOT adapter and curator publish gate | Reuse the 219-fact governed path; no second truth pipeline |
| D-027-02 | TheSkyWatch enters the Research zone, never directly as company SOT | External market evidence must remain visibly distinct |
| D-027-03 | TheSkyWatch tier mapping is `A→P`, `B→S`, `C→H`, `derived→X` | Preserve the upstream quality gradient without promotion |
| D-027-04 | Research records are split by entity and tier | A weak field cannot downgrade or launder stronger fields in the same record |
| D-027-05 | Null and unverified cells are not indexed; disputed cells are retained as disputed | Honest-null and visible conflict are more valuable than artificial coverage |
| D-027-06 | The normalized TheSkyWatch snapshot is the quoted evidence object; original upstream URLs remain locators | The exported registry is reproducible and checksum-bound, while provenance remains traceable |
| D-027-07 | Approved, immutable company-document snapshots may enter Ask through a checksum-bound manifest; live CRM/MRP/IP records still require governed read-only connectors | Useful document knowledge can be admitted now without treating transaction systems as bulk file stores |
| D-027-08 | Corpus activation is dry-run by default; `--apply` requires explicit approval and curator identity | Preserve separation of duties and reversibility |
| D-027-09 | Explicit deterministic intents such as procedure remain authoritative over an external planner | An LLM may clarify an ambiguous question, but must not turn a requested workflow into an unrelated catalog query |
| D-027-10 | Company scope is retrieval context, not an additional required answer subject when a more specific entity exists | “Quy trình CRM của RtR” must answer CRM without failing merely because every paragraph does not repeat the company name |
| D-027-11 | Procedure retrieval reserves the complete numbered sequence of the strongest governing document before fusion padding | Low-lexical intermediate steps must not disappear behind forms or adjacent documents |
| D-027-12 | Reprocessed Office renditions supersede prior renditions; Ask counts only chunks whose rendition resource is active | Corrected Vietnamese/table extraction must replace, not silently mix with, stale output |
| D-027-13 | Independent LLM review is an auditable advisory signal; deterministic citation, evidence, entity, profile and collection gates remain the final grounding authority | Live acceptance showed repeatable reviewer false negatives on correct multi-facet answers; availability cannot depend on one stochastic boolean |
| D-027-14 | Curator-owned profile facets route ordinary point questions to bounded authoritative records | Company/product/domain growth belongs in ontology data, not question-specific code or unrestricted retrieval |

## TARGET ARCHITECTURE

```text
Company canonical kernel ----------------------> SOT publish gate --------> Ask
  facts / specs / capability matrix                  (curator)              |
                                                                            |
Approved company files --> checksum manifest --> rendition + ACL gate ------+
  projects / CRM procedures / MRP snapshots          (curator)

TheSkyWatch normalized registry --> adapter --> Research registry ----> Research search
  518 UAV + 296 companies          A/P B/S C/H X      labelled          (not SOT)

CRM / MRP / IP live state --------> source inventory + connector policy gate
                                      (no direct read until approved)
```

## ACCEPTANCE CRITERIA

- **AC-01** A machine-readable inventory names every in-scope RtR source,
  owner boundary, trust zone, admission status and entry point.
- **AC-02** The company kernel continues to use the existing TIP-013B adapter;
  no duplicate or bypass SOT importer is introduced.
- **AC-03** A deterministic TheSkyWatch adapter validates the canonical registry
  fingerprint and emits the existing Research package contract.
- **AC-04** Entity facts preserve field value, status, confidence, upstream URLs
  and tier; null/unverified facts do not become searchable claims.
- **AC-05** Published TheSkyWatch articles are independently evidence-linked and
  unpublished/sample content is excluded.
- **AC-06** Re-running the adapter on identical inputs produces byte-identical
  package members and the same fingerprint.
- **AC-07** The standard Research parser accepts every emitted record and rejects
  tampering, invalid tiers and snapshot drift.
- **AC-08** Evaluation covers company, product, capability, project, market,
  competitor, manufacturer and ordinary/noisy Vietnamese questions.
- **AC-09** Runtime activation remains an explicit curator action and reports
  record/tier/corroboration counts.
- **AC-10** Completion and verification reports state the remaining gap between
  available ecosystem data and data actually answerable in Ask.

## IMPLEMENTATION SLICES

1. **TIP-027.1 · Foundation:** source inventory, TheSkyWatch adapter, package
   build/import command, tests and corpus report.
2. **TIP-027.2 · Company breadth:** onboard project/capability/document sources
   using owner-approved manifests and global ACL-aware retrieval.
3. **TIP-027.3 · Governed enterprise connectors:** read-only CDC/API adapters
   for CRM, MRP and IP with row/field policy and deletion propagation.
4. **TIP-027.4 · Federated answers:** query planner routes company questions to
   SOT and market questions to labelled Research, then cites both without mixing
   their trust claims.

## VERIFIED IMPLEMENTATION SNAPSHOT · 2026-08-06

- Default company Ask: 219 active SOT chunks plus 3,866 searchable chunks from
  43 approved current documents, for 4,085 searchable units.
- TIP-027.2 contribution: 13 documents and 614 chunks across projects,
  project-control, CRM and MRP; one restricted project document remains visible
  only to `leader` and `curator`.
- TheSkyWatch Research: 1,838 records and 8,162 admitted non-null fields from
  518 UAV variants, 296 manufacturers and 68 published articles. Research stays
  labelled and is not counted as company SOT.
- Office extraction pipeline v4 reprocessed the affected documents; stale
  rendition resources are superseded and excluded by retrieval.
- General query controls now preserve explicit procedure intent, separate
  company context from answer subjects, bind governed document identity to its
  rows, reserve complete numbered workflows before scalar fusion and prevent
  unrelated file-search padding from contaminating a curator-bound entity.
- Enterprise ontology now resolves the maintenance-program family and its
  ordinary Vietnamese aliases. Point lookups include technology-stack wording;
  yes/no enterprise questions receive an explicit useful-answer contract rather
  than an existence-only reply.
- Live grounded smoke passed for CRM B1–B9, MRP maturity, Hải Phòng and Quảng
  Ninh project questions.
- The latest complete enterprise campaign reached **71/77 HTTP scenarios
  (92.2%)**, grounded success **91.4%**, honest-null precision **100%** and
  **zero false-grounded answers**; all five live browser scenarios passed.
  Operations, methods and safety reached 100%. Citation accuracy (92.9%) and
  p95 latency (60.51 s versus the 60 s gate) kept the campaign in NO-GO.
- Selective live remediation then recovered the previously failing HERA pin,
  SkyWatch 360, Sales Brief filename, HERA maintenance and CRM follow-up cases.
  Final architecture changes removed reviewer false-negative veto, replaced the
  four-word answer-subject heuristic and added governed company facets for
  identity, brand, contact, positioning, leadership and recognition.
- Those final changes pass hermetic QA, but live recertification remains
  pending because the provider account now returns
  `insufficient_quota / credit_balance_exhausted`.
- Remaining work is deliberately visible: TIP-027.3 live connectors and
  TIP-027.4 Research federation are not claimed complete.

## DEFERRED / OUT OF CURRENT RELEASE

- no direct database reads from CRM/MRP/IP;
- no auto-graduation of TheSkyWatch Research into SOT;
- no copying credentials, personal data or transaction rows;
- no claim that inventory presence equals Ask coverage.
