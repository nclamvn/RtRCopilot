"""Five outer controls; nested intentional pytest failure is source evidence."""

from __future__ import annotations

import copy
import hashlib
import json
import os
import tempfile
from collections.abc import Iterator
from pathlib import Path
from typing import Callable, cast

import adapter
import flows
import genuine
import native
import policy
import pytest


fixture = cast(
    Callable[[Callable[[], Iterator[Path]]], Callable[[], Iterator[Path]]],
    pytest.fixture,
)


@fixture
def owned() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(
        prefix=".closure-lifecycle-", dir=policy.REFERENCE
    ) as name:
        yield Path(name)


def build(
    path: Path, faults: dict[str, tuple[str, bool]] | None = None
) -> tuple[native.Owner, genuine.Composition]:
    owner = native.Owner(path, faults)
    owner.prepare()
    return owner, genuine.Composition(owner)


def test_genuine_setup_body_cleanup_private_pytest(owned: Path) -> None:
    before = tempfile.tempdir
    owner, composition = build(owned / "genuine")
    try:
        result = flows.original(owner, composition)
        assert result["successful"] is True
        assert result["genuine_doCleanups_results"] == [True]
        nested = flows.pytest_flow(owner, composition)
        assert nested["exit_code"] == 1
        assert nested["intentional_failures"] == 1
        assert owner.first_fault is None and not owner.fds
        result_recovery = owner.finish()
        assert native.recover(owner.root) == result_recovery
        assert result_recovery["actual_capture_admission"] == "HOLD"
        assert (
            sum(f["requested"] for f in owner.frames if f["role"] == "synthetic_input")
            == 733169
        )
        assert len([f for f in owner.frames if f["role"] == "synthetic_input"]) == 35
        assert owner.attempts <= 512 and len(owner.events) <= 192
        assert len(policy.canonical(owner.metadata())) <= policy.META
        assert owner.charge <= 2725881
        assert any(
            e["op"] == "unlink" and str(e["path"]).endswith("test_owned_passcurrent")
            for e in owner.events
        )
        assert any(
            e["op"] == "rmdir" and str(e["path"]).endswith("test_owned_pass0")
            for e in owner.events
        )
        assert not any(n.startswith("pytest-base") for n in owner.directories)
        assert tempfile.tempdir == before
        print(
            json.dumps(
                {
                    "H2": result,
                    "H3": nested,
                    "bridge_attempts": owner.attempts,
                    "events": len(owner.events),
                    "identity_observations": len(owner.observations),
                    "metadata_bytes": len(policy.canonical(owner.metadata())),
                    "charge": owner.charge,
                    "physical_attempt_bytes": owner.physical,
                },
                sort_keys=True,
            )
        )
    finally:
        if not owner.closed:
            owner.abandon()


def test_genuine_probe_fallback_collision_permissions_finalizer(owned: Path) -> None:
    owner, composition = build(owned / "fallback", {"open": ("permission", True)})
    try:
        chosen = composition.tempfile.gettempdir()
        assert chosen == str(native.CapPath(owner, "candidates/tmp"))
        assert owner.first_fault is None
        assert len([f for f in owner.frames if f["mode"] == "create"]) == 2
        assert any(
            e.get("injected") is True and e["op"] == "open" for e in owner.events
        )
        native.recover(owner.root) if owner.closed else owner.finish()
    finally:
        if not owner.closed:
            owner.abandon()
    owner, composition = build(owned / "perms")
    try:
        directory = native.CapPath(owner, "controls")
        with pytest.raises(FileExistsError):
            directory.mkdir()
        owner.faults["mkdir"] = ("collision", True)
        temporary = composition.tempfile.TemporaryDirectory(
            prefix="owned-perms-", dir=str(directory)
        )
        path = owner.path(temporary.name) / "readonly.txt"
        path.write_bytes(b"real readonly native bytes\n")
        owner.change("chmod", path, 0o400)
        owner.faults["unlink"] = ("permission", True)
        temporary.cleanup()
        assert owner.first_fault is None
        assert any(e["op"] == "chflags" for e in owner.events)
        assert any(
            e["op"] == "chmod" and cast(list[object], e["args"])[0] == 0o700
            for e in owner.events
        )
        final = composition.tempfile.TemporaryDirectory(
            prefix="owned-finalizer-", dir=str(directory)
        )
        final._finalizer()
        assert not final._finalizer.alive
        assert owner.warning_count == 1
        owner.drain()
        recovery = owner.finish()
        assert recovery["stage"] == "LOCAL_NATIVE_LIFECYCLE"
        print(
            json.dumps(
                {
                    "H4_recoverable": "injected permission/mkdir collision; actual native fallback/create/write/chmod/chflags/delete; explicit genuine finalizer",
                    "events": len(owner.events),
                    "charge": owner.charge,
                }
            )
        )
    finally:
        if not owner.closed:
            owner.abandon()


def test_absorbing_short_write_genuine_cleanup_failure(owned: Path) -> None:
    read_owner, _ = build(owned / "read-fault")
    path = native.CapPath(read_owner, "controls/read.txt")
    path.write_bytes(b"preserved real read input")
    read_owner.faults["source_read"] = ("storage", False)
    with pytest.raises(OSError) as read_error:
        path.read_bytes()
    assert read_owner.first_fault is read_error.value
    assert (
        read_owner.files / "controls/read.txt"
    ).read_bytes() == b"preserved real read input"
    read_owner.abandon()
    assert not read_owner.fds and not (read_owner.root / "packet/seal.bin").exists()
    with pytest.raises(OSError, match="injected owner_write"):
        native.Owner(
            owned / "constructor-partial", {"constructor_packet": ("storage", False)}
        )
    assert not (owned / "constructor-partial").exists()
    for point in ("open_fstat", "close"):
        current, composition = build(owned / point, {point: ("storage", False)})
        with pytest.raises(OSError) as source_error:
            composition.tempfile.gettempdir()
        assert current.first_fault is not None and "injected " + point in str(
            current.first_fault
        )
        current.source_outcomes.append(
            {
                "producer": "genuine gettempdir",
                "source_exception": type(source_error.value).__name__,
                "source_text": str(source_error.value),
                "first_owner_fault": str(current.first_fault),
            }
        )
        assert current.fds
        current.abandon()
        assert not current.fds
        assert not (current.root / "packet/seal.bin").exists()
        assert any(e["op"] == "close" and e["error"] is None for e in current.events)
    current, composition = build(owned / "scandir")
    temporary = composition.tempfile.TemporaryDirectory(
        prefix="owned-scandir-", dir=str(native.CapPath(current, "controls"))
    )
    (current.path(temporary.name) / "data.txt").write_bytes(b"scandir actual file\n")
    current.faults["scandir"] = ("storage", False)
    with pytest.raises(OSError) as source_error:
        temporary.cleanup()
    assert current.first_fault is source_error.value and not current.fds
    assert any(
        e["op"] == "scandir" and e.get("injected") is True for e in current.events
    )
    assert any(e["op"] == "close" and e["error"] is None for e in current.events)
    first = current.first_fault
    for number in range(4):
        current.warning("retained terminal callback " + str(number), ResourceWarning)
    with pytest.raises(adapter.PacketError, match="four whole"):
        current.warning("fifth unadmitted callback", ResourceWarning)
    assert current.first_fault is first and current.warning_count == 4
    current.abandon()
    failure = json.loads((current.root / "manifest.json").read_bytes())
    assert len([e for e in failure["events"] if e["op"] == "warning"]) == 4

    owner, composition = build(owned / "short", {"write": ("short", False)})
    chosen = composition.tempfile.gettempdir()
    assert chosen == str(native.CapPath(owner, "candidates/TMPDIR"))
    assert owner.first_fault is not None
    first = owner.first_fault
    assert any(
        e["op"] == "write"
        and e["result"] == 1
        and e.get("native_requested") == 1
        and e.get("control") == ["short", False]
        for e in owner.events
    )
    assert any(f["requested"] == 4 for f in owner.frames)
    assert not owner.fds
    with pytest.raises(BaseException) as repeated:
        owner.finish()
    assert repeated.value is first
    owner.abandon()
    assert not (owner.root / "packet/seal.bin").exists()
    assert b"blat" in (owner.root / "packet/packet.bin").read_bytes()
    failure = json.loads((owner.root / "manifest.json").read_bytes())
    assert (
        failure["failure"]["first"]
        == "injected native-input truncation: source=4 native=1 returned=1"
    )

    owner, composition = build(owned / "cleanup", {"rmdir": ("storage", False)})
    outcome = flows.original(owner, composition)
    assert outcome["successful"] is False and outcome["genuine_doCleanups_results"] == [
        False
    ]
    assert len(cast(list[str], outcome["errors"])) == 1
    assert "injected rmdir" in cast(list[str], outcome["errors"])[0]
    assert (
        sum(f["requested"] for f in owner.frames if f["role"] == "synthetic_input")
        == 733169
    )
    assert not owner.fds and all(not getattr(f, "alive") for f in owner.finalizers)
    assert "injected rmdir" in cast(str, outcome["first_owner_fault"])
    assert any(
        "injected rmdir" in e for e in cast(list[str], outcome["cleanup_errors"])
    )
    owner.abandon()
    assert not (owner.root / "packet/seal.bin").exists()
    print(
        json.dumps(
            {
                "H4_short": "sliced-input control: source requested4, native input1, actual returned1; full source blat retained, not spontaneous OS short write",
                "H4_cleanup": outcome,
            },
            sort_keys=True,
        )
    )


def test_preadmitted_partial_xml_stream_failure_native_retention(owned: Path) -> None:
    owner, composition = build(
        owned / "producer-error", {"xml_source": ("after_first", False)}
    )
    with pytest.raises(OSError) as source_error:
        flows.pytest_flow(owner, composition)
    assert owner.first_fault is source_error.value
    assert "injected xml_source" in str(source_error.value)
    assert not owner.fds and not owner.capture_fds
    xml = owner.captures["reports/result.xml"]
    assert xml["accepted_bytes"] == 38
    assert cast(int, xml["bytes"]) > 38
    for name in ("reports/result.xml", "reports/stdout.txt", "reports/stderr.txt"):
        raw = b"".join(owner.buffers[name])
        assert (owner.files / name).read_bytes() == raw
        assert owner.captures[name]["completed"] is True
        assert owner.captures[name]["packet_key"] is None
    assert b"owned stdout pass" in (owner.files / "reports/stdout.txt").read_bytes()
    assert b"owned stderr failure" in (owner.files / "reports/stderr.txt").read_bytes()
    with pytest.raises(BaseException) as repeated:
        owner.finish()
    assert repeated.value is source_error.value
    owner.abandon()
    manifest = json.loads((owner.root / "manifest.json").read_bytes())
    retained = manifest["failure"]["outputs"]["reports/result.xml"]
    physical = (owner.files / "reports/result.xml").read_bytes()
    assert retained["requested"] == {
        "bytes": len(physical),
        "sha256": hashlib.sha256(physical).hexdigest(),
    }
    assert retained["native"]["bytes"] == len(physical)
    assert retained["source_accepted"] == {
        "bytes": 38,
        "sha256": hashlib.sha256(physical[:38]).hexdigest(),
    }
    assert not (owner.root / "packet/seal.bin").exists()
    print(
        json.dumps(
            {
                "H4_output_failure": "injected genuine second XML source write error, accepted38B vs whole requested raw retained",
                "source_error": str(source_error.value),
                "outputs": {
                    n: len(b"".join(parts)) for n, parts in owner.buffers.items()
                },
                "charge": owner.charge,
            },
            sort_keys=True,
        )
    )


def test_typed_recovery_tamper_and_pre_effect_domain_guards(owned: Path) -> None:
    owner, _ = build(owned / "recover")
    native.CapPath(owner, "controls/data.txt").write_bytes(b"typed real native bytes")
    owner.info(native.CapPath(owner, "controls/data.txt"))
    assert (
        native.CapPath(owner, "controls/data.txt").read_bytes()
        == b"typed real native bytes"
    )
    result = owner.finish()
    raw = (owner.root / "manifest.json").read_bytes()
    original = cast(dict[str, object], json.loads(raw))
    for case in (
        "role",
        "unowned",
        "fd_path",
        "inode",
        "permission",
        "ordinal",
        "missing_event",
        "boolean",
        "duplicate_dirs",
        "duplicate_observation",
        "stat_size",
        "read_size",
    ):
        altered = copy.deepcopy(original)
        frames = cast(list[native.Frame], altered["frames"])
        events = cast(list[dict[str, object]], altered["events"])
        if case == "role":
            frames[0]["role"] = "synthetic_input"
        elif case == "unowned":
            frames.clear()
        elif case == "fd_path":
            events[-1]["path"] = "controls/other.txt"
        elif case == "inode":
            cast(list[int], cast(dict[str, object], events[-1]["args"])["opened"])[
                1
            ] += 1
        elif case == "permission":
            cast(list[int], cast(dict[str, object], events[-1]["args"])["opened"])[
                2
            ] = 0
        elif case == "ordinal":
            events[-1]["ordinal"] = events[0]["ordinal"]
        elif case == "missing_event":
            events.pop(0)
        elif case == "boolean":
            frames[0]["seq"] = False
        elif case == "duplicate_dirs":
            cast(list[str], altered["directories"]).append("controls")
        elif case in {"stat_size", "read_size"}:
            observations = cast(dict[str, dict[str, object]], altered["observations"])
            observed = next(
                v for v in observations.values() if v["path"] == "controls/data.txt"
            )
            if case == "stat_size":
                cast(list[int], observed["result"])[3] += 1
            else:
                cast(list[list[int]], observed["reads"])[0][1] += 1
        else:
            observations = cast(dict[str, dict[str, object]], altered["observations"])
            observations["duplicate"] = copy.deepcopy(next(iter(observations.values())))
        with pytest.raises((adapter.PacketError, KeyError, TypeError)):
            native.roles(altered, result["records"])
    manifest_path = owner.root / "manifest.json"
    manifest_path.write_bytes(raw.replace(b'"LOCAL_NATIVE_LIFECYCLE"', b'"HTTP"'))
    with pytest.raises(adapter.PacketError):
        native.recover(owner.root)
    manifest_path.write_bytes(raw)
    assert native.recover(owner.root) == result
    held = owned / "held-native-root"
    alternate = owned / "alternate-root"
    alternate.mkdir()
    owner.files.rename(held)
    owner.files.symlink_to(alternate, target_is_directory=True)
    try:
        with pytest.raises(adapter.PacketError, match="before traversal"):
            native.recover(owner.root)
    finally:
        owner.files.unlink()
        held.rename(owner.files)
    assert native.recover(owner.root) == result
    actual = owner.files / "controls/data.txt"
    original_identity = actual.stat()
    payload = actual.read_bytes()
    actual.unlink()
    with pytest.raises(adapter.PacketError):
        native.recover(owner.root)
    actual.write_bytes(payload)
    replacement = actual.stat()
    assert (replacement.st_dev, replacement.st_ino, replacement.st_mode) != (
        original_identity.st_dev,
        original_identity.st_ino,
        original_identity.st_mode,
    )
    # Check actual replacement identity/mode rather than assuming inode allocation.
    with pytest.raises(adapter.PacketError):
        native.recover(owner.root)
    with pytest.raises(adapter.PacketError):
        stage = __import__("stage")
        pre_contract, pre_raw = cast(tuple[object, bytes], stage.contract())
        adapter.recover(
            owner.root / "packet", pre_contract, pre_raw, cast(bytes, stage.EPOCH)
        )

    actions: dict[str, Callable[[native.Owner, genuine.Composition], object]] = {
        "escape": lambda o, c: native.CapPath(o, "../../outside").read_bytes(),
        "bytes": lambda o, c: c.tempfile.mkdtemp(prefix=b"denied-"),
        "large": lambda o, c: native.CapPath(o, "controls/large.txt").write_bytes(
            b"x" * 4097
        ),
        "unknown": lambda o, c: native.CapPath(o, "unknown.txt").write_bytes(b"x"),
        "native_export": lambda o, c: os.fspath(native.CapPath(o, "controls")),
        "codec": lambda o, c: o.packet.emit("ephemeral", "data", b"x"),
        "unsupported_os": lambda o, c: getattr(o.os, "rename")("a", "b"),
    }
    for name, action in actions.items():
        current, composition = build(owned / name)
        initial = set(current.artifacts)
        with pytest.raises((adapter.PacketError, PermissionError, TypeError)):
            action(current, composition)
        assert set(current.artifacts) == initial
        assert not current.fds
        with pytest.raises(BaseException):
            current.finish()
        current.abandon()
    with pytest.raises(PermissionError):
        policy.deny_original_pre()

    escaping, _ = build(owned / "escaping")
    escaping.reserve_outputs()
    prefix = b'"\\' * 3500
    escaping.capture("reports/stdout.txt", prefix)
    with pytest.raises(adapter.PacketError, match="buffer ceiling") as oversized:
        escaping.capture("reports/stdout.txt", b"unadmitted" * 200)
    assert b"".join(escaping.buffers["reports/stdout.txt"]) == prefix
    escaping.abandon()
    snapshot = json.loads((escaping.root / "manifest.json").read_bytes())
    assert len(policy.canonical(snapshot)) <= policy.META
    retained = snapshot["failure"]["outputs"]["reports/stdout.txt"]
    assert retained["requested"] == {
        "bytes": len(prefix),
        "sha256": hashlib.sha256(prefix).hexdigest(),
    }
    assert retained["native"]["bytes"] == len(prefix)
    assert (escaping.files / "reports/stdout.txt").read_bytes() == prefix
    assert escaping.first_fault is oversized.value and escaping.closed
    assert not escaping.fds and escaping.meta_fd == -1
    assert not (escaping.root / "packet/seal.bin").exists()

    pressure, _ = build(owned / "metadata-pressure")
    pressure.reserve_outputs()
    pressure.capture("reports/stdout.txt", b"admitted prefix")
    diagnostic: dict[str, object] = {
        "control": "injected bounded metadata pressure, not producer output",
        "text": "",
    }
    pressure.source_outcomes.append(diagnostic)
    available = policy.META - 4096 - len(policy.canonical(pressure.failure_snapshot()))
    diagnostic["text"] = "x" * (available - 20)
    pressure.check_metadata()
    with pytest.raises(adapter.PacketError, match="prospective failure") as denied_meta:
        pressure.capture("reports/stdout.txt", b'"\\' * 100)
    assert b"".join(pressure.buffers["reports/stdout.txt"]) == b"admitted prefix"
    pressure.abandon()
    assert (pressure.files / "reports/stdout.txt").read_bytes() == b"admitted prefix"
    assert pressure.first_fault is denied_meta.value and pressure.closed
    assert not pressure.fds and pressure.meta_fd == -1
    assert (pressure.root / "manifest.json").stat().st_size <= policy.META
    assert not (pressure.root / "packet/seal.bin").exists()

    capacity, composition = build(owned / "capacity")
    capacity.reserve_outputs()
    temporary = composition.tempfile.TemporaryDirectory(
        prefix="owned-budget-", dir=str(native.CapPath(capacity, "controls"))
    )
    (capacity.path(temporary.name) / "data.txt").write_bytes(b"before budget denial\n")
    with pytest.raises(adapter.PacketError, match="cleanup reserve") as denied:
        while True:
            capacity.info(native.CapPath(capacity, "controls"))
    first = capacity.first_fault
    assert first is denied.value
    capacity.abandon()
    assert capacity.first_fault is first and not capacity.fds
    assert all(not getattr(f, "alive") for f in capacity.finalizers)
    assert capacity.attempts <= 512 and len(capacity.events) <= 192
    assert temporary.name not in {
        capacity.virtual + "/" + n for n in capacity.directories
    }
    assert not (capacity.root / "packet/seal.bin").exists()
    print(
        json.dumps(
            {
                "H1_H4_capacity": "natural bridge admission exhaustion with active preadmitted outputs/finalizer/file, genuine bounded cleanup still drained",
                "attempts_after_cleanup": capacity.attempts,
                "events": len(capacity.events),
                "selected_fd_peak": capacity.selected_fd_peak,
            },
            sort_keys=True,
        )
    )
