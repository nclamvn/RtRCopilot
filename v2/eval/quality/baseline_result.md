# TIP-013 Phase A · Answer-Quality Baseline (synthetic)

- Generated: 2026-08-01T23:54:55.386858+00:00
- Grounded rate: 100.0% (3 grounded-expected cases)
- Honest-null quality: 100.0% (4 null-expected cases)
- **Leak count: 0** (MUST be 0; any leak is a P0)
- Citation accuracy: 100.0%
- Baseline passed: YES

Real-corpus re-baseline is Phase B (D-013-05).

| id | category | expect | got | cited | correct-citation |
|----|----------|--------|-----|-------|------------------|
| E1 | fact_lookup | grounded | grounded | ['EVAL-HERA'] | yes |
| E2 | fact_lookup | grounded | grounded | ['EVAL-VEGA'] | yes |
| E3 | honest_null | null | honest_null | - | - |
| E4 | acl_restricted | null | honest_null | - | - |
| E5 | verification_gating | null | honest_null | - | - |
| E6 | cross_version_freshness | grounded | grounded | ['EVAL-TITAN'] | yes |
| E7 | research_vs_sot | null | honest_null | - | - |

## Research-zone side checks

- E7: research_hits=1, all_labeled_research=True, beacon_in_research=True
