# TIP-013 Phase A · V1 Parity Report (synthetic)

- Generated: 2026-08-01T23:47:07.785142+00:00
- Questions: 7
- Answer agreement: 6/7 (85.7%)
- Divergences: 1

Oracle = phase-1 pilot deterministic MOCK answering, loaded read-only against a SYNTHETIC GOI (the real l3_pipeline corpus is never touched). V2 = synthetic SOT seeded through the publish gate, asked via the RAG path. This is the template Phase B re-runs on the real 137/162 records (D-013-04).

| id | category | pilot | V2 | answer agree | honest-null agree | citation (V2) |
|----|----------|-------|----|--------------|-------------------|---------------|
| P1 | fact_lookup | answered | grounded | yes | yes | ['HERA-END'] |
| P2 | fact_lookup | answered | grounded | yes | yes | ['VEGA-PAY'] |
| P3 | fact_lookup | answered | grounded | yes | yes | ['OMNI-DEF'] |
| P4 | honest_null | null | honest_null | yes | yes | - |
| P5 | honest_null | null | honest_null | yes | yes | - |
| P6 | honest_null | null | honest_null | yes | yes | - |
| P7 | honest_null_unscoped | null | grounded | NO | NO | ['OMNI-DEF'] |

## Divergence triage

- **P7** (v2_grounds_pilot_nulls): Expected synthetic-harness artefact: V2's non-semantic offline hash embedding (REQ-010) returns an arbitrary nearest neighbour on an UNSCOPED query and the offline extractive provider grounds on it. Source-scoped asks agree. Re-measured with the real semantic embedding + provider on the real corpus in Phase B.
