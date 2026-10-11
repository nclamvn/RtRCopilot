"""Isolated synchronous file prototype. Actual campaign capture remains HOLD."""

import fcntl
import hashlib
import json
import os
import stat
import struct
import threading
import uuid
from pathlib import Path

CAP = 10485760
HEADER = struct.Struct(">BBII")
CLOSE = struct.Struct(">cBIQBc")
FINAL = struct.Struct(">cBBIIQc")
OWNER = struct.Struct(">8s16s16s32sQQ")
SEAL = struct.Struct(">8s32s32sQQ")
TERMINAL = 20 * CLOSE.size + FINAL.size
CONTROLS = OWNER.size + 2 * SEAL.size
IDS = (
    "frozen_copies", "literal_controls", "literal_scope", "launch_review", "journal",
    "final_samples", "summary_stdout", "load_stderr", "migration_streams", "owner_process",
    "supervisor_stop", "source_cap_child", "fixture", "database_admin", "disk",
    "reconstruction", "returncodes", "ephemeral", "future_observer", "outer_transcript",
)


class PacketError(ValueError):
    pass


def need(ok, message):
    if not ok:
        raise PacketError(message)


def sha(data):
    return hashlib.sha256(data).digest()


def safe(path):
    path = Path(path)
    need(path.is_absolute() and ".." not in path.parts and str(path) == path.as_posix(), "path")
    need(not any(p.is_symlink() for p in (path, *path.parents)), "symlink")
    home = Path(__file__).absolute().parent
    need(path != home and path.is_relative_to(home), "prototype path outside r26")
    return path


def limits(contract):
    need(type(contract["cap_bytes"]) is int and contract["cap_bytes"] == CAP
         and [f["id"] for f in contract["families"]] == list(IDS), "contract families/cap")
    result = {}
    for code, family in enumerate(contract["families"], 1):
        need(type(family["code"]) is int and family["code"] == code, "family code")
        variants = ["data", "framing"] if family["id"] == "future_observer" else ["data"]
        need([v["name"] for v in family["variants"]] == variants, "variants")
        for subtype, variant in enumerate(family["variants"], 1):
            n, length = variant["max_records"], variant["max_payload_bytes"]
            need(type(n) is int and 0 < n < 2**32 and type(length) is int
                 and 0 <= length <= CAP and type(variant["code"]) is int
                 and variant["code"] == subtype, "finite domain")
            result[(code, subtype)] = (n, length)
    need(sum(n * (length + 11) for n, length in result.values()) + TERMINAL + CONTROLS <= CAP,
         "aggregate")
    return result


def open_file(root_fd, name, flags):
    fd = os.open(name, flags | os.O_NOFOLLOW, 0o600, dir_fd=root_fd)
    try:
        need(stat.S_ISREG(os.fstat(fd).st_mode), "regular file")
    except BaseException:
        os.close(fd)
        raise
    return os.fdopen(fd, "r+b" if flags & os.O_RDWR else "rb", buffering=0)


def bounded(file, maximum):
    file.seek(0)
    data = file.read(maximum + 1)
    need(len(data) <= maximum and len(data) == os.fstat(file.fileno()).st_size, "file size")
    return data


def parse(data, rules):
    """Strict data/receipt/final grammar; does not infer SLA success from payload."""
    cursor, counts, sizes, next_seq, closed, payloads = 0, [0] * 20, [0] * 20, {}, set(), []
    while cursor < len(data):
        tag = data[cursor]
        if 1 <= tag <= 20:
            need(cursor + HEADER.size <= len(data), "truncated header")
            code, variant, seq, length = HEADER.unpack_from(data, cursor)
            key = (code, variant)
            need(key in rules and code not in closed, "unknown/closed record")
            maximum, max_length = rules[key]
            need(seq == next_seq.get(key, 0) and seq < maximum and length <= max_length, "sequence/domain")
            end = cursor + HEADER.size + length
            need(end < len(data) and data[end] == 10, "payload/suffix")
            payloads.append((IDS[code - 1], variant, seq, data[cursor + HEADER.size:end]))
            next_seq[key] = seq + 1
            counts[code - 1] += 1
            sizes[code - 1] += end + 1 - cursor
            cursor = end + 1
        elif tag == ord("C"):
            need(cursor + CLOSE.size <= len(data), "truncated receipt")
            _, code, count, size, zero, suffix = CLOSE.unpack_from(data, cursor)
            need(1 <= code <= 20 and code not in closed and suffix == b"\n", "duplicate/invalid receipt")
            need((count, size, zero) == (counts[code - 1], sizes[code - 1], int(count == 0)), "receipt snapshot")
            closed.add(code)
            cursor += CLOSE.size
        elif tag == ord("T"):
            need(cursor + FINAL.size == len(data), "terminal/trailing bytes")
            _, status, flags, mask, count, size, suffix = FINAL.unpack_from(data, cursor)
            need(status == flags == 0 and suffix == b"\n" and closed == set(range(1, 21))
                 and mask == (1 << 20) - 1 and count == sum(counts) and size == sum(sizes), "terminal proof")
            need(size <= CAP - TERMINAL - CONTROLS, "packet budget")
            return payloads
        else:
            raise PacketError("unknown frame")
    raise PacketError("missing terminal")


class Writer:
    def __init__(self, path, contract, contract_bytes, epoch, faults=None):
        self.path = safe(path)
        need(type(epoch) is bytes and len(epoch) == 16, "epoch identity")
        need(json.dumps(contract, sort_keys=True, allow_nan=False)
             == json.dumps(json.loads(contract_bytes), sort_keys=True, allow_nan=False), "contract bytes")
        self.rules = limits(contract)
        self.epoch, self.contract_sha = epoch, sha(contract_bytes)
        self.mutex, self.faults = threading.RLock(), dict(faults or {})
        self.closed, self.flags, self.finished = False, 0, False
        self.normal, self.terminal, self.control = 0, 0, OWNER.size
        self.next, self.counts, self.sizes, self.receipts = {}, [0] * 20, [0] * 20, set()
        self.root_fd = self.owner = self.packet = None
        try:
            self.path.mkdir(mode=0o700)
            self.root_fd = os.open(self.path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
            self.owner = open_file(self.root_fd, "owner.bin", os.O_RDWR | os.O_CREAT | os.O_EXCL)
            fcntl.flock(self.owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
            identity = os.fstat(self.root_fd)
            self.owner_bytes = OWNER.pack(b"R26OWN01", epoch, uuid.uuid4().bytes,
                                          self.contract_sha, identity.st_dev, identity.st_ino)
            self._write(self.owner, self.owner_bytes, "owner_write")
            self._sync(self.owner, "owner")
            self.packet = open_file(self.root_fd, "packet.bin", os.O_RDWR | os.O_CREAT | os.O_EXCL)
        except BaseException:
            self._close_descriptors()
            raise

    def _trip(self, stage):
        action = self.faults.pop(stage, None)
        if action == "raise":
            raise OSError("injected " + stage)
        return action

    def _write(self, file, data, stage):
        if self._trip(stage) == "short":
            file.write(data[:1])
            raise OSError("injected short " + stage)
        need(file.write(data) == len(data), "short write")

    def _sync(self, file, stage):
        self._trip(stage + "_flush")
        file.flush()
        self._trip(stage + "_fsync")
        os.fsync(file.fileno())

    def _active(self):
        # Immutable committed/abandoned epoch: later API misuse does no I/O or state change.
        need(not self.closed and not self.finished, "epoch closed; caller misuse")

    def _fail(self, message):
        self.flags |= 1
        raise PacketError(message)

    def emit(self, family, variant, payload, sequence=None):
        with self.mutex:
            self._active()
            if self.flags:
                raise PacketError("epoch already failed")
            if type(family) is not str or family not in IDS or type(variant) is not str:
                self._fail("family/variant")
            code = IDS.index(family) + 1
            subtype = 1 if variant == "data" else 2 if variant == "framing" else 0
            key = (code, subtype)
            if key not in self.rules or code in self.receipts or type(payload) is not bytes:
                self._fail("record domain/closed family")
            seq = self.next.get(key, 0) if sequence is None else sequence
            n, maximum = self.rules[key]
            if type(seq) is not int or seq != self.next.get(key, 0) or seq >= n or len(payload) > maximum:
                self._fail("sequence/count/length")
            frame = HEADER.pack(code, subtype, seq, len(payload)) + payload + b"\n"
            if self.normal + len(frame) > CAP - TERMINAL - CONTROLS:
                self._fail("aggregate overflow")
            self.normal += len(frame)
            self.next[key] = seq + 1
            self.counts[code - 1] += 1
            self.sizes[code - 1] += len(frame)
            try:
                self._write(self.packet, frame, "packet_write")
            except BaseException:
                self.flags |= 2
                raise
            return seq

    def close_family(self, family):
        with self.mutex:
            self._active()
            if type(family) is not str or family not in IDS or IDS.index(family) + 1 in self.receipts:
                self._fail("missing/duplicate family")
            code = IDS.index(family) + 1
            self.receipts.add(code)  # One attempt, including failed persistence; no reserve retry.
            count, size = self.counts[code - 1], self.sizes[code - 1]
            frame = CLOSE.pack(b"C", code, count, size, int(count == 0), b"\n")
            self.terminal += len(frame)
            try:
                self._write(self.packet, frame, "receipt_write")
            except BaseException:
                self.flags |= 2
                raise

    def finish(self):
        with self.mutex:
            self._active()
            self.finished = True
            if self.receipts != set(range(1, 21)):
                self.flags |= 1
            frame = FINAL.pack(b"T", int(bool(self.flags)), self.flags,
                               sum(1 << (c - 1) for c in self.receipts), sum(self.counts), self.normal, b"\n")
            self.terminal += len(frame)
            try:
                self._write(self.packet, frame, "final_write")
                self._sync(self.packet, "packet")
                need(not self.flags, "incomplete epoch; no seal")
                need(set(os.listdir(self.root_fd)) == {"owner.bin", "packet.bin"}, "bypass file")
                packet = bounded(self.packet, CAP - CONTROLS)
                parse(packet, self.rules)
                self.control += SEAL.size
                seal = SEAL.pack(b"R26SEAL1", sha(self.owner_bytes), sha(packet), len(packet), CAP)
                with open_file(self.root_fd, ".seal.tmp", os.O_RDWR | os.O_CREAT | os.O_EXCL) as file:
                    self._write(file, seal, "seal_write")
                    self._sync(file, "seal")
                self._trip("seal_commit")
                self.control += SEAL.size  # Live hardlink is independently charged before linking.
                os.link(".seal.tmp", "seal.bin", src_dir_fd=self.root_fd, dst_dir_fd=self.root_fd,
                        follow_symlinks=False)
                os.unlink(".seal.tmp", dir_fd=self.root_fd)
                self._trip("seal_dirsync")
                os.fsync(self.root_fd)
            except BaseException:
                self.flags |= 2
                self._unseal()  # If invalidation itself fails, retain lock until explicit abandon succeeds.
                raise
            self._close_descriptors()

    def _unseal(self):
        self._trip("invalidate")
        for name in ("seal.bin", ".seal.tmp"):
            try:
                os.unlink(name, dir_fd=self.root_fd)
            except FileNotFoundError:
                pass
        os.fsync(self.root_fd)

    def abandon(self):
        with self.mutex:
            if self.closed:
                return
            self.finished = True
            self._unseal()
            self._close_descriptors()

    def _close_descriptors(self):
        for file in (self.packet, self.owner):
            if file is not None:
                file.close()
        if self.root_fd is not None:
            os.close(self.root_fd)
        self.closed = True


def recover(path, contract, contract_bytes, epoch):
    path = safe(path)
    need(type(epoch) is bytes and len(epoch) == 16, "expected epoch")
    need(json.dumps(contract, sort_keys=True, allow_nan=False)
         == json.dumps(json.loads(contract_bytes), sort_keys=True, allow_nan=False), "contract bytes")
    rules = limits(contract)
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        with open_file(fd, "owner.bin", os.O_RDONLY) as owner:
            fcntl.flock(owner, fcntl.LOCK_SH | fcntl.LOCK_NB)
            need(set(os.listdir(fd)) == {"owner.bin", "packet.bin", "seal.bin"}, "unsealed/extra files")
            raw_owner = bounded(owner, OWNER.size)
            need(len(raw_owner) == OWNER.size, "owner framing")
            magic, actual_epoch, token, contract_sha, dev, ino = OWNER.unpack(raw_owner)
            identity = os.fstat(fd)
            need(magic == b"R26OWN01" and actual_epoch == epoch and token != bytes(16)
                 and contract_sha == sha(contract_bytes) and (dev, ino) == (identity.st_dev, identity.st_ino),
                 "owner/epoch/contract identity")
            with open_file(fd, "seal.bin", os.O_RDONLY) as seal_file:
                seal = bounded(seal_file, SEAL.size)
            need(len(seal) == SEAL.size, "seal framing")
            magic, owner_sha, packet_sha, size, cap = SEAL.unpack(seal)
            with open_file(fd, "packet.bin", os.O_RDONLY) as packet_file:
                packet = bounded(packet_file, CAP - CONTROLS)
            need(magic == b"R26SEAL1" and owner_sha == sha(raw_owner) and packet_sha == sha(packet)
                 and size == len(packet) and cap == CAP
                 and sum(os.stat(name, dir_fd=fd, follow_symlinks=False).st_size
                         for name in os.listdir(fd)) <= CAP, "seal/integrity/cap")
            records = parse(packet, rules)
            return {"prototype_complete": True, "records": records,
                    "stored_bytes": OWNER.size + SEAL.size + len(packet),
                    "actual_capture_admission": "HOLD", "power_loss_proved": False}
    finally:
        os.close(fd)
