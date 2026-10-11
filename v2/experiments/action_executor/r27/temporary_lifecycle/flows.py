"""Real original TestCase.run and real pytest.main, not reconstructed validators."""

from __future__ import annotations

import contextlib
import io
import unittest
import xml.etree.ElementTree as ET
from collections.abc import Callable
from typing import cast

import genuine
import native
import policy


class Transport(io.StringIO):
    def __init__(self, owner: native.Owner, name: str) -> None:
        super().__init__()
        self.owner = owner
        self.name = name
        self.parts = owner.buffers[name]

    def write(self, text: str) -> int:
        raw = text.encode()
        self.owner.capture(self.name, raw)
        return super().write(text)


def original(
    owner: native.Owner, composition: genuine.Composition
) -> dict[str, object]:
    case = composition.case()
    cleanup = cast(Callable[[], bool], case.doCleanups)
    cleanup_result: list[bool] = []

    def observed_cleanup() -> bool:
        value = cleanup()
        cleanup_result.append(value)
        return value

    setattr(case, "doCleanups", observed_cleanup)
    result = unittest.TestResult()
    case.run(result)
    outcome = {
        "testsRun": result.testsRun,
        "failures": [text for _, text in result.failures],
        "errors": [text for _, text in result.errors],
        "successful": result.wasSuccessful(),
        "first_owner_fault": str(owner.first_fault) if owner.first_fault else None,
        "cleanup_errors": list(owner.cleanup_errors),
    }
    outcome["genuine_doCleanups_results"] = cleanup_result
    owner.source_outcomes.append(outcome)
    owner.check_metadata(cleanup=not result.wasSuccessful())
    if not result.wasSuccessful() or owner.first_fault is not None:
        return outcome
    frames = [f for f in owner.frames if f["role"] == "synthetic_input"]
    if (
        len(frames) != 35
        or sum(f["requested"] for f in frames) != 733169
        or owner.synthetic_calls != {k: v[0] for k, v in policy.SYNTHETIC.items()}
    ):
        owner.fail(ValueError("genuine original 35-write identity"))
    if (
        owner.synthetic_root in owner.directories
        or owner.fds
        or any(getattr(f, "alive") for f in owner.finalizers)
    ):
        owner.fail(ValueError("genuine original setup/doCleanups resource closure"))
    return outcome


def pytest_flow(
    owner: native.Owner, composition: genuine.Composition
) -> dict[str, object]:
    import pytest

    (native.CapPath(owner, "pytest-base") / "stale.txt").write_bytes(
        b"stale owned basetemp\n"
    )
    plugins = composition.plugins()
    owner.reserve_outputs()
    out, err = (
        Transport(owner, "reports/stdout.txt"),
        Transport(owner, "reports/stderr.txt"),
    )
    args = [
        str(policy.HERE / "target.py"),
        "-c",
        str(policy.HERE / "pytest.ini"),
        "--noconftest",
        "--assert=plain",
        "-p",
        "no:cacheprovider",
        "-p",
        "no:tmpdir",
        "-p",
        "no:junitxml",
        "-p",
        "no:capture",
        "-p",
        "no:logging",
        "-p",
        "no:legacypath",
        "-p",
        "no:faulthandler",
        "-p",
        "no:pastebin",
        "-q",
        "--tb=short",
        "--color=no",
    ]
    try:
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = pytest.main(args, plugins=list(plugins[:2]))
    except BaseException as error:
        owner.first_fault = owner.first_fault or error
        owner.packet.flags |= 1
        owner.source_outcomes.append(
            {
                "producer": "pytest.main",
                "exception": type(error).__name__,
                "text": str(error),
            }
        )
        raise
    finally:
        for name in ("reports/stdout.txt", "reports/stderr.txt", "reports/result.xml"):
            try:
                owner.finalize_capture(name)
            except BaseException as error:
                owner.cleanup_errors.append(str(error))
    owner.guard()
    xml = native.CapPath(owner, "reports/result.xml").read_bytes()
    suite = ET.fromstring(xml).find("testsuite")
    if (
        suite is None
        or int(code) != 1
        or suite.attrib["tests"] != "2"
        or suite.attrib["failures"] != "1"
        or suite.attrib["errors"] != "0"
        or len(plugins[2]) != 1
        or len(plugins[2][0].parts) != 2
    ):
        owner.fail(ValueError("actual pytest result/two-write genuine XML identity"))
    if b"owned stdout pass" not in b"".join(
        out.parts
    ) or b"owned stderr failure" not in b"".join(err.parts):
        owner.fail(ValueError("actual stdout/stderr retained"))
    composition.pathlib.rm_rf(native.CapPath(owner, "pytest-base"))
    if owner.fds or owner.first_fault:
        owner.fail(ValueError("pytest owned teardown/terminal fault"))
    return {
        "exit_code": int(code),
        "tests": 2,
        "intentional_failures": 1,
        "xml_source_parts": [len(part) for part in plugins[2][0].parts],
        "stdout_bytes": sum(map(len, out.parts)),
        "stderr_bytes": sum(map(len, err.parts)),
    }
