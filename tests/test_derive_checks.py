"""Derive-stage guard selftests (R-P5 zero-gold alarm, U2/R-B4 drift sidecar).

The alarm's whole job is to fire on the rust-OFF failure mode — a derivation
that produced almost no gold but still looks like a valid 0-coverage result —
so the boundary is pinned explicitly, and a missing instance must count as
zero-gold exactly like an empty one.
"""

from __future__ import annotations

import unittest

from ttg.derive_checks import (
    ZERO_GOLD_ALARM_RATE,
    drift_report,
    render_drift,
    zero_gold_check,
)


class ZeroGoldAlarmTest(unittest.TestCase):
    def test_healthy_tier_does_not_alarm(self) -> None:
        gold = {f"i{n}": ["a.py:alpha"] for n in range(38)}
        check = zero_gold_check("go34", gold, total_instances=40)
        self.assertEqual((check.with_gold, check.zero_gold), (38, 2))
        self.assertAlmostEqual(check.rate, 0.05)
        self.assertFalse(check.alarm)

    def test_rust_off_style_empty_derivation_alarms(self) -> None:
        # Every instance derived empty — a rust-OFF binary's signature.
        check = zero_gold_check("rust43", {}, total_instances=43)
        self.assertEqual(check.zero_gold, 43)
        self.assertEqual(check.rate, 1.0)
        self.assertTrue(check.alarm)
        self.assertIn("ALARM", check.summary())
        # the VERDICT lives in tier_disposition, not in the fact line
        self.assertNotIn("NO-GO", check.summary())

    def test_threshold_is_strictly_greater_than(self) -> None:
        # Exactly at the pre-registered rate is within budget; one more alarms.
        at = zero_gold_check("t", {f"i{n}": ["s"] for n in range(90)}, 100)
        self.assertAlmostEqual(at.rate, ZERO_GOLD_ALARM_RATE)
        self.assertFalse(at.alarm)
        over = zero_gold_check("t", {f"i{n}": ["s"] for n in range(89)}, 100)
        self.assertTrue(over.alarm)

    def test_missing_instance_counts_as_zero_gold_like_an_empty_one(self) -> None:
        empty = zero_gold_check("t", {"a": ["s"], "b": []}, 2)
        missing = zero_gold_check("t", {"a": ["s"]}, 2)
        self.assertEqual(empty.zero_gold, missing.zero_gold)
        self.assertEqual(empty.rate, missing.rate)

    def test_zero_corpus_is_rejected_not_divided_by(self) -> None:
        with self.assertRaises(ValueError):
            zero_gold_check("t", {}, 0)


class ErroredThirdClassTest(unittest.TestCase):
    """R-R43: errored is a third class, excluded from the zero-gold denominator.

    Counting an errored instance as zero-gold conflated a 5-repo analyzer
    indexing bug (rust43 coreutils) with a corpus property, inflating a 4.7%
    genuine rate to an 18.6% false alarm.
    """

    def test_one_errored_zero_zero_gold_does_not_alarm(self) -> None:
        # 1 errored + 0 scored-and-empty over 43 -> 0/42, must NOT alarm.
        gold = {f"i{n}": ["s"] for n in range(42)}  # 42 scored, all with gold
        check = zero_gold_check("rust43", gold, 43, frozenset({"err0"}))
        self.assertEqual(check.errored, 1)
        self.assertEqual(check.scored, 42)
        self.assertEqual(check.zero_gold, 0)
        self.assertFalse(check.alarm)
        self.assertIn("1 errored (excluded)", check.summary())

    def test_errored_plus_zero_gold_rate_is_over_total_minus_errored(self) -> None:
        # 6 errored + 2 zero-gold over 43 -> rate = 2/(43-6) = 2/37, within budget.
        gold = {f"i{n}": ["s"] for n in range(35)}  # 35 with gold
        errored = frozenset(f"e{n}" for n in range(6))
        check = zero_gold_check("rust43", gold, 43, errored)
        self.assertEqual((check.errored, check.scored, check.zero_gold), (6, 37, 2))
        self.assertAlmostEqual(check.rate, 2 / 37)
        self.assertFalse(check.alarm)

    def test_errored_does_not_change_a_no_error_tier(self) -> None:
        # go34's shape: 0 errored, 30 with gold, 34 total -> 4/34, unchanged.
        gold = {f"i{n}": ["s"] for n in range(30)}
        without = zero_gold_check("go34", gold, 34)
        withempty = zero_gold_check("go34", gold, 34, frozenset())
        self.assertEqual(without.zero_gold, 4)
        self.assertEqual(without.rate, withempty.rate)
        self.assertIn("4/34", without.summary())
        self.assertNotIn("errored", without.summary())

    def test_errored_gold_bearing_instance_is_not_double_counted(self) -> None:
        # Defensive: an id in BOTH gold and errored counts as errored only.
        gold = {"a": ["s"], "b": ["s"]}
        check = zero_gold_check("t", gold, 3, frozenset({"b"}))
        self.assertEqual(check.errored, 1)
        self.assertEqual(check.scored, 2)     # a + one empty
        self.assertEqual(check.with_gold, 1)  # only 'a'; 'b' excluded as errored
        self.assertEqual(check.zero_gold, 1)

    def test_all_errored_does_not_divide_by_zero(self) -> None:
        check = zero_gold_check("t", {}, 2, frozenset({"x", "y"}))
        self.assertEqual((check.scored, check.zero_gold, check.rate), (0, 0, 0.0))
        self.assertFalse(check.alarm)

    def test_more_errored_than_total_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            zero_gold_check("t", {}, 2, frozenset({"a", "b", "c"}))


class DriftSidecarTest(unittest.TestCase):
    def test_identical_derivation_is_clean(self) -> None:
        gold = {"a": ["f.py:x", "f.py:y"], "b": ["g.py:z"]}
        rep = drift_report("ts40", gold, dict(gold))
        self.assertTrue(rep.clean)
        self.assertEqual((rep.compared, rep.identical), (2, 2))
        self.assertIn("no drift", render_drift(rep))

    def test_symbol_order_is_not_drift(self) -> None:
        rep = drift_report("ts40", {"a": ["x", "y"]}, {"a": ["y", "x"]})
        self.assertTrue(rep.clean)

    def test_added_and_removed_symbols_are_reported_per_instance(self) -> None:
        rep = drift_report("ts40", {"a": ["x", "y"]}, {"a": ["y", "z"]})
        self.assertFalse(rep.clean)
        self.assertEqual(rep.drifted[0].added, ("z",))
        self.assertEqual(rep.drifted[0].removed, ("x",))
        text = render_drift(rep)
        self.assertIn("+ z", text)
        self.assertIn("- x", text)
        # the anchor is never replaced by the re-derivation
        self.assertIn("nothing re-frozen", text)

    def test_instances_only_on_one_side_are_surfaced(self) -> None:
        rep = drift_report("ts40", {"a": ["x"], "gone": ["q"]}, {"a": ["x"], "new": ["r"]})
        self.assertEqual(rep.only_frozen, ("gone",))
        self.assertEqual(rep.only_rederived, ("new",))
        self.assertFalse(rep.clean)

    def test_module_exposes_no_refreeze_path(self) -> None:
        # U2 is structural: drift can be reported, never written back.
        import ttg.derive_checks as m
        writers = [n for n in dir(m) if any(
            w in n.lower() for w in ("write", "freeze", "save", "dump"))]
        self.assertEqual(writers, [])


if __name__ == "__main__":
    unittest.main()
