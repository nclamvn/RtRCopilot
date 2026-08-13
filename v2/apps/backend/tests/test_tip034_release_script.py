from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
WRAPPER = PROJECT_ROOT / "scripts" / "run-tip034-pilot-capture.sh"
EXPECTED_CASES = (
    "PRD-005,PRD-013,PRD-021,PRD-023,COM-002,COM-006,COM-008,COM-010,"
    "OPS-001,OPS-005,OPS-008,OPS-010,SYS-003,SYS-004,SYS-007,MTH-001,"
    "MTH-004,MTH-006,SAFE-003,SAFE-007,SAFE-008,CHAT-001-T1,CHAT-001-T2,"
    "CHAT-003-T1,CHAT-003-T2,CHAT-004-T1,CHAT-004-T2"
)


def _write_executable(path: Path, body: str) -> None:
    path.write_text(body, encoding="utf-8")
    path.chmod(0o755)


def _run_wrapper(
    *, build_identity: str, extra_env: dict[str, str] | None = None
) -> tuple[subprocess.CompletedProcess[str], Path, tempfile.TemporaryDirectory[str]]:
    temporary = tempfile.TemporaryDirectory()
    root = Path(temporary.name)
    scripts = root / "scripts"
    scripts.mkdir()
    shutil.copy2(WRAPPER, scripts / WRAPPER.name)
    capture = root / "runner-environment.txt"
    _write_executable(
        scripts / "build-identity.sh",
        f"#!/usr/bin/env bash\nprintf '%s\\n' '{build_identity}'\n",
    )
    _write_executable(
        scripts / "run-enterprise-e2e.sh",
        """#!/usr/bin/env bash
set -euo pipefail
printf '%s|%s|%s|%s|%s|%s\\n' \
  "$E2E_BUILD_IDENTITY" "$E2E_CASE_IDS" "$E2E_CONCURRENCY" \
  "$E2E_SKIP_BROWSER" "$E2E_SKIP_BUILD" "$E2E_HTTP_REPORT" \
  > "$TIP034_TEST_CAPTURE"
mkdir -p "$(dirname "$E2E_HTTP_REPORT")"
printf '%s\\n' '{"metrics":{"total":27}}' > "$E2E_HTTP_REPORT"
""",
    )
    _write_executable(
        scripts / "assert-release-evidence-path.sh",
        """#!/usr/bin/env bash
set -euo pipefail
if [[ "$1" == eval/real_world/* ]]; then
  echo "RELEASE EVIDENCE PATH FAIL" >&2
  exit 2
fi
printf '%s\\n' "$1"
""",
    )
    _write_executable(
        scripts / "jq",
        """#!/usr/bin/env python3
import json
import sys

with open(sys.argv[-1], encoding="utf-8") as source:
    print(json.load(source)["metrics"]["total"])
""",
    )
    env = {
        **os.environ,
        "PATH": f"{scripts}:{os.environ['PATH']}",
        "TIP034_APPROVE_EXTERNAL": "1",
        "TIP034_TEST_CAPTURE": str(capture),
    }
    if extra_env:
        env.update(extra_env)
    result = subprocess.run(
        [str(scripts / WRAPPER.name)],
        cwd=root,
        env=env,
        capture_output=True,
        check=False,
        text=True,
    )
    return result, capture, temporary


class Tip034ReleaseScriptTests(unittest.TestCase):
    def test_binds_clean_candidate_before_runner(self) -> None:
        build = "a" * 12
        result, capture, temporary = _run_wrapper(build_identity=build)
        self.addCleanup(temporary.cleanup)

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            capture.read_text(encoding="utf-8").strip(),
            (
                f"{build}|{EXPECTED_CASES}|1|1|1|"
                "eval/runtime/tip034_pilot_capture.json"
            ),
        )
        self.assertIn("TIP-034 PILOT CAPTURE COMPLETE", result.stdout)

    def test_rejects_dirty_candidate_before_runner(self) -> None:
        result, capture, temporary = _run_wrapper(
            build_identity=f"{'a' * 12}+{'b' * 12}"
        )
        self.addCleanup(temporary.cleanup)

        self.assertEqual(result.returncode, 2)
        self.assertFalse(capture.exists())
        self.assertIn("release candidate must be clean and committed", result.stderr)

    def test_rejects_case_scope_change_before_runner(self) -> None:
        result, capture, temporary = _run_wrapper(
            build_identity="a" * 12,
            extra_env={"E2E_CASE_IDS": "PRD-005"},
        )
        self.addCleanup(temporary.cleanup)

        self.assertEqual(result.returncode, 2)
        self.assertFalse(capture.exists())
        self.assertIn("case set is immutable", result.stderr)

    def test_rejects_tracked_report_target_before_runner(self) -> None:
        result, capture, temporary = _run_wrapper(
            build_identity="a" * 12,
            extra_env={
                "E2E_HTTP_REPORT": "eval/real_world/tip034_pilot_capture.json"
            },
        )
        self.addCleanup(temporary.cleanup)

        self.assertEqual(result.returncode, 2)
        self.assertFalse(capture.exists())
        self.assertIn("RELEASE EVIDENCE PATH FAIL", result.stderr)
