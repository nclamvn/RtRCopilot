"""Five new outer groups; original assertions inside G2 are not extra scenarios."""

from __future__ import annotations

import copy
import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import adapter
import derive
import pytest
import source_run
import stage
import writer
from host import HostPort


@pytest.fixture
def owned() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix=".closure-pre-stage-", dir=stage.REFERENCE) as name:
        yield Path(name)


def complete(root: Path) -> tuple[derive.StageOwnedBroker, derive.StageRecovery]:
    broker = derive.create_local_pre(root)
    with HostPort(broker) as port:
        session = source_run.run_original_corruption(port)
        assert len(session.attempts) == 35
        assert sum(len(raw) for _, raw in session.attempts) == 733169
        assert broker.charge == 1532863  # full source + fixed reserve, before closure91
        assert len(broker._tombstones) == 1
        assert sum(len(port.read(n)) for n, e in broker._entries.items() if e["exists"]) == 4050
        derive.cleanup(port)
        assert len(broker._tombstones) == 9
        assert len(broker._events) == 6
        assert broker.charge == 1532863
    return broker, broker.finish()


def test_whole_original_corruption_body_real_writer_and_cleanup(owned: Path) -> None:
    root = owned / "whole"
    broker, result = complete(root)
    assert derive.recover_pre(root) == result
    assert result["charge"] == broker.charge == 1532954
    assert result["physical_attempt_bytes"] == 733169
    assert result["native_files"] == 0
    assert len(result["records"]) == 36
    assert all(
        v == "synthetic_input" and owner
        for f, v, _, _, owner in result["semantic_records"]
        if f == "ephemeral"
    )
    assert result["stage"] == "PRE_LOCAL_CONTROL"
    assert result["actual_capture_admission"] == "HOLD"
    assert not any((root / "files").iterdir())


def test_path_variant_count_whole_and_cap_guards_before_artifact(owned: Path) -> None:
    for case in (
        "unknown",
        "large",
        "count",
        "variant",
        "direct",
        "native",
        "aggregate",
        "foreign",
        "metadata",
    ):
        root = owned / case
        broker = derive.create_local_pre(root)
        with HostPort(broker) as port:
            port.mkdir(stage.DIRECTORIES[-1], True, True)
            name = stage.PREFIX + "r21_http_e1/binding.json"
            initial = broker.charge
            with pytest.raises((adapter.PacketError, TypeError)) as error:
                if case == "unknown":
                    port.write("tmp/control/unknown", "ephemeral", b"x", "w")
                elif case == "large":
                    port.write(name, "ephemeral", b"x" * 19, "w")
                elif case == "count":
                    port.write(name, "ephemeral", b"x", "w")
                    port.write(name, "ephemeral", b"y", "w")
                    port.write(name, "ephemeral", b"z", "w")
                elif case == "variant":

                    def wrong_variant(owner: derive.StageOwnedBroker = broker) -> int:
                        return owner._writer.emit("ephemeral", "data", b"x")

                    port._call(wrong_variant)
                elif case == "direct":
                    port.record("ephemeral", b"x")
                elif case == "native":
                    os.fspath(source_run.StagePath(source_run.Session(port)))
                elif case == "foreign":
                    stale = writer.ProducerPath(broker, "foreign", name, "ephemeral")
                    broker._write(stale, b"x", "w")
                elif case == "metadata":
                    broker._source["fault-metadata"] = "x" * stage.METADATA
                    port.write(name, "ephemeral", b"x", "w")
                else:
                    broker._charge = adapter.CAP - 91
                    port.write(name, "ephemeral", b"x", "w")
            assert broker.first_fault is error.value
            with pytest.raises(BaseException) as repeated:
                port.check()
            assert repeated.value is error.value
            if case not in {"count", "aggregate"}:
                assert broker.charge == initial
            if case != "count":
                assert not (root / "files" / name).exists()
            if case == "foreign":
                assert broker._calls == {}
        with pytest.raises(adapter.PacketError):
            broker.finish()
        broker.abandon()
        assert not (root / "packet/seal.bin").exists()


def test_recovery_closed_roles_lifecycle_and_cross_stage(owned: Path) -> None:
    root = owned / "recover"
    _, result = complete(root)
    manifest = writer.mapping(json.loads((root / "manifest.json").read_bytes()))
    records = result["records"]
    cases = ("unknown", "unowned", "duplicate", "count", "events", "stage", "tombstones")
    for case in cases:
        forged = copy.deepcopy(manifest)
        altered = list(records)
        entries = writer.mapping(forged["files"])
        first = next(iter(entries))
        if case == "unknown":
            entries["tmp/control/unknown"] = entries.pop(first)
        elif case == "unowned":
            altered.append(("ephemeral", 1, 35, b"raw"))
        elif case == "duplicate":
            altered.append(altered[0])
        elif case == "count":
            writer.mapping(entries[first])["segments"] = []
        elif case == "events":
            forged["directory_events"] = []
        elif case == "stage":
            forged["stage"] = "HTTP"
        else:
            forged["tombstones"] = []
        with pytest.raises(adapter.PacketError):
            derive.roles(forged, altered)
    # Actual public paired recovery against deliberately corrupted owned disk;
    # post-seal adversarial edits are tests, not qualified producer output.
    for target in (root / "manifest.json", root / "packet/packet.bin", root / "packet/owner.bin"):
        saved = target.read_bytes()
        try:
            if target.name == "manifest.json":
                changed = copy.deepcopy(manifest)
                changed["stage"] = "HTTP"
                target.write_bytes(stage.canonical(changed))
            else:
                target.write_bytes(saved[:-1])
            with pytest.raises(adapter.PacketError):
                derive.recover_pre(root)
        finally:
            target.write_bytes(saved)
        assert derive.recover_pre(root) == result
    extra = root / "files/extra.bin"
    try:
        extra.write_bytes(b"external-tamper")
        with pytest.raises(adapter.PacketError):
            derive.recover_pre(root)
    finally:
        extra.unlink()
    missing = root / "packet/seal.bin"
    moved = root / "packet/seal.moved"
    missing.rename(moved)
    try:
        with pytest.raises(adapter.PacketError):
            derive.recover_pre(root)
    finally:
        moved.rename(missing)
    assert derive.recover_pre(root) == result
    with pytest.raises(adapter.PacketError):
        writer.recover(root)
    http = owned / "http"
    old = writer.Broker(http)
    old.finish()
    with pytest.raises(adapter.PacketError):
        derive.recover_pre(http)
    with pytest.raises(adapter.PacketError):
        derive.limits(json.loads(writer.BASE.read_bytes()))


def test_native_write_cleanup_source_fault_and_capability_sticky(owned: Path) -> None:
    for case in ("native_write", "native_delete", "native_rmdir", "path", "source"):
        root = owned / case
        broker = derive.create_local_pre(
            root, {case: "raise"} if case.startswith("native") else None
        )
        with HostPort(broker) as port:
            if case == "source":
                with (
                    patch.dict(stage.PINS, {"writer.py": "0" * 64}),
                    pytest.raises(adapter.PacketError) as error,
                ):
                    source_run.Session(port)
            elif case == "path":
                with pytest.raises(ValueError) as path_error:
                    source_run.StagePath(source_run.Session(port)) / "../../unknown"
                error_value: BaseException = path_error.value
            else:
                with pytest.raises(OSError) as native_error:
                    source_run.run_original_corruption(port)
                    derive.cleanup(port)
                error_value = native_error.value
            if case == "source":
                error_value = error.value
            assert broker.first_fault is error_value
            with pytest.raises(BaseException) as repeated:
                port.check()
            assert repeated.value is error_value
        with pytest.raises(adapter.PacketError):
            broker.finish()
        broker.abandon()
        assert not (root / "packet/seal.bin").exists()


def test_exact_contract_bounds_original_pre_predispatch_deny(owned: Path) -> None:
    contract, _ = stage.contract()
    assert sum(c for c, _ in stage.BOUNDS.values()) == 35
    payload = sum(c * n for c, n in stage.BOUNDS.values())
    assert payload == 1201440
    assert (
        2 * payload + 35 * 11 + stage.METADATA + adapter.TERMINAL + adapter.CONTROLS + 91 == 2469496
    )
    assert derive.limits(contract)[(18, 1)] == (35, 235440)
    with patch("subprocess.Popen") as spawn:
        for request in (None, True, {"approve": True}, {"entries": 139, "stage": "PRE"}):
            with pytest.raises(PermissionError):
                stage.dispatch_original_pre(request)
        spawn.assert_not_called()
    assert list(owned.iterdir()) == []
