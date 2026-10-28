"""Frozen inputs and honest deterministic rubric checks, never a model judge."""
import csv
import hashlib
import io
import json
from pathlib import Path
import re

from .budget import digest


DEFAULT_CORPUS = Path(__file__).resolve().parents[3] / "tests" / "fixtures" / "aw04" / "campaign.json"


def load_corpus(path=DEFAULT_CORPUS):
    path = Path(path)
    if path.stat().st_size > 200000:
        raise ValueError("campaign_too_large")
    data = json.loads(path.read_text())
    cases, sources = data["cases"], data["sources"]
    if (len(cases) != 12 or len({c["id"] for c in cases}) != 12
            or len({c["domain"] for c in cases}) != 2
            or sum(c["split"] == "dev" for c in cases) != 6
            or sum(c["split"] == "holdout" for c in cases) != 6):
        raise ValueError("campaign_shape_invalid")
    for c in cases:
        if not c["turns"] or not c["rubric"]["semantic"]:
            raise ValueError("campaign_rubric_missing")
        for name in c["sources"]:
            if name not in sources or Path(name).name != name or len(sources[name].encode()) > 256000:
                raise ValueError("campaign_source_invalid")
    if sum(len(v.encode()) for v in sources.values()) > 1000000:
        raise ValueError("campaign_source_limit")
    return data


def manifest(data):
    return {
        "schema_version": 1,
        "campaign": data["campaign"],
        "corpus_digest": digest(data),
        "source_digests": {n: hashlib.sha256(v.encode()).hexdigest() for n, v in sorted(data["sources"].items())},
        "case_digests": {c["id"]: digest(c) for c in data["cases"]},
        "split_counts": {s: sum(c["split"] == s for c in data["cases"]) for s in ("dev", "holdout")},
        "provenance": data["provenance"],
    }


def verify_frozen(data, frozen_path):
    expected = json.loads(Path(frozen_path).read_text())
    actual = manifest(data)
    if actual != expected:
        raise ValueError("campaign_frozen_manifest_mismatch")
    return digest(actual)


def deterministic_rubric(case, sources, *, text="", artifacts=(), versions=(), evidence_kind="simulation"):
    """String/cell checks are limited evidence even on real outputs.

    semantic/human review cannot be set to PASS by this function. A fixture can
    satisfy contract checks but contributes zero semantic quality observations.
    """
    checks, rubric = [], case["rubric"]
    latest = {a["filename"]: a for a in artifacts}
    artifact = latest.get(rubric.get("artifact"))
    if "artifact" in rubric:
        checks.append(dict(name="requested_artifact_exists", passed=artifact is not None))
    content = (artifact or {}).get("content", text)
    for value in rubric.get("required_values", []):
        # Literal absence can be a harmless locale/presentation difference. Do
        # not label a formatted number a critical error without contextual review.
        checks.append(dict(name="literal_required_value:" + value, passed=True if value in content else None,
                           disposition="PASS" if value in content else "REVIEW_REQUIRED"))
    if "word_count" in rubric:
        lo, hi = rubric["word_count"]
        count = len(re.findall(r"\S+", content))
        checks.append(dict(name="word_count", passed=lo <= count <= hi, actual=count, expected=[lo, hi]))
    if "exact_csv" in rubric:
        expected = list(csv.reader(io.StringIO(sources[rubric["exact_csv"]])))
        actual = list(csv.reader(io.StringIO(content)))
        checks.append(dict(name="exact_csv_cells", passed=actual == expected))
    if "localized_edit" in rubric and len(versions) >= 2:
        old, new = versions[-2]["content"], versions[-1]["content"]
        edit = rubric["localized_edit"]
        checks.append(dict(name="localized_byte_preservation", passed=old.count(edit["old"]) == 1 and new == old.replace(edit["old"], edit["new"], 1)))
    elif "localized_edit" in rubric:
        checks.append(dict(name="localized_byte_preservation", passed=False, reason="two_versions_missing"))
    status = ("NOT_APPLICABLE" if not checks else "FAIL" if any(c["passed"] is False for c in checks)
              else "REVIEW_REQUIRED" if any(c["passed"] is None for c in checks) else "PASS")
    return dict(contract_checks=checks, contract_status=status,
                semantic_status="NOT_MEASURED" if evidence_kind != "real-provider" else "NOT_REVIEWED",
                semantic_review_required=rubric["semantic"], human_status="NOT_REVIEWED", evidence_kind=evidence_kind)
