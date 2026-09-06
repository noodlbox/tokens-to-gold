"""STEP-1 unit must-red: the native_floor span matcher, from RAW strings.

The parity, floor-cell, and non-zero tests (which need the certified reports)
live in the acceptance suite (`acceptance/test_certified.py`, run by
`reproduce.sh verify`). This file is the clone-green unit half: the matcher rule
and its permanent negative controls, exercised entirely from raw strings.
"""

from __future__ import annotations

import unittest

from ttg.matcher import match_gold, match_gold_spans


class SpanMatcherUnitTest(unittest.TestCase):
    """The matcher, from RAW strings, with permanent negative controls."""

    def test_covering_span_at_rank_3_is_a_head_at_10_hit(self) -> None:
        # RAW strings: one gold symbol at range [10, 20]; the covering span is the
        # THIRD retrieved item (rank 3), behind two non-covering spans.
        gold_keys = ["evaluator/functions.go:doSource"]
        gold_ranges = [[10, 20]]
        retrieved = [
            "evaluator/functions.go:span:100-200",  # rank 1 — no overlap
            "evaluator/functions.go:span:40-60",  # rank 2 — no overlap
            "evaluator/functions.go:span:15-30",  # rank 3 — overlaps [10, 20]
        ]
        m = match_gold_spans(gold_keys, gold_ranges, retrieved)
        self.assertEqual(m.match_ranks, [3])
        self.assertEqual(m.recall_at(10), 1.0)
        self.assertEqual(m.recall_at(2), 0.0)  # not in the first two spans
        self.assertEqual(m.recall, 1.0)

        # PERMANENT NEGATIVE CONTROL: the pre-fix name-based matcher cannot see a
        # span identity at all — it is a total miss (why every pre-fix
        # native_floor number was a hard zero).
        naive = match_gold(gold_keys, retrieved)
        self.assertEqual(naive.recall, 0.0)
        self.assertEqual(naive.recall_at(10), 0.0)

    def test_a_non_overlapping_span_in_the_right_file_does_not_match(self) -> None:
        # NEGATIVE CONTROL: same file, span [40, 50] does not overlap gold [10, 20].
        m = match_gold_spans(
            ["evaluator/functions.go:doSource"],
            [[10, 20]],
            ["evaluator/functions.go:span:40-50"],
        )
        self.assertEqual(m.match_ranks, [])
        self.assertEqual(m.recall, 0.0)

    def test_a_span_in_the_wrong_file_does_not_match(self) -> None:
        # Overlapping range but a DIFFERENT file — no match (files must be equal).
        m = match_gold_spans(
            ["evaluator/functions.go:doSource"],
            [[10, 20]],
            ["repl/repl.go:span:10-20"],
        )
        self.assertEqual(m.match_ranks, [])
        self.assertEqual(m.recall, 0.0)

    def test_one_span_claims_every_overlapping_gold_no_break(self) -> None:
        # A single wide span covers two adjacent gold symbols at once (no per-span
        # break); both are claimed at that span's rank.
        m = match_gold_spans(
            ["f.go:a", "f.go:b"],
            [[10, 20], [25, 40]],
            ["f.go:span:5-100"],
        )
        self.assertEqual(sorted(m.matched_gold_indices), [0, 1])
        self.assertEqual(m.match_ranks, [1, 1])
        self.assertEqual(m.recall, 1.0)


if __name__ == "__main__":
    unittest.main()
