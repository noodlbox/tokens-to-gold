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
import tempfile
import unittest
from pathlib import Path

from ttg.report import ARMS, CORPUS_LANG, build_report_doc, gold_distribution

PKG = Path(__file__).resolve().parent.parent
GOLD = PKG / "gold"


class PendingPlumbingTest(unittest.TestCase):
    """No run artifact needed: an empty reports dir is 12 PENDING cells."""

    def test_empty_reports_dir_is_all_pending(self) -> None:
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
    fixture built from the committed frozen gold exercises the SCORED path
    (shipped/levers, wire-priced), the n/a path (native_floor present but NOT
    wire-priced), and the PENDING path (go34/rust43 absent). Asserts SHAPE, never
    pinned values -- the real numbers are A4 evidence, not a unit-test constant."""

    @staticmethod
    def _rows(gold: dict[str, list[str]], *, wire_priced: bool) -> list[dict]:
        """One result row per frozen-gold instance. retrieved == gold so scoring
        produces real (non-pinned) numbers; the wire block is present only when
        priced, so native_floor (unpriced) renders n/a, not a measured zero."""
        rows: list[dict] = []
        for iid, symbols in gold.items():
            row: dict = {
                "instance_id": iid,
                "gold_symbols": list(symbols),
                "retrieved_symbols": list(symbols),
            }
            row["token_coverage_wire"] = (
                {
                    "by_budget": {"2000": 1.0, "8000": 1.0, "32000": 1.0},
                    "tokens_to_coverage": {"50": 500, "80": 800, "100": 1000},
                }
                if wire_priced
                else {}
            )
            rows.append(row)
        return rows

    def _write_fixture(self, out: Path) -> None:
        gold = json.loads((GOLD / "frozen_gold_ts40.json").read_text())["gold"]
        for arm, priced in (
            ("shipped_treatment", True),
            ("levers_off_ablation", True),
            ("native_floor", False),  # present, not wire-priced -> n/a
        ):
            (out / f"{arm}_ts40.json").write_text(
                json.dumps({"results": self._rows(gold, wire_priced=priced)})
            )
        # go34/rust43: no arm reports -> PENDING.

    def _row_line(self, doc: str, arm: str) -> str:
        for line in doc.splitlines():
            if line.startswith(f"| {arm} |"):
                return line
        self.fail(f"no rendered row for {arm}")

    def test_scored_pending_and_na_shape(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            self._write_fixture(out)
            doc = build_report_doc(out)

        # 3 ts40 cells present + scored; the other 9 are PENDING.
        self.assertIn("3 of 12 cells scored", doc)

        # SCORED path: ts40 shipped renders numeric wire coverage, not PENDING
        # (retrieved == gold -> Gold@8k_wire = 1.0000).
        shipped = self._row_line(doc, "shipped_treatment")
        self.assertNotIn("PENDING", shipped)
        self.assertIn("1.0000", shipped)

        # n/a path: native_floor is present but not wire-priced -> coverage@budget
        # and cost-to-coverage are n/a, never a measured-looking 0.0000.
        self.assertIn("n/a", self._row_line(doc, "native_floor"))

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


if __name__ == "__main__":
    unittest.main()
