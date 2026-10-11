"""Fail-loud stdlib evidence admissions; exit code alone is never sufficient."""

import hashlib
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

PYTEST_ROOT = Path("/workspace/v2/apps/backend")
OFFLINE_NAMES = (
    "test_child_cleanup_held_record_ownership",
    "test_collector_caps_stop_and_original_failure_retention",
    "test_complete_summary_error_missing_populations",
    "test_connection_generation_and_ledger_semantics",
    "test_deterministic_analysis_and_validation_corruption",
    "test_ids_time_order_and_finite_values",
    "test_lag_bounds_and_no_catchup",
    "test_minimal_detailed_fields_and_transparent_restoration",
)
SQL_NAMES = (
    "test_canonical_legacy_equivalence",
    "test_creation_reuse_overflow_and_isolation",
    "test_cancel_query_close_fault_attribution_and_restoration",
)


def normalized_nodeid(nodeid):
    """pytest root-relative address; external files have an empty path component."""
    path, *selectors = nodeid.split("::")
    source = Path(path)
    if path and source.is_absolute():
        path = source.relative_to(PYTEST_ROOT).as_posix() if source.is_relative_to(PYTEST_ROOT) else ""
    return "::".join([path, *selectors])


def xml_identity(nodeid):
    # Follow pytest's address split while leaving parameter brackets in the name.
    address, bracket, parameter = normalized_nodeid(nodeid).partition("[")
    components = address.split("::")
    components[0] = components[0].replace("/", ".").removesuffix(".py")
    components[-1] += bracket + parameter
    return ".".join(components[:-1]), components[-1]


def expected_group(collection_path, group):
    identities = collected(collection_path)
    if group == "campaign":
        assert identities == [normalized_nodeid("/work/r17/test_r17_campaign.py::test_one_fixed_800_checkout_lifecycle_campaign")]
        return identities
    assert len(identities) == 44 and len(set(identities)) == 44
    assert identities[33:41] == [normalized_nodeid("/work/r17/test_r17_offline.py::OfflineControls::" + name) for name in OFFLINE_NAMES]
    assert identities[41:] == [normalized_nodeid("/work/r17/test_r17_sql.py::" + name) for name in SQL_NAMES]
    slices = {"old-unit": (0, 16), "old-sql": (16, 33), "offline": (33, 41), "r17-sql": (41, 44)}
    begin, end = slices[group]
    return identities[begin:end]


def junit(path, count, expected):
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    assert len(cases) == count, (path, len(cases), count)
    identities = [(case.attrib["classname"], case.attrib["name"]) for case in cases]
    assert len(set(identities)) == count, "duplicate test identity"
    wanted = [xml_identity(nodeid) for nodeid in expected]
    assert len(wanted) == count and set(identities) == set(wanted), "executed XML identities differ from fixed collected inventory"
    assert not any(list(case) for case in cases), "failure/error/skip/output child in XML"
    for suite in root.iter("testsuite"):
        assert all(int(suite.attrib.get(field, 0)) == 0 for field in ("failures", "errors", "skipped"))
    return identities


def collected(path):
    return [normalized_nodeid(line.strip()) for line in Path(path).read_text().splitlines() if "::" in line and ": " not in line]


def collection(old, combined, campaign):
    expected = collected(old)
    observed = collected(combined)
    assert len(expected) == 33 and len(observed) == 44
    assert observed[:33] == expected, "33 old identities changed"
    assert len(set(observed)) == 44
    expected_group(combined, "offline")
    expected_group(combined, "r17-sql")
    assert not any("campaign" in identity for identity in observed)
    expected_group(campaign, "campaign")


def prior(root, stage, binding):
    root = Path(root)
    assert (root / "binding.sha256").read_bytes() == Path(binding).read_bytes()
    old_inventory = Path(__file__).resolve().parents[4] / "v2/experiments/action_executor/raw/tip054-4b-full-20261007-r5qa1/r15/pre_e1/collection.stdout.txt"
    collection(old_inventory, root / "collection.stdout.txt", root / "campaign-collection.stdout.txt")
    codes = (root / "returncodes.txt").read_text().splitlines()
    assert f"stage {stage} exit 0" in codes
    if stage == "pre":
        for label in ("syntax", "pins", "ruff", "format", "collection", "campaign-collection", "inventory", "old-unit", "offline", "xml"):
            assert f"{label} 0" in codes
        junit(root / "old-unit.xml", 16, expected_group(root / "collection.stdout.txt", "old-unit"))
        junit(root / "offline.xml", 8, expected_group(root / "collection.stdout.txt", "offline"))
    else:
        for label in ("old-sql", "r17-sql", "old-xml", "r17-xml", "database_cleanup rtr_tip054_r15_local_e1", "database_cleanup rtr_tip054_r17_local_e1"):
            assert f"{label} 0" in codes
        junit(root / "old-sql.xml", 17, expected_group(root / "collection.stdout.txt", "old-sql"))
        junit(root / "r17-sql.xml", 3, expected_group(root / "collection.stdout.txt", "r17-sql"))


if __name__ == "__main__":
    command, *arguments = sys.argv[1:]
    if command == "junit":
        path, count, inventory, group = arguments
        junit(path, int(count), expected_group(inventory, group))
    elif command == "collection":
        collection(*arguments)
    elif command == "prior":
        prior(*arguments)
    elif command == "review":
        path, digest = arguments
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == digest
        assert "SOURCE ACCEPTED" in Path(path).read_text(), "independent source acceptance required"
    else:
        raise ValueError("unknown gate")
    print("R17_ADMISSION_PASS", command)
