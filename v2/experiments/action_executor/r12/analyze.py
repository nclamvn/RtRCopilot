"""R12 valid-pair replay via pinned pure R11 arithmetic, explicit changed contract."""

import hashlib
import json
import sys
from pathlib import Path

from minimal_observer import CONTRACT, PINS, REFERENCE_ANALYSIS, MinimalObserver
from run_observed import validate_run

ON_FILES = (
    "minimal-exposure.json",
    "r12-source-seal.json",
    "phase-requests.jsonl",
    "pool-boundaries.json",
    "audit-transactions.jsonl",
    "samples.json",
    "samples.jsonl",
    "latency-summary.json",
    "r-controls.json",
)
OFF_FILES = REFERENCE_ANALYSIS.OFF_FILES
union_ns = REFERENCE_ANALYSIS.union_ns
mask_accounting = REFERENCE_ANALYSIS.mask_accounting


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: analyze.py ON-run-dir OFF-run-dir NEW-analysis-dir")
    on_root, off_root, output = map(Path, sys.argv[1:])
    if output.exists() or output.resolve() != output.absolute() or output == output.parent:
        raise ValueError("NEW nonsymlink output required")
    own_before = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    validation = validate_run(on_root)  # R12 namespace/contract/selected witness gate FIRST.
    on, on_seals = REFERENCE_ANALYSIS.load(on_root, ON_FILES)
    off, off_seals = REFERENCE_ANALYSIS.load(off_root, OFF_FILES)
    adapted = dict(on)
    adapted["observer-exposure.json"] = on["minimal-exposure.json"]
    adapted["r11-source-seal.json"] = on["r12-source-seal.json"]
    # Only in-memory keys adapt. No source/raw modification or weaker old decoder.
    rows, summary = REFERENCE_ANALYSIS.analyze(adapted, off)
    summary["measurement_contract"] = CONTRACT
    summary["R12_selected_population_validation"] = validation
    summary["limits"].append("Nested R9 helpers omitted as separate measurements, never zero.")
    _, on_after = REFERENCE_ANALYSIS.load(on_root, ON_FILES)
    _, off_after = REFERENCE_ANALYSIS.load(off_root, OFF_FILES)
    if (on_seals, off_seals) != (on_after, off_after) or own_before != hashlib.sha256(
        Path(__file__).read_bytes()
    ).hexdigest():
        raise ValueError("input/source changed during paired replay")
    packets = {
        "requests.jsonl": "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
            for row in rows
        ),
        "failed.jsonl": "".join(
            json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False) + "\n"
            for row in rows
            if not row["sample"]["okay"]
        ),
        "summary.json": json.dumps(summary, sort_keys=True, indent=2, allow_nan=False) + "\n",
        "provenance.json": json.dumps(
            {
                "ON": on_seals,
                "OFF": off_seals,
                "before_after_equal": True,
                "R12_analyzer_sha256": own_before,
                "pinned_pure_R11": PINS,
            },
            sort_keys=True,
        )
        + "\n",
    }
    if sum(len(value.encode()) for value in packets.values()) > MinimalObserver.MAX_BYTES:
        raise ValueError("NEW paired output cap")
    output.mkdir()
    for name, value in packets.items():
        with (output / name).open("x") as stream:
            stream.write(value)
    print(
        json.dumps(
            {
                "requests": len(rows),
                "files": {
                    name: hashlib.sha256(value.encode()).hexdigest()
                    for name, value in packets.items()
                },
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
