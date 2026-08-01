# CI SLO-smoke fixtures (TIP-013)

These are **synthetic k6 `--summary-export` fixtures** consumed by the
`load-smoke` stage of `.github/workflows/verify.yml`. They exist so the SLO gate
(`scripts/evaluate-slo.sh`) is exercised in CI **without** standing up the full
hardened + load stack (that heavyweight sustained k6 run stays a drill — see
`docs/slo.md` and `make load`).

- `pass/` — every metric inside the `docs/slo.md` target: `evaluate-slo.sh` must
  exit 0.
- `fail/` — one deliberate breach (point-read p95 above target): `evaluate-slo.sh`
  must exit non-zero. This proves the gate has teeth.

The `load-smoke` stage also parses every real k6 scenario with `k6 inspect`, so a
broken scenario script fails CI even though the sustained run is not executed here.
