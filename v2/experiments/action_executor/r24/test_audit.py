"""Memory-only controls; no measured code or prior helper import."""

import copy
import unittest
from audit import CAP, SPEC, audit, fingerprint, historical_coverage, model_fit, parse, sha


def specimen():
    sources = {"source.py": sha(b"source")}
    fixed = {name: 5 for name, kind in SPEC.items() if kind == "fixed"}
    producers = [{"id": name, "classification": kind,
                  "max_bytes": fixed.get(name), "count_domain": "finite model count",
                  "byte_domain": "model domain", "assumptions": "not runtime proof",
                  "witnesses": [{"path": "source.py", "line": 1,
                                 "sha256": sources["source.py"]}],
                  "historical_files": [name], "historical_bytes": 0}
                 for name, kind in SPEC.items()]
    return {"schema": "R24-closed-producers-v1", "cap_bytes": CAP,
            "boundary": "memory specimen", "producers": producers}, fixed, sources


class AuditControls(unittest.TestCase):
    def test_positive_model_never_admits_capture(self):
        self.assertEqual(model_fit([b"a", b"bc"]),
                         {"model_bytes": 3, "model_fit": True, "capture_admission": "HOLD"})
        packet, fixed, sources = specimen()
        result = audit(packet, fixed, sources)
        self.assertIsNone(result["total_upper_bytes"])
        self.assertEqual(result["capture_admission"], "HOLD")
        self.assertEqual(result["fixed_subtotal_bytes"], 15)

    def test_missing_duplicate_unknown_producers(self):
        original, fixed, sources = specimen()
        observed = {name: 0 for name in SPEC}
        historical_coverage(original, observed)
        for change in ({}, dict(observed, invented=0), dict(observed, journal=1)):
            with self.assertRaises(ValueError):
                historical_coverage(original, change)
        variants = [original["producers"][:-1],
                    original["producers"] + [original["producers"][0]]]
        unknown = copy.deepcopy(original["producers"])
        unknown[0]["id"] = "invented"
        variants.append(unknown)
        for producers in variants:
            with self.subTest(producers=producers[-1]["id"]):
                packet = dict(original, producers=producers)
                with self.assertRaises(ValueError):
                    audit(packet, fixed, sources)

    def test_unproved_quantities_cannot_be_promoted(self):
        original, fixed, sources = specimen()
        for kind in ("fixed", "historical", "reserved", "proven"):
            packet = copy.deepcopy(original)
            packet["producers"][3].update(classification=kind, max_bytes=1)
            with self.assertRaises(ValueError):
                audit(packet, fixed, sources)
        for value in (1, True, 0.0):
            packet = copy.deepcopy(original)
            packet["producers"][3]["max_bytes"] = value
            with self.assertRaises(ValueError):
                audit(packet, fixed, sources)
        packet = copy.deepcopy(original)
        packet["producers"][0]["proof"] = "I prove it fits"
        with self.assertRaises(ValueError):
            audit(packet, fixed, sources)

    def test_domains_framing_and_types(self):
        for malformed in ('{"x":1,"x":2}', '{"x":NaN}', '{"x":Infinity}', '{'):
            with self.assertRaises(ValueError):
                parse(malformed)
        original, fixed, sources = specimen()
        changes = [("count_domain", ""), ("byte_domain", []), ("historical_bytes", True),
                   ("max_bytes", True), ("max_bytes", 4), ("witnesses", [])]
        for field, value in changes:
            packet = copy.deepcopy(original)
            packet["producers"][0][field] = value
            with self.assertRaises(ValueError):
                audit(packet, fixed, sources)
        packet = copy.deepcopy(original)
        packet["producers"][1]["historical_files"] = packet["producers"][0]["historical_files"]
        with self.assertRaises(ValueError):
            audit(packet, fixed, sources)
        packet = copy.deepcopy(original)
        packet["cap_bytes"] = float(CAP)
        with self.assertRaises(ValueError):
            audit(packet, fixed, sources)

    def test_changed_fingerprints_and_witnesses(self):
        fingerprint(b"source", sha(b"source"))
        with self.assertRaises(ValueError):
            fingerprint(b"changed", sha(b"source"))
        original, fixed, sources = specimen()
        for field, value in (("sha256", sha(b"changed")), ("path", "missing.py"),
                             ("line", True), ("line", 0)):
            packet = copy.deepcopy(original)
            packet["producers"][0]["witnesses"][0][field] = value
            with self.assertRaises(ValueError):
                audit(packet, fixed, sources)

    def test_cap_exceedance_and_numeric_models(self):
        with self.assertRaises(ValueError):
            model_fit([b"a" * (CAP + 1)])
        for payload in ([1], [True], ["bytes"], {"declared_max": 1}):
            with self.assertRaises(ValueError):
                model_fit(payload)
        packet, fixed, sources = specimen()
        fixed["frozen_copies"] = CAP + 1
        packet["producers"][0]["max_bytes"] = CAP + 1
        with self.assertRaises(ValueError):
            audit(packet, fixed, sources)


if __name__ == "__main__":
    unittest.main()
