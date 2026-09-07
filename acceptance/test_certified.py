"""The ACCEPTANCE suite — every test that needs the certified arm reports.

Split out of `tests/` (A5): the unit suite (`tests/`) is green on any clone by
construction; THIS suite needs the certified reports and is run by
`reproduce.sh verify`, which fetches them first (`fetch-artifacts`) and FAILS
LOUDLY naming the fetch if they are absent — no skip-if-absent anywhere.

Report source: `TTG_REPORTS_DIR` (the fetched dir) when set, else the local
certified trees. Every access goes through `_require`, which fails loud.
"""

from __future__ import annotations

import os
import unittest
from pathlib import Path

from ttg.acceptance import (
    LOCKED_METRICS,
    REPLAY_TOL,
    check_report_file,
    load_fixture,
    load_frozen_gold,
    score_arm,
)
from ttg import privacy as _privacy
from ttg.curve_recompute import curve_parity_findings
from ttg.matcher import match_gold_spans
from ttg.report import _run_wire_stats
from ttg.report_io import (
    gold_bearing_rows,
    load_report,
    result_rows,
    wire_curve,
)
from ttg.rollup import Basis, rollup

PKG = Path(__file__).resolve().parent.parent
_ENV = os.environ.get("TTG_REPORTS_DIR")
_HH = PKG / "runs" / "recert-2026-09" / "certified" / "harbor-hermit-ts40py" / "reports"
_QS = PKG / "runs" / "recert-2026-09" / "certified" / "quick-shrimp-go34rust43" / "reports"
# The full-surface privacy scan resolves its certified surface the SAME way as
# `_report_path`: the fetched dir (`TTG_REPORTS_DIR`) on a clone — where the
# fetched attachments ARE the published surface — else the local certified trees.
# It must never hard-code the local certified path, which a clone never has
# (fold F: fail loud if the resolved surface is absent, never no-op).
_SURFACE = Path(_ENV) if _ENV else PKG / "runs" / "recert-2026-09" / "certified"

ARMS = ("shipped_treatment", "levers_off_ablation", "native_floor")
CORPORA = ("ts40", "py_nosphinx", "go34", "rust43")


def _report_path(arm: str, corpus: str) -> Path:
    if _ENV:
        return Path(_ENV) / f"{arm}_{corpus}.json"
    lease = _HH if corpus in ("ts40", "py_nosphinx") else _QS
    return lease / f"{arm}_{corpus}.json"


def _require(test: unittest.TestCase, arm: str, corpus: str) -> Path:
    path = _report_path(arm, corpus)
    if not path.is_file():
        test.fail(
            f"required certified report absent: {arm}_{corpus}.json (looked in "
            f"{path.parent}) — run `reproduce.sh verify` (fetch-artifacts) first"
        )
    return path


# Parity is counted BY REPORT ROW (rows-with-gold x 2 k); the gold-bearing reach
# n is named beside it. ts40 differs (39 report-gold rows vs n=37: the 47d29d7
# addendum). See tests/test_harness.py KNOWN_DRIFT for the same two ids.
EXPECTED_PARITY = {"ts40": 78, "py_nosphinx": 78, "go34": 60, "rust43": 80}
GOLD_BEARING_N = {"ts40": 37, "py_nosphinx": 39, "go34": 30, "rust43": 40}
OLD_REACH = {
    ("shipped_treatment", "ts40"): 0.783784,
    ("levers_off_ablation", "ts40"): 0.216216,
    ("shipped_treatment", "py_nosphinx"): 0.897436,
    ("levers_off_ablation", "py_nosphinx"): 0.358974,
}
KNOWN_DRIFT = {
    "ts40": {"effect-sse-httpapi-streaming", "query-persist-restored-query-state"},
    "py_nosphinx": set(),
}


class SpanParity(unittest.TestCase):
    """PER-ROW, PER-K parity of the production span matcher against the engine's
    own symbol_recall_by_k, recomputed independently from the row primitives."""

    def _assert_parity(self, corpus: str) -> None:
        rows = result_rows(load_report(_require(self, "native_floor", corpus)))
        checked = 0
        for row in rows:
            gold_keys = [str(s) for s in (row.get("gold_symbols") or [])]
            gold_ranges = row.get("gold_symbol_ranges") or []
            retrieved = [str(s) for s in (row.get("retrieved_symbols") or [])]
            engine = row.get("symbol_recall_by_k") or {}
            if not gold_keys:
                continue
            m = match_gold_spans(gold_keys, gold_ranges, retrieved)
            for k in (10, 25):
                eng = engine.get(str(k))
                if eng is None:
                    continue
                self.assertLess(
                    abs(m.recall_at(k) - float(eng)), REPLAY_TOL,
                    f"{corpus}/{row.get('instance_id')} k={k}: "
                    f"harness {m.recall_at(k):.6f} != engine {eng}",
                )
                checked += 1
        self.assertEqual(
            checked, EXPECTED_PARITY[corpus],
            f"{corpus}: parity checks by report row = {checked}, expected "
            f"{EXPECTED_PARITY[corpus]} (reach n = {GOLD_BEARING_N[corpus]})",
        )

    def test_parity_ts40(self) -> None:
        self._assert_parity("ts40")

    def test_parity_py_nosphinx(self) -> None:
        self._assert_parity("py_nosphinx")

    def test_parity_go34(self) -> None:
        self._assert_parity("go34")

    def test_parity_rust43(self) -> None:
        self._assert_parity("rust43")


class FloorCellNonZero(unittest.TestCase):
    def test_go34_native_floor_cell_is_non_zero(self) -> None:
        m = score_arm(load_report(_require(self, "native_floor", "go34")), "go34")
        self.assertGreater(m.reach_at_80_whole_list, 0.0)
        self.assertGreater(m.whole_list_INTERNAL, 0.0)

    def test_all_floor_cells_are_non_zero(self) -> None:
        for corpus in CORPORA:
            with self.subTest(corpus=corpus):
                m = score_arm(load_report(_require(self, "native_floor", corpus)), corpus)
                self.assertGreater(m.whole_list_INTERNAL, 0.0, f"{corpus} floor collapsed")


class ReachScored(unittest.TestCase):
    def test_gc1_scored_whole_list_reproduces_old_reach(self) -> None:
        for (arm, corpus), old in OLD_REACH.items():
            with self.subTest(arm=arm, corpus=corpus):
                m = score_arm(load_report(_require(self, arm, corpus)), corpus)
                self.assertLess(abs(m.reach_at_80_whole_list - old), REPLAY_TOL)

    def test_gc2_within_equals_whole_on_every_shipped_row(self) -> None:
        for corpus in CORPORA:
            with self.subTest(corpus=corpus):
                m = score_arm(load_report(_require(self, "shipped_treatment", corpus)), corpus)
                self.assertLess(
                    abs(m.reach_at_80_within_32k - m.reach_at_80_whole_list), REPLAY_TOL,
                    f"shipped/{corpus}: within_32k != whole_list (capped => equal)",
                )

    def test_gc3_both_discriminators_diverge(self) -> None:
        divergent = []
        for label, (arm, corpus) in (
            ("floor/ts40", ("native_floor", "ts40")),
            ("ablation/py", ("levers_off_ablation", "py_nosphinx")),
        ):
            m = score_arm(load_report(_require(self, arm, corpus)), corpus)
            if abs(m.reach_at_80_whole_list - m.reach_at_80_within_32k) > REPLAY_TOL:
                divergent.append(label)
        self.assertEqual(sorted(divergent), ["ablation/py", "floor/ts40"])


class FloorRegressionWitness(unittest.TestCase):
    def test_floor_held_ts40_and_py(self) -> None:
        for corpus in ("ts40", "py_nosphinx"):
            with self.subTest(corpus=corpus):
                checks = check_report_file(
                    _require(self, "native_floor", corpus), corpus, "native_floor"
                )
                self.assertTrue(checks)
                for c in checks:
                    self.assertTrue(
                        c.ok,
                        f"floor DRIFT {corpus}/{c.metric}: {c.got:.6f} != "
                        f"{c.expected:.6f} ({c.delta_pp:+.3f}pp)",
                    )


class WireCurvePathGuard(unittest.TestCase):
    def test_levers_off_through_rollup(self) -> None:
        report = load_report(_require(self, "levers_off_ablation", "py_nosphinx"))
        roll = rollup(report, frozen_instance_ids=list(load_frozen_gold("py_nosphinx")))
        self.assertGreaterEqual(roll.binding.gold_at_budget[8000], 0.0)

    def test_ablation_within_32k_wire_curve_path(self) -> None:
        m = score_arm(
            load_report(_require(self, "levers_off_ablation", "py_nosphinx")), "py_nosphinx"
        )
        self.assertLess(m.reach_at_80_within_32k, m.reach_at_80_whole_list)


class T1InstanceBasis(unittest.TestCase):
    """The gold-bearing basis is BINDING; the engine's all-rows basis is not; and
    the engine-vs-frozen drift is EXACTLY the pre-registered addendum."""

    def _measurer(self, corpus: str) -> dict:
        arms = load_fixture()["arms"][corpus]["shipped_treatment"]
        return {
            "gold_at_8k": arms["gold_at_8k_wire"],
            "reach_at_80_whole_list": arms["reach_at_80_whole_list"],
            "n": arms["n"],
        }

    def test_binding_basis_reproduces_measurer(self) -> None:
        for corpus in ("ts40", "py_nosphinx"):
            with self.subTest(corpus=corpus):
                want = self._measurer(corpus)
                roll = rollup(
                    load_report(_require(self, "shipped_treatment", corpus)),
                    frozen_instance_ids=list(load_frozen_gold(corpus)),
                )
                self.assertIs(roll.binding.basis, Basis.FROZEN_GOLD)
                self.assertEqual(roll.binding.n, want["n"])
                self.assertAlmostEqual(roll.binding.gold_at_budget[8000], want["gold_at_8k"], places=4)
                self.assertAlmostEqual(
                    roll.binding.reach_at_coverage[80], want["reach_at_80_whole_list"], places=4
                )

    def test_negative_control_all_rows_basis_misses_measurer(self) -> None:
        for corpus in ("ts40", "py_nosphinx"):
            with self.subTest(corpus=corpus):
                want = self._measurer(corpus)
                roll = rollup(
                    load_report(_require(self, "shipped_treatment", corpus)),
                    frozen_instance_ids=list(load_frozen_gold(corpus)),
                )
                self.assertGreater(roll.engine_basis.n, roll.binding.n)
                self.assertNotAlmostEqual(
                    roll.engine_basis.gold_at_budget[8000], want["gold_at_8k"], places=4
                )

    def test_difference_is_exactly_the_known_addendum_drift(self) -> None:
        for corpus in ("ts40", "py_nosphinx"):
            with self.subTest(corpus=corpus):
                report = load_report(_require(self, "shipped_treatment", corpus))
                frozen = load_frozen_gold(corpus)
                roll = rollup(report, frozen_instance_ids=list(frozen))
                drift = {r.get("instance_id") for r in gold_bearing_rows(report)} - set(frozen)
                self.assertEqual(
                    drift, KNOWN_DRIFT[corpus],
                    f"{corpus}: engine-vs-frozen drift != the pre-registered addendum",
                )
                rows = {r.get("instance_id"): r for r in result_rows(report)}
                drift_contrib = sum(
                    float((wire_curve(rows[i]).get("by_budget") or {}).get("8000", 0.0) or 0.0)
                    for i in drift
                )
                delta = (
                    roll.engine_basis.gold_at_budget[8000] * roll.engine_basis.n
                    - roll.binding.gold_at_budget[8000] * roll.binding.n
                )
                self.assertAlmostEqual(delta, drift_contrib, places=6)

    def test_render_labels_both_bases(self) -> None:
        # The rendered rollup must LABEL the two bases so a reader cannot mistake
        # the engine's all-rows basis for the binding one, and must state that the
        # ts40 engine-vs-frozen drift is EXPECTED (the pre-registered addendum),
        # not a discrepancy. Fail-loud (no skip): `_require` fetches or fails.
        text = rollup(
            load_report(_require(self, "shipped_treatment", "ts40")),
            frozen_instance_ids=list(load_frozen_gold("ts40")),
        ).render("ts40")
        self.assertIn("BINDING", text)
        self.assertIn("NOT binding", text)
        self.assertIn("EXPECTED, not a discrepancy", text)


class NativeFloorRunWireMedian(unittest.TestCase):
    """MUST-RED: the native_floor run-wire MEDIAN (the typical-instance floor
    cost) replays the pinned B5 §5 reference EXACTLY — ts40 <- L167 = 123,044,
    py_nosphinx <- L169 = 446,932; go34/rust43 are re-cert additions pinned in
    the fixture. This exercises the SAME `_run_wire_stats` the gauge renders, so
    a break in the median path (or a report that moved) reddens here."""

    def test_medians_replay_the_pinned_reference_exactly(self) -> None:
        pinned = load_fixture()["native_floor_run_wire_median"]["delivered_wire"]
        # The two anchored to B5 §5 must equal the doc's stated values.
        self.assertEqual(pinned["ts40"], 123044)  # B5 §5 L167
        self.assertEqual(pinned["py_nosphinx"], 446932)  # B5 §5 L169
        for corpus in ("ts40", "py_nosphinx", "go34", "rust43"):
            with self.subTest(corpus=corpus):
                report = load_report(_require(self, "native_floor", corpus))
                _mean, median, _max = _run_wire_stats(report, corpus)
                self.assertEqual(
                    median, pinned[corpus],
                    f"{corpus}: native_floor run-wire median {median:,} != pinned "
                    f"{pinned[corpus]:,} (B5 §5 reference)",
                )


class T7RealCaptures(unittest.TestCase):
    def test_real_captures_load(self) -> None:
        for corpus in ("ts40", "py_nosphinx"):
            with self.subTest(corpus=corpus):
                report = load_report(_require(self, "shipped_treatment", corpus))
                self.assertGreater(len(result_rows(report)), 0)
                self.assertGreater(len(list(gold_bearing_rows(report))), 0)


class T9AcceptanceCells(unittest.TestCase):
    def test_all_cells_exact_on_replay(self) -> None:
        for arm in ("shipped_treatment", "levers_off_ablation"):
            for corpus in ("ts40", "py_nosphinx"):
                with self.subTest(arm=arm, corpus=corpus):
                    checks = check_report_file(_require(self, arm, corpus), corpus, arm)
                    self.assertEqual(len(checks), len(LOCKED_METRICS) + 1)
                    for check in checks:
                        self.assertTrue(
                            check.ok,
                            f"{arm}/{corpus}/{check.metric}: {check.got:.6f} != "
                            f"{check.expected:.6f} ({check.delta_pp:+.3f}pp)",
                        )

    def test_negative_control_wrong_arm_fixture_mismatches(self) -> None:
        # Scoring the ablation report against the shipped arm's numbers must FAIL.
        checks = check_report_file(
            _require(self, "levers_off_ablation", "ts40"), "ts40", "shipped_treatment"
        )
        self.assertTrue(any(not c.ok for c in checks))


class T5CurveParity(unittest.TestCase):
    def test_g2_parity_on_both_public_corpora(self) -> None:
        for corpus in ("ts40", "py_nosphinx"):
            with self.subTest(corpus=corpus):
                report = load_report(_require(self, "shipped_treatment", corpus))
                self.assertEqual(curve_parity_findings(report), [])


class T10ReporterAnnotation(unittest.TestCase):
    def test_reporter_annotates_the_unclaimable_metric(self) -> None:
        checks = check_report_file(
            _require(self, "shipped_treatment", "py_nosphinx"),
            "py_nosphinx", "shipped_treatment",
        )
        at10 = next(c for c in checks if c.metric == "head_only_at_10")
        self.assertIn("NOT superiority-claimable", at10.note)


class T6CertifiedSurfaceScan(unittest.TestCase):
    """The full published-surface privacy scan (tracked + the certified tree),
    which REQUIRES the certified tree (fold F: no silent no-op) and REPORTS its
    scope. The clone-safe tracked-only scan lives in the unit suite."""

    SURFACE = _SURFACE

    def test_no_private_corpus_on_full_surface(self) -> None:
        import subprocess

        if not self.SURFACE.is_dir():
            self.fail(
                f"certified/fetched surface absent at {self.SURFACE} — run "
                "`reproduce.sh verify` (fetch-artifacts) first; this full-surface "
                "scan does not no-op"
            )
        extra = [
            f for f in self.SURFACE.rglob("*")
            if f.is_file() and "__pycache__" not in f.parts
        ]
        # finding-H cert_present guard: the resolved surface must actually carry
        # the certified reports. An empty or mislaid TTG_REPORTS_DIR must FAIL,
        # never silently degrade to a tracked-only scan.
        if not any(f.suffix.lower() == ".json" for f in extra):
            self.fail(
                f"certified/fetched surface at {self.SURFACE} carries no reports "
                "— run `reproduce.sh verify` (fetch-artifacts) first; this scan "
                "does not no-op on an empty surface"
            )
        tracked = subprocess.run(
            ["git", "ls-files", "-z"], cwd=PKG, capture_output=True, text=True, check=True
        ).stdout.split("\0")
        files = {PKG / p for p in tracked if p}
        files.update(extra)
        surface = [f for f in files if f.is_file() and "__pycache__" not in f.parts]
        json_count = sum(1 for f in surface if f.suffix.lower() == ".json")
        src = "fetched" if _ENV else "certified"
        print(f"\nfull surface: {len(surface)} files, {json_count} .json (tracked + {src})")
        offenders = [
            os.path.relpath(f, PKG)
            for f in surface
            if _privacy.contains_private(f.read_text(errors="ignore"))
        ]
        self.assertEqual(offenders, [], f"private corpus leaked into: {offenders}")


if __name__ == "__main__":
    unittest.main()
