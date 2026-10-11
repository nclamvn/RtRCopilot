"""Fail-loud stdlib evidence admissions; exit code alone is never sufficient."""

import hashlib
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def junit(path, count):
    root = ET.parse(path).getroot()
    cases = list(root.iter("testcase"))
    assert len(cases) == count, (path, len(cases), count)
    identities = [(case.attrib["classname"], case.attrib["name"]) for case in cases]
    assert len(set(identities)) == count, "duplicate test identity"
    assert not any(list(case) for case in cases), "failure/error/skip/output child in XML"
    for suite in root.iter("testsuite"):
        assert all(int(suite.attrib.get(field, 0)) == 0 for field in ("failures", "errors", "skipped"))
    return identities


def collected(path):
    return [line.strip() for line in Path(path).read_text().splitlines() if "::" in line and ": " not in line]


def collection(old, combined, campaign):
    expected = collected(old)
    observed = collected(combined)
    assert len(expected) == 33 and len(observed) == 44
    assert observed[:33] == expected, "33 old identities changed"
    assert len(set(observed)) == 44
    assert sum("test_r17_offline.py::OfflineControls::" in identity for identity in observed) == 8
    assert sum("test_r17_sql.py::" in identity for identity in observed) == 3
    assert not any("campaign" in identity for identity in observed)
    assert collected(campaign) == ["/work/r17/test_r17_campaign.py::test_one_fixed_800_checkout_lifecycle_campaign"]


def prior(root, stage, binding):
    root = Path(root)
    assert (root / "binding.sha256").read_bytes() == Path(binding).read_bytes()
    codes = (root / "returncodes.txt").read_text().splitlines()
    assert f"stage {stage} exit 0" in codes
    if stage == "pre":
        for label in ("syntax", "pins", "ruff", "format", "collection", "campaign-collection", "inventory", "old-unit", "offline", "xml"):
            assert f"{label} 0" in codes
        junit(root / "old-unit.xml", 16)
        junit(root / "offline.xml", 8)
    else:
        for label in ("old-sql", "r17-sql", "old-xml", "r17-xml", "database_cleanup rtr_tip054_r15_local_e1", "database_cleanup rtr_tip054_r17_local_e1"):
            assert f"{label} 0" in codes
        junit(root / "old-sql.xml", 17)
        junit(root / "r17-sql.xml", 3)


if __name__ == "__main__":
    command, *arguments = sys.argv[1:]
    if command == "junit":
        junit(arguments[0], int(arguments[1]))
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
