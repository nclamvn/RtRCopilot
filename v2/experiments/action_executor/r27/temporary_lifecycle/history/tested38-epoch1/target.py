"""Exactly two local fixture scenarios; the second failure is expected evidence."""

from native import CapPath


def test_owned_pass(tmp_path: CapPath) -> None:
    print("owned stdout pass")
    path = tmp_path / "pass.txt"
    path.write_text("native fixture pass\n")
    assert path.read_bytes() == b"native fixture pass\n"


def test_owned_failure(tmp_path: CapPath) -> None:
    import sys

    print("owned stderr failure", file=sys.stderr)
    (tmp_path / "failure.txt").write_bytes(b"native fixture failure\n")
    assert False, "intentional lifecycle control"
