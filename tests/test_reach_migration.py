"""Reach-field migration — the clone-green UNIT half (GC1 fixture, GC3 synthetic,
GC4 grep). The scored gates (GC1-scored, GC2, GC3 discriminators, the floor
regression witness, the wire_curve path guard) need the certified reports and
live in the acceptance suite (`acceptance/test_certified.py`)."""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from ttg.acceptance import load_fixture, within_budget_reach
from ttg.matcher import match_gold

PKG = Path(__file__).resolve().parent.parent

# The pre-migration reach_at_80 values — the value-preserving rename target.
OLD_REACH = {
    ("shipped_treatment", "ts40"): 0.783784,
    ("levers_off_ablation", "ts40"): 0.216216,
    ("shipped_treatment", "py_nosphinx"): 0.897436,
    ("levers_off_ablation", "py_nosphinx"): 0.358974,
}


class GC1ValuePreservingRename(unittest.TestCase):
    """reach_at_80_whole_list carries the EXACT old reach_at_80 value (fixture)."""

    def test_fixture_whole_list_equals_old_reach(self) -> None:
        arms = load_fixture()["arms"]
        for (arm, corpus), old in OLD_REACH.items():
            with self.subTest(arm=arm, corpus=corpus):
                self.assertAlmostEqual(
                    arms[corpus][arm]["reach_at_80_whole_list"], old, places=6
                )


class GC3NonVacuity(unittest.TestCase):
    """The split is non-vacuous, proved from raw data: a 0.79 row counts for
    whole_list but NOT within_32k."""

    def test_synthetic_079_row_counts_whole_not_within(self) -> None:
        gold_ids = ["inst-1"]  # within_budget_reach keys by INSTANCE ID
        rows = {"inst-1": {"token_coverage_wire": {"by_budget": {"32000": 0.79}}}}
        self.assertEqual(within_budget_reach(rows, gold_ids), 0.0)  # 0.79 < 0.8
        at_bound = {"inst-1": {"token_coverage_wire": {"by_budget": {"32000": 0.80}}}}
        self.assertEqual(within_budget_reach(at_bound, gold_ids), 1.0)  # boundary counts
        self.assertEqual(match_gold(["pkg/f.py:a"], ["pkg/f.py:a"]).recall, 1.0)


class GC4NoBareReachAt80(unittest.TestCase):
    """No bare reach_at_80 survives anywhere (every use is _whole_list or
    _within_32k qualified). Excludes THIS file, which names the bare token."""

    def test_zero_bare_reach_at_80(self) -> None:
        pat = re.compile("reach_at_80(?!_whole_list|_within_32k)")
        offenders = []
        for base in ("ttg", "tests", "arms", "acceptance"):
            for f in (PKG / base).rglob("*"):
                if not f.is_file() or "__pycache__" in f.parts:
                    continue
                if f.suffix not in (".py", ".json") or f.name == Path(__file__).name:
                    continue
                for i, line in enumerate(f.read_text(errors="ignore").splitlines(), 1):
                    if pat.search(line):
                        offenders.append(f"{f.relative_to(PKG)}:{i}: {line.strip()}")
        self.assertEqual(offenders, [], offenders)


if __name__ == "__main__":
    unittest.main()
