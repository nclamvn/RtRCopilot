"""Real private filesystem, opaque capability and prewrite/recovery controls."""

from __future__ import annotations

import os
import tempfile
import threading
from array import array
from collections.abc import Iterator
from pathlib import Path

import adapter
import broker as core
import pytest
from broker import METADATA, Broker, ProducerPath, recover

HERE = Path(__file__).absolute().parent


@pytest.fixture
def owned() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix=".broker-test-", dir=HERE) as temporary:
        yield Path(temporary)


def incomplete(broker: Broker, root: Path) -> None:
    with pytest.raises((ValueError, OSError)):
        broker.finish()
    assert not (root / "packet/seal.bin").exists()
    broker.abandon()


def test_binary_text_empty_overwrite_delete_recreate_and_copies(owned: Path) -> None:
    root = owned / "epoch"
    broker = Broker(root)
    directory = broker.path("temp")
    directory.mkdir()
    text = directory / "unicode"
    assert text.write_text("Đ") == 1
    assert text.read_text() == "Đ" and text.stat().st_size == 2
    text.write_text("")
    assert text.read_bytes() == b""
    text.write_bytes(b"before-delete")
    before = broker.charge
    text.unlink()
    assert not text.exists() and broker.charge == before
    text.write_bytes(b"recreated")
    copy = broker.path("copy", "journal")
    copy.write_bytes(text.read_bytes())
    with (directory / "empty").open("w"):
        pass
    view = memoryview(array("I", [16909060]))
    binary = directory / "view"
    with binary.open("wb") as stream:
        assert stream.write(view) == view.nbytes
    assert binary.read_bytes() == view.tobytes()
    result = broker.finish()
    assert (
        result["prototype_complete"]
        and result["physical_attempt_bytes"] == 2 + 13 + 9 + 9 + view.nbytes
    )
    assert result["charge"] > result["stored_bytes"]
    assert recover(root) == result
    payloads = [record[3] for record in result["records"]]
    assert b"before-delete" in payloads and b"recreated" in payloads and b"" in payloads
    old = (root / "files/temp/unicode").read_bytes()
    with pytest.raises(adapter.PacketError):
        text.unlink()
    assert (root / "files/temp/unicode").read_bytes() == old and recover(root) == result


def test_preio_domain_count_metadata_and_combined_cap(owned: Path) -> None:
    for scenario in ("domain", "count", "metadata"):
        root = owned / scenario
        broker = Broker(root)
        file = broker.path("kept", "journal")
        file.write_bytes(b"unchanged")
        if scenario == "count":
            for _ in range(3199):
                broker.record("journal", b"")
        elif scenario == "metadata":
            # Bounded owner fault seam grows declared metadata, not the physical payload.
            broker._source["m" * METADATA] = "0" * 64
        with pytest.raises(adapter.PacketError), file.open("wb") as port:
            port.write(b"x" * 513 if scenario == "domain" else b"changed")
        assert (root / "files/kept").read_bytes() == b"unchanged"
        incomplete(broker, root)
    root = owned / "aggregate"
    broker = Broker(root)
    broker.path("final", "final_samples").write_bytes(b"f" * 2097152)
    temp = broker.path("temporary", "ephemeral")
    for number in range(16):
        temp.write_bytes(bytes([number]) * 65536)
    journal = broker.path("journal", "journal")
    with journal.open("wb") as port:
        for _ in range(3200):
            port.write(b"j" * 512)
    before = (root / "files/journal").read_bytes()
    with pytest.raises(adapter.PacketError):
        for _ in range(4096):
            broker.record("load_stderr", b"x" * 512)
    assert broker.charge <= adapter.CAP and (root / "files/journal").read_bytes() == before
    incomplete(broker, root)


def test_opaque_cached_native_unsafe_foreign_and_closed_ports(owned: Path) -> None:
    for name in (
        "cached-open",
        "os-open",
        "foreign",
        "closed",
        "unsafe",
        "invalid-binary",
        "decode",
    ):
        root = owned / name
        broker = Broker(root)
        file = broker.path("raw", "journal")
        file.write_bytes(b"\xff")
        if name == "cached-open":
            cached = open
            with pytest.raises(adapter.PacketError):
                cached(file, "wb")
        elif name == "os-open":
            with pytest.raises(adapter.PacketError):
                os.open(file, os.O_WRONLY | os.O_TRUNC)
        elif name == "foreign":
            failures: list[BaseException] = []

            def work(file: ProducerPath = file, failures: list[BaseException] = failures) -> None:
                try:
                    file.write_bytes(b"foreign")
                except BaseException as error:
                    failures.append(error)

            thread = threading.Thread(target=work)
            thread.start()
            thread.join()
            assert len(failures) == 1 and isinstance(failures[0], adapter.PacketError)
        elif name == "closed":
            port = file.open("a")
            port.close()
            with pytest.raises(adapter.PacketError):
                port.write("late")
        elif name == "unsafe":
            with pytest.raises(adapter.PacketError):
                broker.path("../escape")
        elif name == "invalid-binary":
            # Runtime adversarial call through object-checked capability API.
            with pytest.raises(TypeError):
                file.write_bytes(7)
        else:
            with pytest.raises(UnicodeDecodeError):
                file.read_text()
        assert (root / "files/raw").read_bytes() == b"\xff"
        incomplete(broker, root)
    broker = Broker(owned / "ports")
    file = broker.path("raw", "journal")
    for _ in range(40):
        with file.open("w") as port:
            port.write("ok")
    assert not broker._handles
    broker.finish()


def test_storage_fault_reservations_cleanup_and_primary_identity(owned: Path) -> None:
    for fault in (
        "packet_write",
        "native_open",
        "native_write",
        "native_flush",
        "native_fsync",
        "manifest",
        "seal_commit",
    ):
        root = owned / fault
        action = "short" if fault in ("packet_write", "native_write") else "raise"
        broker = Broker(root, {fault: action})
        file = broker.path("raw", "journal")
        before = broker.charge
        with pytest.raises((OSError, adapter.PacketError)):
            if fault in ("manifest", "seal_commit"):
                file.write_bytes(b"whole")
                broker.finish()
            else:
                file.write_bytes(b"whole")
        assert broker.charge >= before and not (root / "packet/seal.bin").exists()
        broker.abandon()
    broker = Broker(owned / "primary")
    file = broker.path("raw", "journal")
    original = RuntimeError("original")
    with pytest.raises(RuntimeError) as caught, file.open("w") as port:
        port.write("raw")
        broker._faults["flush"] = "raise"
        raise original
    assert caught.value is original and isinstance(original.__cause__, OSError)
    incomplete(broker, owned / "primary")


def test_precommit_and_recovery_missing_extra_symlink_corruption(owned: Path) -> None:
    for corruption in ("extra", "missing", "raw", "symlink"):
        root = owned / ("pre-" + corruption)
        broker = Broker(root)
        file = broker.path("raw", "journal")
        file.write_bytes(b"exact")
        target = root / "files/raw"
        if corruption == "extra":
            (root / "extra").write_bytes(b"bypass")
        elif corruption == "missing":
            target.unlink()
        elif corruption == "raw":
            target.write_bytes(b"tamper")
        else:
            target.unlink()
            target.symlink_to(owned / "foreign")
        with pytest.raises(adapter.PacketError):
            broker.finish()
        assert not (root / "packet/seal.bin").exists()
        broker.abandon()
    for corruption in ("extra", "missing", "raw", "manifest", "oversize"):
        root = owned / ("sealed-" + corruption)
        broker = Broker(root)
        broker.path("raw", "journal").write_bytes(b"exact")
        broker.finish()
        if corruption == "extra":
            (root / "files/extra").write_bytes(b"bypass")
        elif corruption == "missing":
            (root / "files/raw").unlink()
        elif corruption == "raw":
            (root / "files/raw").write_bytes(b"tamper")
        elif corruption == "manifest":
            (root / "manifest.json").write_bytes(b"{}")
        else:
            with (root / "manifest.json").open("r+b") as native:
                native.truncate(METADATA + 1)
        with pytest.raises(adapter.PacketError):
            recover(root)


def test_immutable_boundary_and_foreign_token(owned: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    for field in ("BOUNDARY_SHA", "SCOPE_SHA"):
        root = owned / field
        with monkeypatch.context() as scoped:
            scoped.setattr(core, field, "0" * 64)
            with pytest.raises(adapter.PacketError, match="approved boundary/scope drift"):
                Broker(root)
            assert not root.exists()
    broker = Broker(owned / "foreign-token")
    wrong = ProducerPath(broker, "not-the-epoch", "raw", "journal")
    with pytest.raises(adapter.PacketError):
        wrong.write_bytes(b"foreign")
    incomplete(broker, owned / "foreign-token")
