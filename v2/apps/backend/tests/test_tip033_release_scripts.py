from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


PROJECT_ROOT = Path(__file__).resolve().parents[3]
VERIFY_SCRIPT = PROJECT_ROOT / "scripts" / "verify-tip033-report.sh"
CASE_IDS = ["OPS-010", "SYS-007", "MTH-004", "PRD-001", "PRD-023"]


def _report(build: str = "a" * 12) -> dict[str, object]:
    return {
        "runtime_build_identity": build,
        "selected_case_ids": CASE_IDS,
        "metrics": {
            "total": 5,
            "passed": 5,
            "false_grounded_count": 0,
            "citation_accuracy": 1.0,
            "p95_latency_ms": 21_527.255,
        },
        "results": [
            {"latency_ms": latency}
            for latency in (5_407, 9_965, 11_985, 17_564, 21_527)
        ],
    }


def _verify(
    report: dict[str, object], expected_build: str
) -> subprocess.CompletedProcess[str]:
    with tempfile.TemporaryDirectory() as temp_dir:
        report_path = Path(temp_dir) / "tip033.json"
        report_path.write_text(json.dumps(report), encoding="utf-8")
        return subprocess.run(
            [str(VERIFY_SCRIPT)],
            cwd=PROJECT_ROOT,
            env={
                **os.environ,
                "TIP033_REPORT": str(report_path),
                "TIP033_EXPECTED_BUILD": expected_build,
            },
            capture_output=True,
            check=False,
            text=True,
        )


class Tip033ReleaseScriptTests(unittest.TestCase):
    def test_accepts_numeric_one_point_zero(self) -> None:
        result = _verify(_report(), "a" * 12)

        self.assertEqual(result.returncode, 0)
        self.assertIn("TIP-033 RECERTIFICATION PASS", result.stdout)

    def test_rejects_stale_build(self) -> None:
        result = _verify(_report(), "b" * 12)

        self.assertEqual(result.returncode, 1)
        self.assertIn(
            "build, immutable case set, quality or latency gate failed",
            result.stderr,
        )

    def test_rejects_latency_over_budget(self) -> None:
        report = _report()
        metrics = report["metrics"]
        self.assertIsInstance(metrics, dict)
        assert isinstance(metrics, dict)
        metrics["p95_latency_ms"] = 25_000.001

        result = _verify(report, "a" * 12)

        self.assertEqual(result.returncode, 1)
