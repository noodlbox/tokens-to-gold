"""Selftests for the homed `paired_stats.py` (R-P2).

Homed byte-identical from the m23gate harness (sha 4d359404…); V1 shipped
without it though C2 said it would. The regression report's per-metric
HELD/IMPROVED/REGRESSED verdict carries a paired bootstrap 95% CI and the exact
paired sign test from here, alongside the ±2.75 pp floor — the floor alone is
not an uncertainty statement.
"""

from __future__ import annotations

import unittest

from ttg.paired_stats import (
    BootstrapCI,
    SignTest,
    bootstrap_mean_ci,
    mean,
    sign_test,
)


class PairedStatsTest(unittest.TestCase):
    def test_sign_test_counts_and_direction(self) -> None:
        res = sign_test([0.05, 0.05, 0.0, -0.01])
        self.assertIsInstance(res, SignTest)
        self.assertEqual((res.up, res.down, res.ties), (2, 1, 1))
        self.assertTrue(0.0 <= res.p_value <= 1.0)

    def test_all_ties_is_p_one(self) -> None:
        res = sign_test([0.0, 0.0, 0.0])
        self.assertEqual((res.up, res.down), (0, 0))
        self.assertEqual(res.p_value, 1.0)

    def test_bootstrap_ci_brackets_a_positive_mean(self) -> None:
        deltas = [0.10, 0.12, 0.08, 0.11, 0.09]
        ci = bootstrap_mean_ci(deltas, iterations=2000, seed=1)
        assert ci is not None
        self.assertIsInstance(ci, BootstrapCI)
        self.assertLessEqual(ci.lower, ci.mean_delta)
        self.assertLessEqual(ci.mean_delta, ci.upper)
        self.assertTrue(ci.excludes_zero_positive())  # clean positive effect

    def test_mean_of_known_values(self) -> None:
        self.assertAlmostEqual(mean([1.0, 2.0, 3.0]), 2.0)


if __name__ == "__main__":
    unittest.main()
