"""R-G4: an alarm is NO-GO for the tier that alarmed, never for the run.

The must-red the ruling asks for: one tier alarms while the others complete.
Before the per-tier gate, a single alarming tier aborted the whole run under
set -e -- discarding the remaining tiers' derivations and every arm run. These
tests pin the per-tier semantics so that cannot come back.
"""

from __future__ import annotations

import unittest

from ttg.derive_checks import (
    RULED_ALARM_EXCEPTIONS,
    Disposition,
    tier_disposition,
    zero_gold_check,
)


def _check(corpus: str, with_gold: int, total: int):
    return zero_gold_check(corpus, {f"i{n}": ["s"] for n in range(with_gold)}, total)


class TierGateTest(unittest.TestCase):
    def test_one_alarming_tier_does_not_condemn_the_others(self) -> None:
        # The fixture the ruling names: rust43 alarms with no ruling; every
        # other tier must still be publishable.
        tiers = [
            _check("ts40", 37, 40),        # 7.5%  within budget
            _check("py_nosphinx", 39, 40), # 2.5%  within budget
            _check("go34", 30, 34),        # 11.8% alarmed, RULED
            _check("rust43", 30, 43),      # 30%   alarmed, unruled
        ]
        verdicts = {c.corpus: tier_disposition(c) for c in tiers}

        self.assertEqual(verdicts["rust43"].disposition,
                         Disposition.NO_GO_PENDING_RULING)
        self.assertFalse(verdicts["rust43"].publishable)
        # ...and the run carries on: everything else still publishes.
        for corpus in ("ts40", "py_nosphinx", "go34"):
            self.assertTrue(verdicts[corpus].publishable, corpus)

    def test_within_budget_is_certified_without_a_ruling(self) -> None:
        v = tier_disposition(_check("py_nosphinx", 39, 40))
        self.assertEqual(v.disposition, Disposition.CERTIFIED)
        self.assertIsNone(v.ruling)

    def test_ruled_alarm_ships_disclosed_not_waived(self) -> None:
        v = tier_disposition(_check("go34", 30, 34))
        self.assertEqual(v.disposition, Disposition.CERTIFIED_WITH_DISCLOSURE)
        self.assertTrue(v.publishable)
        # the alarm is NOT suppressed: the rate and the cause both survive
        self.assertTrue(v.check.alarm)
        self.assertIn("11.8%", v.check.summary())
        self.assertIsNotNone(v.ruling)
        assert v.ruling is not None
        self.assertIn("new-file-dominated", v.ruling)

    def test_summary_does_not_contradict_a_ruled_disposition(self) -> None:
        v = tier_disposition(_check("go34", 30, 34))
        self.assertNotIn("until ruled", v.check.summary())

    def test_an_unruled_corpus_cannot_inherit_another_tiers_ruling(self) -> None:
        self.assertIn("go34", RULED_ALARM_EXCEPTIONS)
        v = tier_disposition(_check("some_new_tier", 10, 40))
        self.assertEqual(v.disposition, Disposition.NO_GO_PENDING_RULING)


if __name__ == "__main__":
    unittest.main()
