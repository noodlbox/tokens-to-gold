"""The 4-language report generator: PENDING plumbing (always) + the real
partial render against the lease-1 certified reports (when staged).

Must-red: the whole module fails to import before `ttg/report.py` exists
(`build_report_doc` is undefined), so every assertion here is red without the
generator and green with it. The empty-dir test additionally holds the
report-not-staged path without needing any run artifact, so it runs in a fresh
clone; the render test skips unless the lease-1 certified reports are present.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ttg import report
from ttg.report import (
    ARMS,
    CORPUS_LANG,
    Cell,
    CellScore,
    Provenance,
    ProvenanceError,
    build_report_doc,
    gold_distribution,
)

PKG = Path(__file__).resolve().parent.parent
GOLD = PKG / "gold"

# A stand-in provenance so the table/plumbing tests exercise the full compose
# without depending on the pending PIN (the gate is tested separately below).
# released_binary_sha=None is the state R16 ships in (the public binary is R17).
_FAKE_PROV = Provenance(
    harness_tip="deadbeefcafe",
    binary_sha="ab" * 32,
    untracked_count=3,
    released_binary_sha=None,
)


class PendingPlumbingTest(unittest.TestCase):
    """No run artifact needed: an empty reports dir is 12 PENDING cells."""

    def test_empty_reports_dir_is_all_pending(self) -> None:
        with mock.patch.object(report, "resolve_provenance", return_value=_FAKE_PROV):
            with tempfile.TemporaryDirectory() as tmp:
                doc = build_report_doc(tmp)
        self.assertEqual(len(CORPUS_LANG) * len(ARMS), 12)
        self.assertIn("0 of 12 cells scored", doc)
        # all 12 table cells (plus the 4 ts40/py regression rows) are PENDING
        # with a reason, never a fabricated 0.
        self.assertGreaterEqual(doc.count("PENDING (report not staged)"), 12)
        self.assertNotIn("0.0000", doc)


class GoldDistributionTest(unittest.TestCase):
    """Read from the FROZEN gold on disk, never remembered. The ts40 and py gold
    ship in the repo, so this runs in any clone."""

    def test_thin_keys_median_max_from_frozen_gold(self) -> None:
        ts = gold_distribution(GOLD / "frozen_gold_ts40.json")
        self.assertEqual((ts.n, ts.thin_keys, ts.max_per_instance), (37, 1, 30))
        self.assertEqual(ts.median_per_instance, 7)

        # Python is the thin-keys caveat: 26 of 39 instances are single-symbol
        # gold (median 1), a materially easier shape than ts40's median 7.
        py = gold_distribution(GOLD / "frozen_gold_py_nosphinx.json")
        self.assertEqual((py.n, py.thin_keys), (39, 26))
        self.assertEqual(py.median_per_instance, 1)


class SyntheticRenderTest(unittest.TestCase):
    """Runs EVERYWHERE (no run artifact, no skipUnless): a synthetic ts40
    fixture built from the committed frozen gold exercises the SCORED symbol
    path (shipped/levers, `token_coverage_wire`), the SCORED span path
    (native_floor, span-form retrieval + `token_coverage`), and the PENDING path
    (go34/rust43 absent). Asserts SHAPE, never pinned values -- the real numbers
    are A4 evidence, not a unit-test constant."""

    @staticmethod
    def _symbol_rows(gold: dict[str, list[str]]) -> list[dict]:
        """One symbol-arm row per frozen-gold instance. retrieved == gold so
        scoring produces real (non-pinned) numbers; the wire block is populated
        so shipped/levers render numeric coverage@budget."""
        rows: list[dict] = []
        for iid, symbols in gold.items():
            rows.append(
                {
                    "instance_id": iid,
                    "gold_symbols": list(symbols),
                    "retrieved_symbols": list(symbols),
                    "token_coverage_wire": {
                        "delivered_tokens": 9000,
                        "by_budget": {"2000": 1.0, "8000": 1.0, "32000": 1.0},
                        "tokens_to_coverage": {"50": 500, "80": 800, "100": 1000},
                    },
                }
            )
        return rows

    @staticmethod
    def _floor_rows(gold: dict[str, list[str]]) -> list[dict]:
        """One span-arm (native_floor) row per instance: each gold symbol gets a
        distinct range and a covering `file:span:a-b`, and the arm carries only
        `token_coverage` (spans are read content; wire == read). Every gold is
        covered, so the floor scores real non-zero coverage@budget and reach."""
        rows: list[dict] = []
        for iid, symbols in gold.items():
            ranges = [[10 + i * 100, 30 + i * 100] for i in range(len(symbols))]
            retrieved = [
                f"{sym.split(':', 1)[0]}:span:{ranges[i][0]}-{ranges[i][1]}"
                for i, sym in enumerate(symbols)
            ]
            rows.append(
                {
                    "instance_id": iid,
                    "gold_symbols": list(symbols),
                    "gold_symbol_ranges": ranges,
                    "retrieved_symbols": retrieved,
                    "token_coverage": {
                        "delivered_tokens": 80000,
                        "by_budget": {"2000": 0.5, "8000": 1.0, "32000": 1.0},
                        "tokens_to_coverage": {"50": 500, "80": 800, "100": 1000},
                    },
                }
            )
        return rows

    def _write_fixture(self, out: Path) -> None:
        gold = json.loads((GOLD / "frozen_gold_ts40.json").read_text())["gold"]
        (out / "shipped_treatment_ts40.json").write_text(
            json.dumps({"results": self._symbol_rows(gold)})
        )
        (out / "levers_off_ablation_ts40.json").write_text(
            json.dumps({"results": self._symbol_rows(gold)})
        )
        (out / "native_floor_ts40.json").write_text(
            json.dumps({"results": self._floor_rows(gold)})
        )
        # go34/rust43: no arm reports -> PENDING.

    def _row_line(self, doc: str, arm: str) -> str:
        for line in doc.splitlines():
            if line.startswith(f"| {arm} |"):
                return line
        self.fail(f"no rendered row for {arm}")

    def test_scored_pending_and_floor_shape(self) -> None:
        with mock.patch.object(report, "resolve_provenance", return_value=_FAKE_PROV):
            with tempfile.TemporaryDirectory() as tmp:
                out = Path(tmp)
                self._write_fixture(out)
                doc = build_report_doc(out)

        # 3 ts40 cells present + scored; the other 9 are PENDING.
        self.assertIn("3 of 12 cells scored", doc)

        # SCORED symbol path: ts40 shipped renders numeric wire coverage, not
        # PENDING (retrieved == gold -> Gold@8k_wire = 1.0000).
        shipped = self._row_line(doc, "shipped_treatment")
        self.assertNotIn("PENDING", shipped)
        self.assertIn("1.0000", shipped)

        # SCORED span path: native_floor is wire-priced via token_coverage, so it
        # renders numeric coverage@budget (Gold@8k = 1.0000 here), NEVER "n/a"
        # and never a PENDING. Its head-only@k is omitted (rendered as "—") and
        # its reach carries the unbounded-reach footnote marker.
        floor = self._row_line(doc, "native_floor")
        self.assertNotIn("PENDING", floor)
        self.assertNotIn("n/a", floor)
        self.assertIn("1.0000", floor)
        self.assertIn("—", floor)
        # The reworded footnote states the pricing basis, not an "n/a" excuse.
        self.assertIn("wire == read for spans", doc)
        self.assertNotIn("does not price retrieval by", doc)

        # PENDING path: go34/rust43 have no arm report.
        self.assertIn("Go  (corpus `go34`, N=30)", doc)
        self.assertIn("Rust  (corpus `rust43`, N=40)", doc)
        self.assertIn("PENDING (report not staged)", doc)

        # Whole-list recall is INTERNAL and must never be rendered.
        self.assertNotIn("whole_list", doc.lower())

        # The thin-keys distribution renders, read from the committed frozen gold
        # and independent of which arm reports are staged.
        self.assertIn("Gold-symbol distribution (thin-keys caveat)", doc)
        self.assertIn("| TypeScript | `ts40` |", doc)

        # The run-wire cost gauge renders (additive), values tracing to the rows'
        # delivered_tokens: 9,000 (symbol arms) and 80,000 (the span floor). The
        # gauge now carries a median column (mean / median / max).
        self.assertIn("Run-wire cost gauge", doc)
        self.assertIn("median run wire", doc)
        self.assertIn("9,000 wire", doc)
        self.assertIn("80,000 wire", doc)


class ProvenanceGateTest(unittest.TestCase):
    """P/K/L: the published artifact REFUSES rather than stamp a hardcoded or
    unverifiable provenance."""

    def test_render_refuses_on_pending_pin(self) -> None:
        # K: a PENDING [recert.binary] REFUSES the render. The committed pin is
        # filled since step 8, so the pending state is injected (mock) rather
        # than relied on — the behavior, not the current pin value, is the guard.
        with mock.patch.object(report, "is_pending", return_value=True):
            with tempfile.TemporaryDirectory() as tmp:
                with self.assertRaises(ProvenanceError):
                    build_report_doc(tmp)

    def test_harness_tip_equals_rev_parse_on_clean_tree(self) -> None:
        # P: the derived tip is exactly git rev-parse HEAD when tracked is clean.
        head = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=PKG, capture_output=True, text=True
        ).stdout.strip()

        def fake_git(pkg: Path, *args: str) -> str:
            return head + "\n" if args[0] == "rev-parse" else ""  # clean status

        with mock.patch.object(report, "_git", side_effect=fake_git):
            self.assertEqual(report._derive_harness_tip(PKG), head)

    def test_refuses_on_dirty_tracked_tree(self) -> None:
        # P: a non-empty `status --porcelain --untracked-files=no` REFUSES.
        def dirty_git(pkg: Path, *args: str) -> str:
            return "abc123\n" if args[0] == "rev-parse" else " M ttg/report.py\n"

        with mock.patch.object(report, "_git", side_effect=dirty_git):
            with self.assertRaises(ProvenanceError):
                report._derive_harness_tip(PKG)

    def test_untracked_only_tree_does_not_refuse(self) -> None:
        # P nuance: untracked paths (runs/ by design) NEVER refuse — the
        # tracked-only status is clean, so the tip derives.
        head = "cafef00d"

        def untracked_only_git(pkg: Path, *args: str) -> str:
            if args[0] == "rev-parse":
                return head + "\n"
            if "--untracked-files=no" in args:
                return ""  # tracked clean
            return "?? runs/x\n?? runs/y\n"  # untracked present

        with mock.patch.object(report, "_git", side_effect=untracked_only_git):
            self.assertEqual(report._derive_harness_tip(PKG), head)
            self.assertEqual(report._count_untracked(PKG), 2)

    def test_n_equality_scored_vs_gold_distribution(self) -> None:
        # L: a scored cell whose n != GoldDistribution.n REFUSES. ts40 gold n = 37.
        good = Cell("ts40", "shipped_treatment", _cellscore(n=37), None)
        self.assertEqual(report._corpus_n("ts40", [good], GOLD), 37)
        bad = Cell("ts40", "shipped_treatment", _cellscore(n=999), None)
        with self.assertRaises(ProvenanceError):
            report._corpus_n("ts40", [bad], GOLD)


class RenderBothBinariesTest(unittest.TestCase):
    """The provenance renders BOTH binaries honestly: the measurement binary
    (measured-with, not published) always, and the release binary as either
    PENDING (R17) or its published sha — never conflating the two."""

    def test_pending_release_renders_measurement_and_pending(self) -> None:
        out = report.render_provenance(_FAKE_PROV)
        self.assertIn("ab" * 32, out)  # measurement sha shown
        self.assertIn("measured-with, not published", out)
        self.assertIn("Release binary — PENDING (R17)", out)
        self.assertIn("validate-pins --flip", out)

    def test_published_release_renders_the_release_sha(self) -> None:
        flipped = Provenance(
            harness_tip="deadbeefcafe",
            binary_sha="ab" * 32,
            untracked_count=3,
            released_binary_sha="cd" * 32,
        )
        out = report.render_provenance(flipped)
        self.assertIn("cd" * 32, out)  # release sha shown
        self.assertIn("ab" * 32, out)  # measurement sha still shown
        self.assertNotIn("PENDING (R17)", out)


def _cellscore(n: int) -> CellScore:
    return CellScore(
        corpus="ts40",
        arm="shipped_treatment",
        n=n,
        gold_at_8k=1.0,
        gold_at_32k=1.0,
        head_at_10=0.0,
        head_at_25=0.0,
        reach_at_80_whole_list=0.0,
        reach_at_80_within_32k=0.0,
        ttg80_median_wire=None,
        whole_list_internal=0.0,
        mean_run_wire=0,
        median_run_wire=0,
        max_run_wire=0,
    )


if __name__ == "__main__":
    unittest.main()
