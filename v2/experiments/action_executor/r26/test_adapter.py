"""Real local prototype files; fault injections are not power-cut certification."""

import hashlib
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from adapter import CAP, CLOSE, CONTROLS, FINAL, HEADER, IDS, OWNER, SEAL, TERMINAL, PacketError, Writer, recover

CONTRACT = None
CONTRACT_BYTES = None
HERE = Path(__file__).absolute().parent
EPOCH = bytes(range(16))


class FileControls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix=".r26-test-", dir=HERE)
        self.root = Path(self.temporary.name)
        self.writers = []

    def tearDown(self):
        for writer in self.writers:
            writer.abandon()
        self.temporary.cleanup()

    def writer(self, label="epoch", faults=None):
        writer = Writer(self.root / label, CONTRACT, CONTRACT_BYTES, EPOCH, faults)
        self.writers.append(writer)
        return writer

    def complete(self, writer):
        for family in IDS:
            writer.close_family(family)
        writer.finish()
        return recover(writer.path, CONTRACT, CONTRACT_BYTES, EPOCH)

    def rejects(self, path, epoch=EPOCH):
        with self.assertRaises((PacketError, OSError)):
            recover(path, CONTRACT, CONTRACT_BYTES, epoch)

    def snapshot(self, path):
        return {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in path.iterdir()}

    def test_real_roundtrip_raw_and_immutable_epoch(self):
        writer = self.writer()
        payload = b"raw\x00\xff\n" + "é".encode()
        writer.emit("load_stderr", "data", payload)
        result = self.complete(writer)
        self.assertEqual(result["records"], [("load_stderr", 1, 0, payload)])
        self.assertTrue(result["prototype_complete"])
        self.assertEqual(result["actual_capture_admission"], "HOLD")
        self.assertFalse(result["power_loss_proved"])
        before = self.snapshot(writer.path)
        for call in (lambda: writer.emit("load_stderr", "data", b"late"),
                     lambda: writer.close_family("journal"), writer.finish):
            with self.assertRaises(PacketError):
                call()
            self.assertEqual(self.snapshot(writer.path), before)
        self.assertTrue(recover(writer.path, CONTRACT, CONTRACT_BYTES, EPOCH)["prototype_complete"])
        self.assertEqual(writer.normal, len(payload) + 11)
        self.assertEqual(writer.terminal, TERMINAL)

    def test_exact_full_aggregate_and_control_reserve(self):
        writer = self.writer()
        for family in CONTRACT["families"]:
            for variant in family["variants"]:
                payload = b"x" * variant["max_payload_bytes"]
                for sequence in range(variant["max_records"]):
                    writer.emit(family["id"], variant["name"], payload, sequence)
        result = self.complete(writer)
        self.assertEqual(writer.normal + writer.terminal + writer.control, 9778616 + 264)
        self.assertEqual(CONTROLS, OWNER.size + 2 * SEAL.size)
        self.assertLessEqual(CONTROLS, 4096)
        self.assertLess(writer.normal + writer.terminal + writer.control, CAP)
        self.assertEqual(result["stored_bytes"], 9778616 + OWNER.size + SEAL.size)
        self.assertEqual(len(result["records"]), 48182)

    def test_input_closure_and_unsealed_crash_fail_closed(self):
        cases = [("journal", "data", b"x" * 513, None), ([], "data", b"x", None),
                 ("journal", {}, b"x", None), ("journal", "data", "not bytes", None),
                 ("journal", "data", b"x", True), ("journal", "data", b"x", 1)]
        for number, args in enumerate(cases):
            writer = self.writer(str(number))
            with self.assertRaises(PacketError):
                writer.emit(*args)
            with self.assertRaises(PacketError):
                self.complete(writer)
            writer.abandon()
            self.rejects(writer.path)
        for label, late in (("duplicate", False), ("late", True)):
            writer = self.writer(label)
            writer.close_family("journal")
            with self.assertRaises(PacketError):
                writer.emit("journal", "data", b"late") if late else writer.close_family("journal")
            with self.assertRaises(PacketError):
                writer.finish()
            writer.abandon()
            self.rejects(writer.path)
        writer = self.writer("saturated")
        writer.emit("literal_scope", "data", b"first")
        with self.assertRaises(PacketError):
            writer.emit("literal_scope", "data", b"second")
        writer.abandon()
        self.rejects(writer.path)
        crashed = self.writer("unsealed")
        crashed.emit("journal", "data", b"raw")
        crashed.abandon()  # Controlled descriptor release, not process-death/power-loss test.
        self.rejects(crashed.path)
        with self.assertRaises(PacketError):
            crashed.emit("journal", "data", b"retry")

    def test_real_write_flush_fsync_and_seal_faults(self):
        stages = ["owner_write", "owner_flush", "owner_fsync", "packet_write", "receipt_write",
                  "final_write", "packet_flush", "packet_fsync", "seal_write", "seal_flush",
                  "seal_fsync", "seal_commit", "seal_dirsync"]
        for number, stage in enumerate(stages):
            action = "short" if stage.endswith("write") else "raise"
            path = self.root / str(number)
            writer = None
            with self.subTest(stage=stage):
                with self.assertRaises((PacketError, OSError)):
                    writer = self.writer(str(number), {stage: action})
                    writer.emit("journal", "data", b"raw")
                    self.complete(writer)
                if writer:
                    self.assertLessEqual(writer.normal + writer.terminal + writer.control, CAP)
                    if stage == "packet_write":
                        self.assertEqual(writer.normal, 14)
                        self.assertEqual((path / "packet.bin").stat().st_size, 1)
                    writer.abandon()
                self.rejects(path)
        held = self.writer("uncertain-invalidation", {"seal_dirsync": "raise", "invalidate": "raise"})
        with self.assertRaises(OSError):
            self.complete(held)
        self.assertTrue((held.path / "seal.bin").exists())
        self.assertFalse(held.closed)
        self.rejects(held.path)  # Existing seal is insufficient while failed owner retains real flock.
        with self.assertRaises(AttributeError):
            held.release()  # No public escape hatch that drops failed-finalization ownership.
        self.rejects(held.path)
        held.abandon()  # Explicit cleanup succeeds after the injected one-shot invalidation failure.
        self.assertFalse((held.path / "seal.bin").exists())
        self.rejects(held.path)

    def test_ownership_stale_and_serialized_concurrency(self):
        writer = self.writer()
        self.rejects(writer.path)  # Real flock prevents recovery while writer owns epoch.
        with self.assertRaises(FileExistsError):
            self.writer()
        def emit(number):
            return writer.emit("load_stderr", "data", str(number).encode())
        with ThreadPoolExecutor(max_workers=8) as threads:
            sequences = list(threads.map(emit, range(80)))
        self.assertEqual(sorted(sequences), list(range(80)))
        result = self.complete(writer)
        self.assertEqual(sorted(int(row[3]) for row in result["records"]), list(range(80)))
        stale = self.writer("stale")
        stale.abandon()
        with self.assertRaises(FileExistsError):
            self.writer("stale")
        self.rejects(stale.path)
        bypass = self.writer("live-bypass")
        (bypass.path / "bypass.log").write_bytes(b"unowned writer")
        with self.assertRaises(PacketError):
            self.complete(bypass)
        bypass.abandon()
        self.rejects(bypass.path)

    def test_strict_recovery_corruption_and_identity(self):
        writer = self.writer()
        writer.emit("journal", "data", b"raw")
        self.complete(writer)
        original = {p.name: p.read_bytes() for p in writer.path.iterdir()}
        self.rejects(writer.path, bytes(16))
        for name in ("owner.bin", "seal.bin", "packet.bin"):
            path = writer.path / name
            for changed in (original[name][:-1], original[name] + b"extra",
                            bytes([original[name][0] ^ 1]) + original[name][1:]):
                path.write_bytes(changed)  # Deliberate bypass on owned test files.
                self.rejects(writer.path)
                path.write_bytes(original[name])
        (writer.path / "bypass.log").write_bytes(b"not accounted")
        self.rejects(writer.path)
        (writer.path / "bypass.log").unlink()
        moved = self.root / "moved"
        moved.mkdir()
        for name, data in original.items():
            (moved / name).write_bytes(data)
        self.rejects(moved)  # Owner binds actual directory device/inode, not just a caller token.
        # Re-sign test mutations to exercise grammar, not only seal digest detection.
        packet = original["packet.bin"]
        data_end = HEADER.size + 3 + 1
        variants = [packet[:data_end] + packet[:data_end] + packet[data_end:],
                    packet[:data_end] + packet[data_end + CLOSE.size:],
                    bytes([21]) + packet[1:], packet[:-FINAL.size], packet + packet[-FINAL.size:],
                    packet[:2] + (2).to_bytes(4, "big") + packet[6:],
                    packet[:6] + (999).to_bytes(4, "big") + packet[10:]]
        receipt = bytearray(packet); receipt[data_end + 2:data_end + 6] = (5).to_bytes(4, "big")
        variants.append(bytes(receipt))
        for changed in variants:
            (writer.path / "packet.bin").write_bytes(changed)
            seal = SEAL.pack(b"R26SEAL1", hashlib.sha256(original["owner.bin"]).digest(),
                             hashlib.sha256(changed).digest(), len(changed), CAP)
            (writer.path / "seal.bin").write_bytes(seal)
            self.rejects(writer.path)

    def test_unsafe_paths_and_contract_mismatch(self):
        link = self.root / "link"
        link.symlink_to(self.root, target_is_directory=True)
        with self.assertRaises(PacketError):
            Writer(link / "epoch", CONTRACT, CONTRACT_BYTES, EPOCH)
        with self.assertRaises(PacketError):
            Writer(self.root / ".." / "escape", CONTRACT, CONTRACT_BYTES, EPOCH)
        with self.assertRaises(PacketError):
            Writer(Path("/not-admitted-r26"), CONTRACT, CONTRACT_BYTES, EPOCH)
        writer = self.writer()
        self.complete(writer)
        packet = writer.path / "packet.bin"
        saved = packet.read_bytes(); packet.unlink(); packet.symlink_to(self.root / "foreign")
        self.rejects(writer.path)
        packet.unlink(); packet.write_bytes(saved)
        with self.assertRaises(PacketError):
            recover(writer.path, CONTRACT, CONTRACT_BYTES + b" ", EPOCH)
        with self.assertRaises(PacketError):
            Writer(self.root / "bad-contract", dict(CONTRACT, cap_bytes=CAP * 2), CONTRACT_BYTES, EPOCH)
        self.assertFalse((self.root / "bad-contract").exists())
