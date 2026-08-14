from __future__ import annotations

import subprocess
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
ASSERT_SCRIPT = PROJECT_ROOT / "scripts" / "assert-release-evidence-path.sh"
TIP033_WRAPPER = PROJECT_ROOT / "scripts" / "run-tip033-recertification.sh"
TIP034_WRAPPER = PROJECT_ROOT / "scripts" / "run-tip034-pilot-capture.sh"
TIP03512_WRAPPER = PROJECT_ROOT / "scripts" / "run-tip03512-ai-surrogate.sh"
PREFLIGHT = PROJECT_ROOT / "scripts" / "verify-tip035-release.sh"
PRODUCTION_PREFLIGHT = (
    PROJECT_ROOT / "scripts" / "verify-production-configuration.sh"
)
GITIGNORE = PROJECT_ROOT / ".gitignore"
MAKEFILE = PROJECT_ROOT / "Makefile"
CI_COMMON = PROJECT_ROOT / "scripts" / "ci-common.sh"
CI_LOCAL = PROJECT_ROOT / "scripts" / "ci-local.sh"
DEPLOY = PROJECT_ROOT / "scripts" / "deploy.sh"
RESTORE = PROJECT_ROOT / "scripts" / "restore-data.sh"


def _check(path: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [str(ASSERT_SCRIPT), path],
        cwd=PROJECT_ROOT,
        capture_output=True,
        check=False,
        text=True,
    )


class ReleaseEvidenceBoundaryTests(unittest.TestCase):
    def test_accepts_ignored_runtime_evidence_path(self) -> None:
        result = _check("eval/runtime/tip034.json")

        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(result.stdout.strip().endswith("eval/runtime/tip034.json"))

    def test_rejects_tracked_candidate_source(self) -> None:
        result = _check("eval/real_world/tip034_pilot_capture.json")

        self.assertEqual(result.returncode, 2)
        self.assertIn("must stay under eval/runtime", result.stderr)

    def test_rejects_unignored_in_repository_path(self) -> None:
        result = _check("eval/release-evidence/tip034.json")

        self.assertEqual(result.returncode, 2)
        self.assertIn("must stay under eval/runtime", result.stderr)

    def test_release_wrappers_default_to_runtime_and_skip_build(self) -> None:
        for wrapper in (TIP033_WRAPPER, TIP034_WRAPPER):
            source = wrapper.read_text(encoding="utf-8")
            self.assertIn("RTR_RELEASE_EVIDENCE_DIR:-eval/runtime", source)
            self.assertIn("E2E_SKIP_BUILD:-1", source)
            self.assertIn("assert-release-evidence-path.sh", source)

    def test_ai_surrogate_wrapper_is_local_only_and_runtime_bound(self) -> None:
        source = TIP03512_WRAPPER.read_text(encoding="utf-8")

        self.assertIn("tip035_12_ai_surrogate_result.json", source)
        self.assertIn("tip034_pilot_capture.json", source)
        self.assertIn("assert-release-evidence-path.sh", source)
        self.assertIn("docker compose run --rm --no-deps", source)
        self.assertNotIn("TIP034_APPROVE_EXTERNAL", source)
        self.assertNotIn("run-enterprise-e2e.sh", source)

    def test_release_preflight_reads_runtime_evidence(self) -> None:
        source = PREFLIGHT.read_text(encoding="utf-8")
        self.assertIn("RTR_RELEASE_EVIDENCE_DIR:-eval/runtime", source)
        self.assertNotIn(
            'tip033_report="eval/real_world/tip033_latency_recertification.json"',
            source,
        )
        self.assertNotIn(
            'tip034_result="eval/pilot/tip034_campaign_result.json"', source
        )
        self.assertIn("TIP035_AI_SURROGATE_APPROVED", source)
        self.assertIn("ai_surrogate_not_human_attestation", source)
        self.assertIn("human_subjective_usefulness_not_measured", source)
        self.assertIn("verify-production-configuration.sh", source)

    def test_production_preflight_is_content_free_and_runtime_bound(self) -> None:
        source = PRODUCTION_PREFLIGHT.read_text(encoding="utf-8")

        self.assertIn("validate_production_env.py", source)
        self.assertIn("assert-release-evidence-path.sh", source)
        self.assertIn("get_settings", source)
        self.assertNotIn("set -x", source)

    def test_runtime_evidence_directory_is_ignored(self) -> None:
        patterns = GITIGNORE.read_text(encoding="utf-8").splitlines()

        self.assertIn("eval/runtime/", patterns)
        self.assertIn(".env.production", patterns)

    def test_pilot_evaluator_writes_only_runtime_evidence(self) -> None:
        source = MAKEFILE.read_text(encoding="utf-8")

        self.assertIn(
            "PILOT_CAMPAIGN_LEDGER ?= /app/eval/runtime/tip034_observations.json",
            source,
        )
        self.assertIn(
            "PILOT_CAMPAIGN_OUTPUT ?= /app/eval/runtime/tip034_campaign_result.json",
            source,
        )
        self.assertIn(
            "PILOT_ACCEPTANCE_REPORT ?= /app/eval/runtime/tip034_pilot_capture.json",
            source,
        )

    def test_empty_optional_compose_build_args_are_nounset_safe(self) -> None:
        helper = CI_COMMON.read_text(encoding="utf-8")
        ci_local = CI_LOCAL.read_text(encoding="utf-8")
        deploy = DEPLOY.read_text(encoding="utf-8")

        self.assertIn("rtr_compose_build()", helper)
        self.assertIn("${#RTR_COMPOSE_BUILD_ARGS[@]}", helper)
        self.assertIn("rtr_compose_build docker compose build", ci_local)
        self.assertIn("rtr_compose_build \"${HARDENED_COMPOSE[@]}\"", deploy)
        self.assertNotIn(
            'build "${RTR_COMPOSE_BUILD_ARGS[@]}"', ci_local
        )
        self.assertNotIn(
            'build "${RTR_COMPOSE_BUILD_ARGS[@]}"', deploy
        )

    def test_restore_batches_object_copies_in_one_container(self) -> None:
        source = RESTORE.read_text(encoding="utf-8")

        self.assertIn("object-copy.nul", source)
        self.assertIn("while IFS= read -r -d '' object_key", source)
        self.assertIn(r'\"/objects/\$object_key\"', source)
        self.assertNotIn("while IFS='|' read -r object_key", source)
