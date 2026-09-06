"""Reach-field migration gates (GC1-GC4) + the wire_curve path guard.

reach@80 split into two qualified fields — `reach_at_80_whole_list` (uncapped)
and `reach_at_80_within_32k` (capped at the 32k wire budget). These are the
reviewer's four GC transcripts made permanent, plus a path-exercising guard for
the shared `wire_curve` helper.

Certified reports are REQUIRED, not skipped: a missing one FAILS LOUD naming the
fetch, so a green run is never a silently-empty one (fold F).
"""

from __future__ import annotations

import re
import unittest
from pathlib import Path

from ttg.acceptance import (
    REPLAY_TOL,
    load_fixture,
    load_frozen_gold,
    score_arm,
    within_budget_reach,
)
from ttg.matcher import match_gold
from ttg.report_io import load_report
from ttg.rollup import rollup

PKG = Path(__file__).resolve().parent.parent
_C = PKG / "runs" / "recert-2026-09" / "certified"
_HH = _C / "harbor-hermit-ts40py" / "reports"
_QS = _C / "quick-shrimp-go34rust43" / "reports"
CERT = {
    ("shipped_treatment", "ts40"): _HH / "shipped_treatment_ts40.json",
    ("levers_off_ablation", "ts40"): _HH / "levers_off_ablation_ts40.json",
    ("shipped_treatment", "py_nosphinx"): _HH / "shipped_treatment_py_nosphinx.json",
    ("levers_off_ablation", "py_nosphinx"): _HH / "levers_off_ablation_py_nosphinx.json",
    ("shipped_treatment", "go34"): _QS / "shipped_treatment_go34.json",
    ("shipped_treatment", "rust43"): _QS / "shipped_treatment_rust43.json",
    ("native_floor", "ts40"): _HH / "native_floor_ts40.json",
}

# The pre-migration reach_at_80 values — the value-preserving rename target.
OLD_REACH = {
    ("shipped_treatment", "ts40"): 0.783784,
    ("levers_off_ablation", "ts40"): 0.216216,
    ("shipped_treatment", "py_nosphinx"): 0.897436,
    ("levers_off_ablation", "py_nosphinx"): 0.358974,
}


def _require(test: unittest.TestCase, key: tuple[str, str]) -> Path:
    path = CERT[key]
    if not path.is_file():
        test.fail(
            f"required certified artifact absent: {path.relative_to(PKG)} — run "
            "reproduce.sh verify (fetch-artifacts) first; this gate does not skip"
        )
    return path


class GC1ValuePreservingRename(unittest.TestCase):
    """reach_at_80_whole_list carries the EXACT old reach_at_80 value."""

    def test_fixture_whole_list_equals_old_reach(self) -> None:
        arms = load_fixture()["arms"]
        for (arm, corpus), old in OLD_REACH.items():
            with self.subTest(arm=arm, corpus=corpus):
                self.assertAlmostEqual(
                    arms[corpus][arm]["reach_at_80_whole_list"], old, places=6
                )

    def test_scored_whole_list_reproduces_old_reach(self) -> None:
        for (arm, corpus), old in OLD_REACH.items():
            with self.subTest(arm=arm, corpus=corpus):
                m = score_arm(load_report(_require(self, (arm, corpus))), corpus)
                self.assertLess(abs(m.reach_at_80_whole_list - old), REPLAY_TOL)


class GC2WithinEqualsWholeOnShippedOnly(unittest.TestCase):
    """within_32k == whole_list ON THE SHIPPED ROWS ONLY — the capped arm.
    The ablation is uncapped and legitimately diverges (see GC3)."""

    def test_within_equals_whole_on_every_shipped_row(self) -> None:
        checked = 0
        for corpus in ("ts40", "py_nosphinx", "go34", "rust43"):
            with self.subTest(corpus=corpus):
                m = score_arm(
                    load_report(_require(self, ("shipped_treatment", corpus))), corpus
                )
                self.assertLess(
                    abs(m.reach_at_80_within_32k - m.reach_at_80_whole_list),
                    REPLAY_TOL,
                    f"shipped/{corpus}: within_32k != whole_list (capped => equal)",
                )
            checked += 1
        self.assertEqual(checked, 4)


class GC3NonVacuity(unittest.TestCase):
    """The split is non-vacuous: within_32k genuinely differs from whole_list.
    TWO discriminators — the span floor AND the uncapped ablation-py cell — must
    BOTH diverge, so dropping EITHER fails this; plus a synthetic 0.79 row."""

    def test_both_discriminators_diverge(self) -> None:
        divergent = []
        for label, (arm, corpus) in (
            ("floor/ts40", ("native_floor", "ts40")),
            ("ablation/py", ("levers_off_ablation", "py_nosphinx")),
        ):
            m = score_arm(load_report(_require(self, (arm, corpus))), corpus)
            if abs(m.reach_at_80_whole_list - m.reach_at_80_within_32k) > REPLAY_TOL:
                divergent.append(label)
        self.assertEqual(
            sorted(divergent),
            ["ablation/py", "floor/ts40"],
            "both discriminators must diverge; dropping either makes this fail",
        )

    def test_synthetic_079_row_counts_whole_not_within(self) -> None:
        # A row fully recalled offline (whole_list counts it) whose wire curve
        # covers only 0.79 at 32k (within_32k does NOT count it), from raw data.
        # within_budget_reach keys by INSTANCE ID (as score_arm calls it).
        gold_ids = ["inst-1"]
        rows = {"inst-1": {"token_coverage_wire": {"by_budget": {"32000": 0.79}}}}
        self.assertEqual(within_budget_reach(rows, gold_ids), 0.0)  # 0.79 < 0.8
        # the boundary: exactly 0.80 DOES count within-32k.
        at_bound = {"inst-1": {"token_coverage_wire": {"by_budget": {"32000": 0.80}}}}
        self.assertEqual(within_budget_reach(at_bound, gold_ids), 1.0)
        # and that same instance's WHOLE-LIST recall is a full hit (retrieved ==
        # gold), so whole_list counts it while within_32k (0.79) does not.
        self.assertEqual(match_gold(["pkg/f.py:a"], ["pkg/f.py:a"]).recall, 1.0)


class GC4NoBareReachAt80(unittest.TestCase):
    """No bare reach_at_80 survives anywhere (every use is _whole_list or
    _within_32k qualified). Excludes THIS file, which names the bare token in its
    own regex and docs."""

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


class WireCurvePathGuard(unittest.TestCase):
    """The shared wire_curve helper is BOUND and EXERCISED on the ablation path —
    a levers_off report driven through the rollup. RED (NameError) if the
    wire_curve import is dropped from rollup/acceptance; GREEN when bound."""

    def test_levers_off_through_rollup(self) -> None:
        report = load_report(_require(self, ("levers_off_ablation", "py_nosphinx")))
        roll = rollup(report, frozen_instance_ids=list(load_frozen_gold("py_nosphinx")))
        self.assertGreaterEqual(roll.binding.gold_at_budget[8000], 0.0)

    def test_ablation_within_32k_wire_curve_path(self) -> None:
        m = score_arm(
            load_report(_require(self, ("levers_off_ablation", "py_nosphinx"))),
            "py_nosphinx",
        )
        # The ablation is where within_32k (wire-curve) diverges from whole_list;
        # a non-trivial value here proves the wire_curve path actually ran.
        self.assertLess(m.reach_at_80_within_32k, m.reach_at_80_whole_list)


if __name__ == "__main__":
    unittest.main()
