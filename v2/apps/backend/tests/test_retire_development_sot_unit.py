from copy import deepcopy

import pytest

from rtr_copilot.commands import retire_development_sot as cleanup


def _inventory() -> dict[str, object]:
    return {
        "schema_version": 1,
        "canonical": {
            "active_source_revisions": 6,
            "active_records": 235,
            "active_chunks": 235,
            "sources": [{"source_key": "rtr.specs", "revision": 6}],
        },
        "enterprise_files": {"approved_documents": 43, "active_chunks": 9046},
        "targets": {
            "source_keys": ["fixture.alpha", "fixture.beta"],
            "producers": ["test-fixture", "tip011-integration"],
            "missing_producer_sources": [],
            "counts": {key: 1 for key in cleanup.ZERO_TARGET_KEYS},
            "rollback": {
                "active_revisions": [{"source_key": "fixture.alpha"}],
                "active_search_pointers": [],
                "active_records": [],
                "active_generations": [],
            },
        },
    }


def test_fingerprint_is_deterministic_for_mapping_order() -> None:
    first = _inventory()
    second = {key: first[key] for key in reversed(first)}
    assert cleanup.cleanup_fingerprint(first) == cleanup.cleanup_fingerprint(second)


def test_unknown_producer_is_refused() -> None:
    candidate = _inventory()
    candidate["targets"]["producers"].append("manual-production-import")  # type: ignore[index,union-attr]
    with pytest.raises(cleanup.CleanupRefused, match="unapproved_target_producers"):
        cleanup.validate_inventory(candidate)


def test_canonical_target_is_refused() -> None:
    candidate = _inventory()
    candidate["targets"]["source_keys"].append("rtr.specs")  # type: ignore[index,union-attr]
    with pytest.raises(cleanup.CleanupRefused, match="canonical_source_in_target"):
        cleanup.validate_inventory(candidate)


def test_postconditions_require_zero_targets_and_protected_stability() -> None:
    before = _inventory()
    after = deepcopy(before)
    after["targets"]["counts"] = {  # type: ignore[index]
        key: 0 for key in cleanup.ZERO_TARGET_KEYS
    }
    cleanup.validate_postconditions(before, after)
    after["enterprise_files"]["active_chunks"] = 9045  # type: ignore[index]
    with pytest.raises(cleanup.CleanupRefused, match="protected_measurement_changed"):
        cleanup.validate_postconditions(before, after)
