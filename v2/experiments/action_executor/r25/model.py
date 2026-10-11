"""Synchronous memory-only proposal; no actual capture or durability authority."""

import struct

CAP = 10 * 1024 * 1024
IDS = (
    "frozen_copies", "literal_controls", "literal_scope", "launch_review", "journal",
    "final_samples", "summary_stdout", "load_stderr", "migration_streams", "owner_process",
    "supervisor_stop", "source_cap_child", "fixture", "database_admin", "disk",
    "reconstruction", "returncodes", "ephemeral", "future_observer", "outer_transcript",
)
HEADER = struct.Struct(">BBII")
CLOSE = struct.Struct(">cBIQBc")
FINAL = struct.Struct(">cBBIIQc")
RESERVE = 20 * CLOSE.size + FINAL.size
REJECT, OVERFLOW, STORAGE, CLEANUP, CLOSURE, BYPASS, MALFORMED, CRASH = (
    1, 2, 4, 8, 16, 32, 64, 128,
)


def require(condition, message):
    if not condition:
        raise ValueError(message)


def budget(contract):
    require(contract["schema"] == "R25-proposed-envelope-v1"
            and type(contract["cap_bytes"]) is int and contract["cap_bytes"] == CAP
            and contract["actual_capture_admission"] == "HOLD", "proposal boundary")
    for name, expected in (("record_header_bytes", HEADER.size), ("record_suffix_bytes", 1),
                           ("close_bytes", CLOSE.size), ("final_bytes", FINAL.size),
                           ("terminal_reserve_bytes", RESERVE)):
        require(type(contract[name]) is int and contract[name] == expected, "exact framing")
    require([f["id"] for f in contract["families"]] == list(IDS), "closed producer set/order")
    rows = []
    for index, family in enumerate(contract["families"], 1):
        require(type(family["code"]) is int and family["code"] == index, "family code")
        variants = family["variants"]
        expected = ["data", "framing"] if family["id"] == "future_observer" else ["data"]
        require([v["name"] for v in variants] == expected, "closed variants")
        size, count = 0, 0
        for code, variant in enumerate(variants, 1):
            require(type(variant["code"]) is int and variant["code"] == code, "variant code")
            n, length = variant["max_records"], variant["max_payload_bytes"]
            require(type(n) is int and 0 < n < 2**32 and type(length) is int
                    and 0 <= length <= CAP, "proposed finite domains")
            count += n
            size += n * (HEADER.size + length + 1)
        require(count < 2**32, "closure count serialization")
        rows.append({"family": family["id"], "max_records": count,
                     "encoded_upper_bytes": size, "classification": "proposed model only"})
    normal = sum(row["encoded_upper_bytes"] for row in rows)
    require(normal + RESERVE <= CAP, "proposed aggregate exceeds cap")
    return {"families": rows, "normal_upper_bytes": normal, "terminal_reserve_bytes": RESERVE,
            "total_model_upper_bytes": normal + RESERVE, "cap_bytes": CAP,
            "spare_bytes": CAP - normal - RESERVE, "actual_capture_admission": "HOLD",
            "actual_source_upper_bytes": None}


class Envelope:
    def __init__(self, contract):
        self.budget = budget(contract)
        self.rules = {(f["id"], v["name"]): (f["code"], v["code"], v["max_records"],
                                                v["max_payload_bytes"])
                      for f in contract["families"] for v in f["variants"]}
        self.next = dict.fromkeys(self.rules, 0)
        self.counts = dict.fromkeys(IDS, 0)
        self.bytes = dict.fromkeys(IDS, 0)
        self.receipts = {}
        self.charged = 0
        self.terminal_charged = 0
        self.frames = []
        self.flags = 0
        self.state = "OPEN"
        self.final_ack = False
        self.final_status = None

    def fault(self, flag):
        self.flags |= flag
        if self.state in ("TERMINAL", "CRASHED"):
            self.final_ack = False
        else:
            self.state = "INCOMPLETE"

    def _persist(self, frame, storage_ok, partial):
        if type(storage_ok) is not bool or type(partial) is not int or not 0 <= partial <= len(frame):
            self.fault(MALFORMED)
            return False
        if storage_ok:
            self.frames.append(frame)
            return True
        self.frames.append(frame[:partial])
        self.fault(STORAGE)
        return False

    def emit(self, family, variant, sequence, payload, *, storage_ok=True, partial=0):
        if type(family) is not str or type(variant) is not str:
            self.fault(MALFORMED)
            return False
        if self.state != "OPEN" or family in self.receipts:
            self.fault(CLOSURE)
            return False
        key = (family, variant)
        if key not in self.rules or type(sequence) is not int or type(payload) is not bytes:
            self.fault(MALFORMED)
            return False
        code, subtype, maximum, length = self.rules[key]
        if sequence != self.next[key] or sequence >= maximum:
            self.fault(REJECT)
            return False
        if len(payload) > length:
            self.fault(REJECT)
            return False
        frame = HEADER.pack(code, subtype, sequence, len(payload)) + payload + b"\n"
        if self.charged + len(frame) > CAP - RESERVE:
            self.fault(OVERFLOW)
            return False
        # Reserve the whole attempt before persistence; partial failures never refund it.
        self.charged += len(frame)
        self.next[key] += 1
        self.counts[family] += 1
        self.bytes[family] += len(frame)
        return self._persist(frame, storage_ok, partial)

    def close(self, family, *, storage_ok=True, partial=0):
        if type(family) is not str or family not in IDS or family in self.receipts \
                or self.state in ("TERMINAL", "CRASHED"):
            self.fault(CLOSURE)
            return False
        count, size = self.counts[family], self.bytes[family]
        frame = CLOSE.pack(b"C", IDS.index(family) + 1, count, size, int(count == 0), b"\n")
        self.terminal_charged += len(frame)
        ack = self._persist(frame, storage_ok, partial)
        self.receipts[family] = (count, size, ack)
        return ack

    def bypass(self):
        # A declared bypass invalidates proof; this model cannot discover actual bypasses.
        self.fault(BYPASS)

    def crash(self):
        self.fault(CRASH)
        self.state = "CRASHED"
        self.final_ack = False

    def finish(self, *, cleanup_ok=True, storage_ok=True, partial=0):
        if self.state in ("TERMINAL", "CRASHED") or self.final_status is not None:
            self.fault(CLOSURE)
            return self.result()
        if type(cleanup_ok) is not bool or not cleanup_ok:
            self.fault(CLEANUP)
        if set(self.receipts) != set(IDS) or not all(r[2] for r in self.receipts.values()):
            self.fault(CLOSURE)
        complete = not self.flags
        mask = sum(1 << IDS.index(f) for f, r in self.receipts.items() if r[2])
        self.final_status = "COMPLETE_MODEL" if complete else "INCOMPLETE"
        frame = FINAL.pack(b"T", int(not complete), self.flags, mask, sum(self.counts.values()),
                           self.charged, b"\n")
        self.terminal_charged += len(frame)
        self.final_ack = self._persist(frame, storage_ok, partial)
        self.state = "TERMINAL"
        return self.result()

    def result(self):
        return {"model_complete": self.final_ack and self.final_status == "COMPLETE_MODEL"
                and not self.flags, "model_stop_acknowledged": self.final_ack
                and self.final_status == "INCOMPLETE", "flags": self.flags,
                "normal_charged_bytes": self.charged,
                "terminal_charged_bytes": self.terminal_charged,
                "stored_bytes": sum(map(len, self.frames)), "actual_capture_admission": "HOLD",
                "actual_durability_proved": False}
