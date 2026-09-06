"""accept-vs witness predicate: a re-run must reproduce a baseline to 4dp.

Tests compare_metrics DIRECTLY with synthetic ArmMetrics -- no report files, no
corpus, no skip-if-absent. The end-to-end exercise of accept-vs against real
reports is the lease's accept-witness stage; here we pin the PREDICATE so the
witness cannot silently weaken. REPLAY_TOL is 5e-05, so a 1e-3 move is caught
and a 1e-6 move is within tolerance.
"""

from __future__ import annotations

import unittest

from ttg.acceptance import ArmMetrics, compare_metrics

_BASE = ArmMetrics(
    n=37,
    head_only_at_10=0.0824,
    head_only_at_25=0.1368,
    gold_at_8k_wire=0.7891,
    gold_at_32k_wire=0.8893,
    reach_at_80_whole_list=0.7838,
    reach_at_80_within_32k=0.7838,
    whole_list_INTERNAL=0.8893,
)


def _expected(m: ArmMetrics) -> dict:
    return {**m.as_dict(), "n": m.n}


class CompareMetricsTest(unittest.TestCase):
    def test_identical_metrics_all_ok(self) -> None:
        checks = compare_metrics(_BASE, _expected(_BASE), corpus="ts40")
        self.assertTrue(checks)
        self.assertTrue(all(c.ok for c in checks), [c.metric for c in checks if not c.ok])

    def test_a_1e_3_perturbation_is_caught(self) -> None:
        # The must-red: 1e-3 > REPLAY_TOL (5e-05), so gold_at_8k_wire fails.
        perturbed = ArmMetrics(**{**_BASE.__dict__, "gold_at_8k_wire": 0.7891 + 1e-3})
        checks = compare_metrics(perturbed, _expected(_BASE), corpus="ts40")
        bad = [c for c in checks if not c.ok]
        self.assertEqual([c.metric for c in bad], ["gold_at_8k_wire"])

    def test_a_1e_6_perturbation_is_within_replay_tol(self) -> None:
        # 1e-6 < REPLAY_TOL: exact-to-4dp tolerates it (pins the tolerance).
        nudged = ArmMetrics(**{**_BASE.__dict__, "reach_at_80_whole_list": 0.7838 + 1e-6})
        checks = compare_metrics(nudged, _expected(_BASE), corpus="ts40")
        self.assertTrue(all(c.ok for c in checks))

    def test_a_changed_n_is_caught(self) -> None:
        smaller = ArmMetrics(**{**_BASE.__dict__, "n": 36})
        checks = compare_metrics(smaller, _expected(_BASE), corpus="ts40")
        n_check = next(c for c in checks if c.metric == "n")
        self.assertFalse(n_check.ok)


if __name__ == "__main__":
    unittest.main()
