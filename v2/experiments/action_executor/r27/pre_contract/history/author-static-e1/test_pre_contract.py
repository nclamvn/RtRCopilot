"""Five real source diagnostic groups; never original six-test or PRE qualification."""

from __future__ import annotations

import os
import tempfile
import traceback
from collections.abc import Iterator
from pathlib import Path
from unittest.mock import patch

import adapter
import admission
import bridge
import pytest
from host import HostPort, OwnedBroker
from writer import recover

REFERENCE = bridge.HERE.parent / "real_path"


@pytest.fixture
def owned() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix=".closure-pre-contract-", dir=REFERENCE) as name:
        yield Path(name)


def incomplete(broker: OwnedBroker, root: Path) -> None:
    with pytest.raises(adapter.PacketError):
        broker.finish()
    assert not (root / "packet/seal.bin").exists()
    broker.abandon()


def test_genuine_whole_payloads_and_lifetime_source_quantification() -> None:
    result = admission.manifest()
    life = result["packet_lifetime"]
    assert isinstance(life, dict)
    assert (
        life["whole_write_attempts"],
        life["lifetime_payload_bytes"],
        life["final_live_payload_bytes"],
    ) == (35, 733169, 4050)
    assert result["execution_admission"] == "DENY"
    cases: tuple[tuple[bridge.Mode, tuple[int, int]], ...] = (
        ("full", (235440, 233840)),
        ("four", (582, 578)),
        ("one", (153, 152)),
    )
    for mode, sizes in cases:
        session = bridge.preview(mode)
        assert [len(a.raw) for a in session.attempts[3:5]] == list(sizes)
        assert len(session.attempts) == 9
        assert all(a.admitted for a in session.attempts)
        assert session.attempts[2].raw == bridge.preview(mode).attempts[2].raw


def test_original_full_and_four_whole_writes_reject_before_artifact(owned: Path) -> None:
    cases: tuple[tuple[bridge.Mode, bridge.Mapping, int, int], ...] = (
        ("full", "natural_diagnostic", 4, 4),
        ("four", "natural_diagnostic", 4, 4),
        ("full", "ephemeral_diagnostic", 3, 3),
    )
    for mode, mapping, accepted, index in cases:
        root = owned / (mode + "-" + mapping)
        broker = OwnedBroker(root)
        with HostPort(broker) as port:
            session = bridge.Session(port, mapping)
            before = broker.charge
            with pytest.raises(adapter.PacketError) as caught:
                session.invoke(mode)
            expected = bridge.preview(mode).attempts[index]
            assert session.attempts[-1].raw == expected.raw
            assert not session.attempts[-1].admitted
            assert sum(a.admitted for a in session.attempts) == accepted
            assert broker.first_fault is caught.value
            assert broker.charge == before + sum(
                2 * len(a.raw) + 11 for a in session.attempts if a.admitted
            )
            assert not (root / "files/tmp/control" / expected.name).exists()
            for a in session.attempts[:accepted]:
                assert (root / "files/tmp/control" / a.name).read_bytes() == a.raw
            frames = traceback.extract_tb(caught.value.__traceback__)
            assert any(
                f.filename.endswith("r21/test_r21_offline.py") and f.name == "write_packet"
                for f in frames
            )
        incomplete(broker, root)


def test_one_row_raw_fidelity_delete_overwrite_no_refund(owned: Path) -> None:
    root = owned / "one"
    broker = OwnedBroker(root)
    with HostPort(broker) as port:
        session = bridge.Session(port)
        packet = session.invoke("one")
        expected = bridge.preview("one")
        assert [(a.name, a.raw) for a in session.attempts] == [
            (a.name, a.raw) for a in expected.attempts
        ]
        for a in session.attempts:
            assert (bridge.LogicalTempPath(session) / a.name).read_bytes() == a.raw
        summary = packet / "run/latency-summary.json"
        saved = summary.read_bytes()
        initial = broker.charge
        summary.unlink()
        assert broker.charge == initial
        assert summary.write_bytes(saved) == len(saved)
        assert broker.charge == initial + 2 * len(saved) + 11
    result = broker.finish()
    assert recover(root) == result
    assert len(result["records"]) == 11  # nine original + overwrite + charged closure marker
    assert result["physical_attempt_bytes"] == sum(len(a.raw) for a in session.attempts)
    assert result["actual_capture_admission"] != "READY"
    second = owned / "repeat"
    broker = OwnedBroker(second)
    with HostPort(broker) as port:
        session = bridge.Session(port)
        session.invoke("one")
        binding = (second / "files/tmp/control/r21_http_e1/binding.json").read_bytes()
        with pytest.raises(adapter.PacketError):
            session.invoke("one")  # third frozen-copy attempt: no refund on overwrite
        assert (second / "files/tmp/control/r21_http_e1/binding.json").read_bytes() == binding
    incomplete(broker, second)


def test_source_unknown_native_and_storage_fault_sticky(owned: Path) -> None:
    for case in ("source", "path", "native", "storage"):
        root = owned / case
        broker = OwnedBroker(root, {"native_write": "raise"} if case == "storage" else None)
        with HostPort(broker) as port:
            session = bridge.Session(port)
            if case == "source":
                with (
                    patch.dict(bridge.PINS, {"r21/test_r21_offline.py": "0" * 64}),
                    pytest.raises(ValueError) as caught,
                ):
                    session.invoke("one")
            elif case == "path":
                with pytest.raises(ValueError) as caught:
                    (bridge.LogicalTempPath(session) / "unknown").write_bytes(b"raw")
            elif case == "native":
                with pytest.raises(TypeError) as caught:
                    os.open(bridge.LogicalTempPath(session), os.O_RDONLY)
            else:
                with pytest.raises(OSError) as caught:
                    session.invoke("one")
            assert broker.first_fault is caught.value
            with pytest.raises(BaseException) as again:
                port.check()
            assert again.value is caught.value
        incomplete(broker, root)


def test_predispatch_deny_never_creates_root_child_or_marker(owned: Path) -> None:
    with patch("subprocess.Popen") as spawn:
        for request in (None, True, {"approve": True}, {"entries": 192, "mapping": "ephemeral"}):
            with pytest.raises(PermissionError):
                admission.dispatch_pre(request)
        spawn.assert_not_called()
    assert list(owned.iterdir()) == []
    with patch.dict(bridge.PINS, {"r21/test_r21_envelope.py": "0" * 64}), pytest.raises(ValueError):
        admission.dispatch_pre(True)
