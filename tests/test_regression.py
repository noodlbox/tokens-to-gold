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
    paired_deltas_pp,
    reach_at_coverage,
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


class IntentionToTreatTest(unittest.TestCase):
    """R-R1: an instance that errors on the new binary must count 0 against
    EVERY metric, not vanish from some and score 0 in others.

    Dropping it would let a binary raise its Gold@B average by failing outright
    on its hardest instances — the average improves because the hard cases left
    the denominator."""

    _BASIS = ["ok", "errored"]

    def _base(self):
        row = {
            "gold_symbols": ["a.py:alpha"],
            "token_coverage_wire": {
                "by_budget": {"8000": 0.90, "32000": 0.90},
                "tokens_to_coverage": {"80": 5000},
            },
        }
        return {"results": [dict(row, instance_id=i) for i in self._BASIS]}

    def _current_missing_errored(self):
        base = self._base()
        return {"results": [r for r in base["results"] if r["instance_id"] == "ok"]}

    def test_errored_instance_stays_in_every_metric(self) -> None:
        verdicts = compare_reports(
            self._base(), self._current_missing_errored(), DEFAULT_METRICS, self._BASIS)
        for v in verdicts:
            self.assertEqual(v.n, 2, f"{v.metric} dropped the errored instance")
            self.assertEqual(v.n_missing_current, 1, v.metric)
            self.assertEqual(v.n_missing_baseline, 0, v.metric)

    def test_errored_instance_scores_zero_not_omitted(self) -> None:
        # baseline 0.90 -> missing scores 0.0, i.e. a -90pp delta on that pair.
        paired = paired_deltas_pp(
            self._base(), self._current_missing_errored(),
            gold_at_budget(8000)[1], self._BASIS)
        self.assertEqual(len(paired.deltas), 2)
        self.assertIn(-90.0, [round(d, 6) for d in paired.deltas])

    def test_gold_and_reach_treat_a_fieldless_row_identically(self) -> None:
        # A row present but carrying no wire block: both metrics must call it
        # MISSING and score 0 — previously Gold skipped it and reach scored 0.
        base = self._base()
        current = {"results": [
            dict(base["results"][0]),
            {"instance_id": "errored", "gold_symbols": ["a.py:alpha"]},
        ]}
        for _, value in (gold_at_budget(8000), reach_at_coverage(80)):
            paired = paired_deltas_pp(base, current, value, self._BASIS)
            self.assertEqual(len(paired.deltas), 2)
            self.assertEqual(paired.n_missing_current, 1)

    def test_union_pairing_keeps_instances_absent_from_one_side(self) -> None:
        # Without an explicit basis the pairing set is the UNION, so nothing
        # silently disappears just by being absent from one report.
        paired = paired_deltas_pp(
            self._base(), self._current_missing_errored(), gold_at_budget(8000)[1])
        self.assertEqual(len(paired.deltas), 2)

    def test_missing_counts_are_rendered(self) -> None:
        table = render_table(compare_reports(
            self._base(), self._current_missing_errored(), DEFAULT_METRICS, self._BASIS))
        self.assertIn("missing (base/cur)", table)
        self.assertIn("0/1", table)


if __name__ == "__main__":
    unittest.main()
