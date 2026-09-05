"""R12 verdict-format selftests.

The load-bearing case is the identity check the design owner named: feeding a
reference report against ITSELF must yield HELD on every metric with the CI
strictly inside the ±2.75 pp floor band. If that ever fails, the verdict
machinery is manufacturing movement out of nothing.

The complementary cases prove the rule is decided by the CI relative to the
floor — not by the point estimate — so a big-but-noisy delta reads
INDETERMINATE rather than IMPROVED.
"""

from __future__ import annotations

import copy
import unittest

from ttg.regression import (
    DEFAULT_METRICS,
    NOISE_FLOOR_PP,
    Verdict,
    compare_reports,
    gold_at_budget,
    render_table,
    verdict_for,
)


def _report(per_instance: dict[str, float], reach80: dict[str, bool] | None = None):
    """A minimal report carrying the per-instance wire coverage the rollup reads."""
    reach80 = reach80 or {k: True for k in per_instance}
    return {
        "results": [
            {
                "instance_id": iid,
                "gold_symbols": ["a.py:alpha"],
                "token_coverage_wire": {
                    "by_budget": {"8000": cov, "32000": cov},
                    "tokens_to_coverage": ({"80": 5000} if reach80.get(iid) else {}),
                },
            }
            for iid, cov in sorted(per_instance.items())
        ]
    }


_BASE = _report({f"i{n}": 0.70 + (n % 5) * 0.03 for n in range(20)})


class IdentitySelftest(unittest.TestCase):
    def test_report_against_itself_is_held_with_ci_inside_the_floor(self) -> None:
        verdicts = compare_reports(_BASE, copy.deepcopy(_BASE), DEFAULT_METRICS)
        self.assertTrue(verdicts)
        for v in verdicts:
            self.assertEqual(v.verdict, Verdict.HELD, v.metric)
            self.assertEqual(v.mean_delta_pp, 0.0, v.metric)
            self.assertIsNotNone(v.ci)
            assert v.ci is not None
            self.assertGreaterEqual(v.ci.lower, -NOISE_FLOOR_PP)
            self.assertLessEqual(v.ci.upper, NOISE_FLOOR_PP)
            # every pair is a tie, so the sign test is vacuously p=1
            self.assertEqual((v.sign.up, v.sign.down), (0, 0))
            self.assertEqual(v.sign.p_value, 1.0)

    def test_table_renders_ci_and_sign_test_on_every_row(self) -> None:
        table = render_table(compare_reports(_BASE, copy.deepcopy(_BASE), DEFAULT_METRICS))
        self.assertIn("HELD", table)
        self.assertIn("95% CI", table)
        self.assertIn("sign test", table)
        self.assertIn(f"±{NOISE_FLOOR_PP:.2f} pp", table)


class VerdictRuleTest(unittest.TestCase):
    def test_uniform_drop_beyond_the_floor_is_regressed(self) -> None:
        worse = _report({f"i{n}": 0.70 + (n % 5) * 0.03 - 0.10 for n in range(20)})
        v = compare_reports(_BASE, worse, [gold_at_budget(8000)])[0]
        self.assertEqual(v.verdict, Verdict.REGRESSED)
        self.assertAlmostEqual(v.mean_delta_pp, -10.0, places=6)

    def test_uniform_gain_beyond_the_floor_is_improved(self) -> None:
        better = _report({f"i{n}": 0.70 + (n % 5) * 0.03 + 0.10 for n in range(20)})
        v = compare_reports(_BASE, better, [gold_at_budget(8000)])[0]
        self.assertEqual(v.verdict, Verdict.IMPROVED)

    def test_small_uniform_move_inside_the_floor_is_held(self) -> None:
        nudged = _report({f"i{n}": 0.70 + (n % 5) * 0.03 + 0.01 for n in range(20)})
        v = compare_reports(_BASE, nudged, [gold_at_budget(8000)])[0]
        self.assertEqual(v.verdict, Verdict.HELD)

    def test_large_but_noisy_delta_is_indeterminate_not_improved(self) -> None:
        # Mean is well past the floor, but the spread makes it indistinguishable:
        # the point estimate must NOT be allowed to decide.
        deltas = [+40.0, -30.0, +45.0, -28.0, +38.0, -25.0, +42.0, -20.0]
        v = verdict_for("noisy", deltas)
        self.assertGreater(v.mean_delta_pp, NOISE_FLOOR_PP)
        self.assertEqual(v.verdict, Verdict.INDETERMINATE)

    def test_empty_pairing_is_indeterminate(self) -> None:
        self.assertEqual(verdict_for("none", []).verdict, Verdict.INDETERMINATE)


if __name__ == "__main__":
    unittest.main()
