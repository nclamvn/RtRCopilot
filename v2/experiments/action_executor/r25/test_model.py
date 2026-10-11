"""Memory-only records/faults; actual proposed JSON supplied by offline runner."""

import copy
import unittest
from model import CAP, CLOSE, FINAL, HEADER, IDS, RESERVE, Envelope, budget

CONTRACT = None


def closed(envelope):
    for family in IDS:
        envelope.close(family)
    return envelope


class EnvelopeControls(unittest.TestCase):
    def test_positive_exact_bytes_and_zero_receipts(self):
        model = Envelope(CONTRACT)
        raw = "raw diagnostic: é".encode()
        self.assertTrue(model.emit("load_stderr", "data", 0, raw))
        self.assertEqual(model.frames[0], HEADER.pack(8, 1, 0, len(raw)) + raw + b"\n")
        self.assertEqual(model.charged, len(raw) + 11)
        result = closed(model).finish()
        self.assertTrue(result["model_complete"])
        self.assertEqual(result["terminal_charged_bytes"], RESERVE)
        self.assertEqual(result["stored_bytes"], len(raw) + 11 + RESERVE)
        self.assertEqual(model.receipts["journal"], (0, 0, True))
        self.assertEqual(result["actual_capture_admission"], "HOLD")
        self.assertFalse(result["actual_durability_proved"])

    def test_full_proposed_budget_and_copies(self):
        model = Envelope(CONTRACT)
        for family in CONTRACT["families"]:
            for variant in family["variants"]:
                payload = b"x" * variant["max_payload_bytes"]
                for sequence in range(variant["max_records"]):
                    self.assertTrue(model.emit(family["id"], variant["name"], sequence, payload))
        result = closed(model).finish()
        expected = budget(CONTRACT)["total_model_upper_bytes"]
        self.assertEqual(result["stored_bytes"], expected)
        self.assertEqual(expected, 9778616)
        self.assertLess(expected, CAP)
        self.assertTrue(result["model_complete"])
        self.assertEqual(sum(r[0] for r in model.receipts.values()),
                         sum(v["max_records"] for f in CONTRACT["families"] for v in f["variants"]))
        # Journal/final/summary/stdout/live-file records are independently charged, not deduplicated.
        self.assertGreater(model.bytes["journal"], model.bytes["summary_stdout"])

    def test_missing_duplicate_and_closed_snapshot(self):
        model = Envelope(CONTRACT)
        model.close("journal")
        receipt = model.receipts["journal"]
        size = model.result()["stored_bytes"]
        self.assertFalse(model.emit("journal", "data", 0, b"late"))
        self.assertFalse(model.close("journal"))
        self.assertEqual(model.receipts["journal"], receipt)
        self.assertEqual(model.result()["stored_bytes"], size)
        self.assertFalse(model.finish()["model_complete"])
        other = closed(Envelope(CONTRACT))
        other.finish()
        size = other.result()["stored_bytes"]
        self.assertFalse(other.emit("load_stderr", "data", 0, b"late"))
        self.assertFalse(other.finish()["model_complete"])
        self.assertEqual(other.result()["stored_bytes"], size)
        self.assertFalse(other.close("journal"))
        self.assertEqual(other.result()["stored_bytes"], size)
        missing = Envelope(CONTRACT)
        missing.close("journal")
        result = missing.finish()
        self.assertFalse(result["model_complete"])
        self.assertTrue(result["model_stop_acknowledged"])

    def test_rejected_raw_saturation_and_bypass(self):
        cases = [("load_stderr", "data", 0, b"x" * 513),
                 ("missing", "data", 0, b"raw"), ("journal", "missing", 0, b"raw"),
                 ("journal", "data", True, b"raw"), ("journal", "data", 1, b"raw"),
                 ("journal", "data", 0, "not bytes"), ([], "data", 0, b"raw"),
                 ("journal", {}, 0, b"raw")]
        for args in cases:
            model = Envelope(CONTRACT)
            self.assertFalse(model.emit(*args))
            self.assertEqual(model.charged, 0)
            self.assertFalse(closed(model).finish()["model_complete"])
        model = Envelope(CONTRACT)
        model.emit("literal_scope", "data", 0, b"raw")
        size = model.charged
        self.assertFalse(model.emit("literal_scope", "data", 1, b"raw"))
        self.assertEqual(model.charged, size)
        self.assertFalse(closed(model).finish()["model_complete"])
        bypass = Envelope(CONTRACT)
        bypass.bypass()
        self.assertFalse(closed(bypass).finish()["model_complete"])

    def test_storage_cleanup_crash_and_reserve(self):
        model = Envelope(CONTRACT)
        self.assertFalse(model.emit("journal", "data", 0, b"raw", storage_ok=False, partial=2))
        self.assertEqual(model.charged, 14)
        self.assertEqual(model.result()["stored_bytes"], 2)
        self.assertFalse(closed(model).finish()["model_complete"])
        model = Envelope(CONTRACT)
        self.assertFalse(model.close("journal", storage_ok=False, partial=1))
        for family in IDS[0:4] + IDS[5:]:
            model.close(family)
        self.assertFalse(model.finish()["model_complete"])
        self.assertEqual(model.terminal_charged, RESERVE)
        for cleanup in (False, 1):
            self.assertFalse(closed(Envelope(CONTRACT)).finish(cleanup_ok=cleanup)["model_complete"])
        terminal = closed(Envelope(CONTRACT))
        result = terminal.finish(storage_ok=False, partial=1)
        self.assertFalse(result["model_complete"])
        self.assertFalse(result["model_stop_acknowledged"])
        uncertain = closed(Envelope(CONTRACT))
        result = uncertain.finish(storage_ok=False, partial=FINAL.size)
        self.assertFalse(result["model_complete"])
        self.assertFalse(result["model_stop_acknowledged"])
        self.assertEqual(len(uncertain.frames[-1]), FINAL.size)
        crashed = closed(Envelope(CONTRACT))
        crashed.crash()
        result = crashed.finish()
        self.assertFalse(result["model_complete"])
        self.assertFalse(result["model_stop_acknowledged"])
        self.assertLessEqual(result["terminal_charged_bytes"], RESERVE)
        before = result["stored_bytes"]
        crashed.bypass()
        self.assertFalse(crashed.close("journal"))
        self.assertFalse(crashed.finish()["model_complete"])
        self.assertEqual(crashed.state, "CRASHED")
        self.assertEqual(crashed.result()["stored_bytes"], before)
        for storage, partial in ((1, 0), (True, -1), (True, True), (True, 100000)):
            malformed = Envelope(CONTRACT)
            self.assertFalse(malformed.close("journal", storage_ok=storage, partial=partial))
            charged = malformed.terminal_charged
            self.assertFalse(malformed.close("journal"))
            self.assertEqual(malformed.terminal_charged, charged)
            self.assertFalse(closed(malformed).finish()["model_complete"])

    def test_contract_domains_cap_framing_and_families(self):
        for field, value in (("cap_bytes", CAP * 2), ("cap_bytes", float(CAP)),
                             ("terminal_reserve_bytes", RESERVE - 1),
                             ("record_header_bytes", HEADER.size - 1),
                             ("actual_capture_admission", "PASS")):
            data = copy.deepcopy(CONTRACT)
            data[field] = value
            with self.assertRaises(ValueError):
                budget(data)
        for families in (CONTRACT["families"][:-1], CONTRACT["families"] + CONTRACT["families"][:1]):
            with self.assertRaises(ValueError):
                budget(dict(CONTRACT, families=families))
        for n, length in ((True, 1), (1, True), (2**32, 1), (100000, CAP)):
            data = copy.deepcopy(CONTRACT)
            data["families"][0]["variants"][0].update(max_records=n, max_payload_bytes=length)
            with self.assertRaises(ValueError):
                budget(data)
        self.assertEqual((CLOSE.size, FINAL.size, RESERVE), (16, 20, 340))
