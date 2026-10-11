"""R-only frozen-source result, separate from child gate correctness verdict."""
import json
import sys
from pathlib import Path

root = Path(sys.argv[1])
assert str(root).startswith("/evidence/r_bind_")
expected = (root / "expected-product.sha256").read_text().strip()
before_product = (root / "product-before.sha256").read_text().split()[0]
after_product = (root / "product-after.sha256").read_text().split()[0]
before = json.loads((root / "source-before.json").read_text())
after = json.loads((root / "source-after.json").read_text())
changed = sorted(key for key in before.keys() | after.keys() if before.get(key) != after.get(key))
child_code = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2] != "unknown" else None
bound = not changed and before_product == after_product == expected
report = {
    "source_test_old_and_r_helpers_and_env_example_unchanged": not changed,
    "source_binding_count": len(before),
    "changed_binding_keys": changed,
    "expected_product_sha256": expected,
    "product_before_sha256": before_product,
    "product_after_sha256": after_product,
    "product_frozen_expected_unchanged": before_product == after_product == expected,
    "boundary_status": "PASS" if bound else "FAIL",
    "child_exit_code": child_code,
    "child_gate_status": (
        "NOT_REPORTED" if child_code is None else "PASS" if child_code == 0 else "FAIL"
    ),
    "limits": (
        "Source binding is not correctness acceptance. Child failures preserved; "
        "unknown manual outcome not inferred. Original gate helpers unmodified. "
        "New R guard verifies finite owned capacity before every delegated CREATE DATABASE; "
        "no image/volume/prune or product commands mocked."
    ),
}
(root / "binding-result.json").write_text(json.dumps(report, indent=2))
print(json.dumps(report, indent=2))
if not bound:
    raise SystemExit(2)
