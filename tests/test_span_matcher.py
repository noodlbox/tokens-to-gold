"""STEP-1 must-reds: the native_floor span-aware offline scorer.

The native_floor (rg) comparator delivers SPANS (`file:span:a-b`), so the
name-based `match_gold` scores it as a total miss — every native_floor number
the pre-fix scorer produced was WRONG (a hard zero), not merely imprecise.
Nothing pre-fix reached any pin, fixture, page, or external surface; this suite
is what makes the span path correct and keeps it correct.

Teeth (the reviewer's six binding traps):
  (1) INDEPENDENCE — the harness recall is RECOMPUTED from row primitives via
      the production span matcher; the engine's `symbol_recall_by_k` is only the
      reference, never read as the harness value.
  (2) PER-ROW AND PER-K — parity is asserted for every row and every k, not on
      an aggregate.
  (3) NON-VACUITY — each report test counts its checks and asserts it made > 0.
  (4) PREDICATE — equality uses the shared 4dp `REPLAY_TOL`, the same tolerance
      `accept`/`check_arm` use.
  (5) BELOW ANY NEW TYPE — inputs are RAW strings, never a pre-built MatchResult.
  (6) NEGATIVE CONTROL — the permanent controls: name-based `match_gold` on
      spans matches NOTHING, and a span in the RIGHT file that does not overlap
      matches NOTHING.

Must-red witness: reverting the scorer's span-awareness (`_report_is_span_form`
-> always False, so `score_arm` falls back to `match_gold`) turns the go34
non-zero test RED; the matcher tests are red before `match_gold_spans` exists
(import) and are pinned forever by the permanent negative controls.
"""

from __future__ import annotations

import unittest
from pathlib import Path

from ttg.acceptance import REPLAY_TOL, score_arm
from ttg.matcher import match_gold, match_gold_spans
from ttg.report_io import load_report, result_rows

PKG = Path(__file__).resolve().parent.parent
CERTIFIED = PKG / "runs" / "recert-2026-09" / "certified"
FLOOR_REPORTS = {
    "ts40": CERTIFIED / "harbor-hermit-ts40py" / "reports" / "native_floor_ts40.json",
    "py_nosphinx": CERTIFIED
    / "harbor-hermit-ts40py"
    / "reports"
    / "native_floor_py_nosphinx.json",
    "go34": CERTIFIED / "quick-shrimp-go34rust43" / "reports" / "native_floor_go34.json",
    "rust43": CERTIFIED
    / "quick-shrimp-go34rust43"
    / "reports"
    / "native_floor_rust43.json",
}


def _gold_present(corpus: str) -> bool:
    return (PKG / "gold" / f"frozen_gold_{corpus}.json").is_file()


class SpanMatcherUnitTest(unittest.TestCase):
    """Must-red (a): the matcher, from RAW strings, with permanent controls."""

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

        # POSITIVE: the covering span claims the gold at rank 3, a head@10 hit.
        m = match_gold_spans(gold_keys, gold_ranges, retrieved)
        self.assertEqual(m.match_ranks, [3])
        self.assertEqual(m.recall_at(10), 1.0)
        self.assertEqual(m.recall_at(2), 0.0)  # not in the first two spans
        self.assertEqual(m.recall, 1.0)

        # PERMANENT NEGATIVE CONTROL (trap 6): the pre-fix name-based matcher
        # cannot see a span identity at all — it is a total miss. This is why
        # every pre-fix native_floor number was a hard zero.
        naive = match_gold(gold_keys, retrieved)
        self.assertEqual(naive.recall, 0.0)
        self.assertEqual(naive.recall_at(10), 0.0)

    def test_a_non_overlapping_span_in_the_right_file_does_not_match(self) -> None:
        # NEGATIVE CONTROL (trap 6): same file, but the span [40, 50] does not
        # overlap the gold range [10, 20] — no match.
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


class SpanParityTest(unittest.TestCase):
    """Must-red (b): PER-ROW, PER-K parity of the production span matcher against
    the engine's own `symbol_recall_by_k`, recomputed independently from the row
    primitives. Skips only when the certified report is not staged."""

    def _assert_parity(self, corpus: str) -> None:
        path = FLOOR_REPORTS[corpus]
        if not path.is_file():
            self.skipTest(f"certified native_floor report not staged: {path}")
        rows = result_rows(load_report(path))
        checked = 0
        for row in rows:
            gold_keys = [str(s) for s in (row.get("gold_symbols") or [])]
            gold_ranges = row.get("gold_symbol_ranges") or []
            retrieved = [str(s) for s in (row.get("retrieved_symbols") or [])]
            engine = row.get("symbol_recall_by_k") or {}
            if not gold_keys:
                continue
            # INDEPENDENCE (trap 1): recompute via the production span matcher
            # from the raw primitives; `symbol_recall_by_k` is the reference only.
            m = match_gold_spans(gold_keys, gold_ranges, retrieved)
            for k in (10, 25):
                eng = engine.get(str(k))
                if eng is None:
                    continue
                mine = m.recall_at(k)
                # PREDICATE (trap 4): shared 4dp tolerance, per row per k (trap 2).
                self.assertLess(
                    abs(mine - float(eng)),
                    REPLAY_TOL,
                    f"{corpus}/{row.get('instance_id')} k={k}: "
                    f"harness {mine:.6f} != engine {eng}",
                )
                checked += 1
        # NON-VACUITY (trap 3): the loop actually made checks.
        self.assertGreater(checked, 0, f"{corpus}: no (row, k) parity checks ran")

    def test_parity_go34(self) -> None:
        self._assert_parity("go34")

    def test_parity_rust43(self) -> None:
        self._assert_parity("rust43")

    def test_parity_ts40(self) -> None:
        self._assert_parity("ts40")

    def test_parity_py_nosphinx(self) -> None:
        self._assert_parity("py_nosphinx")


class FloorCellNonZeroTest(unittest.TestCase):
    """Must-red (c): the go34 native_floor cell scores NON-ZERO through the
    production `score_arm` seam. RED when the scorer is not span-aware (it falls
    back to `match_gold` and the whole floor cell collapses to 0.0)."""

    def test_go34_native_floor_cell_is_non_zero(self) -> None:
        path = FLOOR_REPORTS["go34"]
        if not (path.is_file() and _gold_present("go34")):
            self.skipTest("go34 native_floor report or frozen gold not staged")
        metrics = score_arm(load_report(path), "go34")
        self.assertGreater(metrics.reach_at_80, 0.0)
        self.assertGreater(metrics.whole_list_INTERNAL, 0.0)

    def test_all_staged_floor_cells_are_non_zero(self) -> None:
        checked = 0
        for corpus, path in FLOOR_REPORTS.items():
            if not (path.is_file() and _gold_present(corpus)):
                continue
            metrics = score_arm(load_report(path), corpus)
            self.assertGreater(
                metrics.whole_list_INTERNAL, 0.0, f"{corpus} floor collapsed to 0"
            )
            checked += 1
        self.assertGreater(checked, 0, "no floor cells staged to check")


if __name__ == "__main__":
    unittest.main()
