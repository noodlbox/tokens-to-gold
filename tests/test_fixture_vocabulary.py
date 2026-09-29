"""The V1 fixture's metric names translate to the current ones, and a check
that cannot find a headline metric refuses rather than skips (B64 lens H1)."""

from __future__ import annotations

import unittest

from ttg.acceptance import AcceptanceError, ArmMetrics, compare_metrics, fixture_arms, load_fixture


class FixtureVocabulary(unittest.TestCase):
    def test_the_real_fixture_translates_to_the_current_names(self) -> None:
        arm = fixture_arms(load_fixture())["ts40"]["shipped_treatment"]
        self.assertEqual(arm["gold_at_8k_ranked_list"], 0.789118)
        self.assertIn("gold_at_32k_ranked_list", arm)
        self.assertNotIn("gold_at_8k_wire", arm)

    def test_every_fixture_arm_carries_the_headline_metrics(self) -> None:
        for corpus, arms in fixture_arms(load_fixture()).items():
            for name, arm in arms.items():
                with self.subTest(corpus=corpus, arm=name):
                    self.assertIn("gold_at_8k_ranked_list", arm)

    def test_a_missing_headline_metric_refuses(self) -> None:
        got = ArmMetrics(n=1, head_only_at_10=0.0, head_only_at_25=0.0, gold_at_8k_ranked_list=0.5,
                         gold_at_32k_ranked_list=0.5, reach_at_80_whole_list=0.0,
                         reach_at_80_within_32k=0.0, whole_list_INTERNAL=0.5)
        with self.assertRaises(AcceptanceError):
            compare_metrics(got, {"n": 1, "gold_at_8k_wire": 0.5}, corpus="ts40")


if __name__ == "__main__":
    unittest.main()
