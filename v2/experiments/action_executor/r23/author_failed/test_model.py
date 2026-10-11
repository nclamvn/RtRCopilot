"""Six memory-only R23 controls. Synthetic counters are not runtime proof."""

import copy
import unittest

import model as m


def trace(slot):
    path = slot % 4
    mains = ((1, 1, 1), (4, 2, 2), (11, 3, 3)) if path < 2 else (
        ((1, 1, 1),) if path == 2 else ((1, 0, 1), (1, 0, 2), (4, 0, 3), (11, 0, 4)))
    windows = {key: (10 + index * 100, 100 + index * 100) for index, key in enumerate(mains)}
    records = []
    for phase, generation, context in m.PLANS[path]:
        key = phase, generation, context
        if key == (0, 0, 0):
            start, end = 0, 450
        elif key in windows:
            start, end = windows[key]
        else:
            parent = next(main for main in mains if main[1:] == key[1:])
            siblings = [child for child in m.PLANS[path] if child[1:] == parent[1:] and child != parent]
            start = windows[parent][0] + 1 + siblings.index(key) * 10
            end = start + 5
        base = dict(slot=slot, operation=path, path=path, phase=phase,
                    generation=generation, context=context, error=0)
        records += [dict(base, edge=0, us=start, outcome=0),
                    dict(base, edge=1, us=end, outcome=1)]
    return sorted(records, key=lambda e: (e["us"], e["edge"], e["phase"]))


class OfflineControls(unittest.TestCase):
    def test_closed_fixed_wire_domains_and_roundtrip(self):
        for slot in range(4):
            for event in trace(slot):
                wire = m.encode(event)
                self.assertEqual(len(wire), 32)
                self.assertEqual(m.decode(wire), event)
        for key, value in (("slot", True), ("us", m.MAX_US + 1), ("generation", 9),
                            ("outcome", "cancel"), ("path", 7)):
            bad = dict(trace(0)[0], **{key: value})
            with self.assertRaises(ValueError):
                m.encode(bad)
        with self.assertRaises(ValueError):
            m.encode(dict(trace(0)[0], token="forbidden"))
        rows = trace(2)
        for bad in (rows + [rows[0]], rows[1:], list(reversed(rows))):
            with self.assertRaises(ValueError):
                m.attribution(bad)
        with self.assertRaises(ValueError):
            m.attribution([dict(rows[0], generation=0)])

    def test_exact_reachable_worst_bytes_all_framing(self):
        events = [event for slot in range(m.SLOTS) for event in trace(slot)]
        wire = m.packet(events, "C" * m.SLOTS, (1599, 99))
        self.assertEqual(len(events), 40000)
        self.assertEqual(len(wire), m.budget()["observer_wire_bytes"])
        decoded, coverage = m.parse_packet(wire)
        self.assertEqual(decoded, events)
        self.assertEqual(coverage, "C" * m.SLOTS)
        for bad in (wire[:-1], wire.replace(b"END|40000", b"END|39999"),
                    wire.replace(b"R23P1", b"R23P2")):
            with self.assertRaises(ValueError):
                m.parse_packet(bad)
        bounds = {key: 524288 for key in m.budget()["original_components"]}
        self.assertEqual(m.budget(bounds)["capture_admission"], "HOLD")
        self.assertFalse(m.budget(bounds)["original_bounds_proved"])

    def test_nested_unions_residual_not_inclusive_sum(self):
        self.assertEqual(m.union([(1, 9), (2, 3), (7, 12), (15, 20)]), 16)
        for slot in range(4):
            result = m.attribution(trace(slot))
            self.assertEqual(result["state"], "C")
            self.assertEqual(result["child_union_us"] + result["unobserved_residual_us"], 450)
        rows = trace(0)
        mutation = next(e for e in rows if (e["phase"], e["edge"]) == (4, 0))
        mutation["us"] = 50
        rows.sort(key=lambda e: (e["us"], e["edge"]))
        with self.assertRaises(ValueError):
            m.attribution(rows)

    def test_error_cancel_incomplete_capacity_retained_or_rejected(self):
        for outcome, error, flag in ((2, 3, "F"), (3, 0, "F"), (4, 0, "I")):
            rows = trace(0)
            rows[-1].update(outcome=outcome, error=error)
            self.assertEqual(m.attribution(rows)["state"], flag)
            wire = m.packet(rows, flag + "N" * 1599, (0, 5))
            self.assertEqual(m.parse_packet(wire)[0], rows)
        rows = trace(0)[:-1]
        self.assertEqual(m.attribution(rows)["state"], "I")
        self.assertEqual(m.parse_packet(m.packet(rows, "I" + "N" * 1599, (0, 1)))[0], rows)
        over = trace(0) + [trace(0)[0]]
        before = copy.deepcopy(over)
        with self.assertRaises(ValueError):
            m.packet(over, "C" + "N" * 1599)
        self.assertEqual(over, before)  # No trim/drop/dedupe to meet the bound.

    def test_default_off_arguments_results_errors_and_restore_model_only(self):
        calls = []
        token = object()
        registry = {"policy_current_identity": token}
        def original(*args, **kwargs):
            calls.append((args, kwargs))
            return token
        for enabled in (False, True):
            self.assertIs(m.call_model(original, (token,), {"key": token}, registry,
                                       enabled=enabled), token)
            self.assertEqual(registry, {"policy_current_identity": token})
        self.assertEqual(calls[0], calls[1])
        class Cancel(BaseException):
            pass
        for error in (RuntimeError("synthetic"), Cancel()):
            def fail(error=error):
                raise error
            with self.assertRaises(type(error)) as caught:
                m.call_model(fail, (), {}, registry, enabled=True)
            self.assertIs(caught.exception, error)
            self.assertEqual(registry, {"policy_current_identity": token})
        for enabled in (False, True):
            registry = {"r23_model_observer": token}
            def effect():
                registry["original_effect"] = token
                return token
            self.assertIs(m.call_model(effect, (), {}, registry, enabled=enabled), token)
            self.assertEqual(registry, {"r23_model_observer": token, "original_effect": token})
            error = Cancel()
            def repeated_cancel():
                for _ in range(3):
                    calls.append("synthetic_cancel_delivery")
                registry["error_effect"] = token
                raise error
            with self.assertRaises(Cancel) as caught:
                m.call_model(repeated_cancel, (), {}, registry, enabled=enabled)
            self.assertIs(caught.exception, error)
            self.assertIs(registry["error_effect"], token)
            self.assertIs(registry["r23_model_observer"], token)

    def test_origin_trap_unknown_paths_and_no_fake_cancel_generations(self):
        flags = dict.fromkeys(m.ORIGIN_KEYS, True)
        self.assertTrue(m.origin_model(flags))
        for key in m.ORIGIN_KEYS:
            self.assertFalse(m.origin_model(dict(flags, **{key: False})))
        self.assertFalse(m.origin_model(dict(flags, unknown=True)))
        self.assertTrue(all(generation == 0 for _, generation, _ in m.PLANS[3]))
        self.assertLessEqual(max(2 * len(plan) for plan in m.PLANS.values()), 32)
        self.assertEqual(m.budget()["capture_admission"], "HOLD")


if __name__ == "__main__":
    unittest.main(verbosity=2)
