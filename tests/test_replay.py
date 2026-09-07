"""G4: `ttg replay` — the 12-cell grid is DERIVED, never typed.

c3's failure mode is a cell that is silently absent: eleven green lines read like
twelve. The grid therefore comes from `arms.arm_matrix` (section-5 arms x pinned
corpora) and a cell that was not compared is a REFUSAL naming that cell, not a
shorter table.
"""

from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from arms.arm_matrix import CORPORA, SECTION5_ARMS
from ttg import cli, replay
from ttg.report_io import load_report, result_rows

STAGING = Path(__file__).resolve().parent.parent / "runs/recert-2026-09/R16-staging"


class DeriveCellsTest(unittest.TestCase):
    def test_the_grid_is_the_matrix_product_not_a_literal(self) -> None:
        cells = replay.derive_cells()
        self.assertEqual(len(cells), len(SECTION5_ARMS) * len(CORPORA))
        self.assertEqual(set(a for a, _ in cells), set(SECTION5_ARMS))
        self.assertEqual(set(c for _, c in cells), set(CORPORA))

    def test_adding_a_corpus_grows_the_grid_without_touching_replay(self) -> None:
        """The derivation must track the matrix: if a tier is added and the grid
        does not grow, the count was typed somewhere."""
        before = len(replay.derive_cells())
        CORPORA["__probe__"] = CORPORA["ts40"]
        try:
            self.assertEqual(len(replay.derive_cells()), before + len(SECTION5_ARMS))
        finally:
            del CORPORA["__probe__"]


class AnchorRoutingTest(unittest.TestCase):
    def test_v1_anchor_only_when_the_certified_baseline_reproduces_it(self) -> None:
        self.assertEqual(replay.choose_anchor(pinned=True, certified_matches=True), replay.ANCHOR_V1)
        self.assertEqual(replay.choose_anchor(pinned=True, certified_matches=False), replay.ANCHOR_CERTIFIED)
        self.assertEqual(replay.choose_anchor(pinned=False, certified_matches=False), replay.ANCHOR_CERTIFIED)


class MissingCellTest(unittest.TestCase):
    """MUST-RED: delete one report -> REFUSED, naming that cell."""

    def _dirs(self) -> tuple[Path, Path]:
        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, tmp, ignore_errors=True)
        reports, certified = tmp / "reports", tmp / "certified"
        reports.mkdir()
        certified.mkdir()
        for arm, corpus in replay.derive_cells():
            for d in (reports, certified):
                (d / f"{arm}_{corpus}.json").write_text(json.dumps({"results": []}))
        return reports, certified

    def test_a_missing_report_is_named_and_refused(self) -> None:
        reports, certified = self._dirs()
        victim = replay.derive_cells()[0]
        (reports / f"{victim[0]}_{victim[1]}.json").unlink()
        missing = replay.missing_cells(reports, certified, replay.derive_cells())
        self.assertIn(victim, [cell for cell, _ in missing])

    def test_a_missing_certified_baseline_is_also_named(self) -> None:
        reports, certified = self._dirs()
        victim = replay.derive_cells()[-1]
        (certified / f"{victim[0]}_{victim[1]}.json").unlink()
        missing = replay.missing_cells(reports, certified, replay.derive_cells())
        self.assertIn(victim, [cell for cell, _ in missing])

    def test_cli_refuses_and_names_the_cell(self) -> None:
        reports, certified = self._dirs()
        victim = replay.derive_cells()[0]
        (reports / f"{victim[0]}_{victim[1]}.json").unlink()
        rc = cli.main(["replay", "--reports", str(reports), "--certified", str(certified)])
        self.assertEqual(rc, 1)

    def test_a_complete_grid_is_not_refused_for_absence(self) -> None:
        reports, certified = self._dirs()
        self.assertEqual(replay.missing_cells(reports, certified, replay.derive_cells()), [])


@unittest.skipUnless(STAGING.is_dir(), "certified staging tree not present (fresh clone)")
class CertifiedReplayTest(unittest.TestCase):
    """Integration on the real certified reports: replaying them against
    THEMSELVES must be a perfect pass on every derived cell."""

    def test_the_certified_reports_replay_against_themselves(self) -> None:
        rc = cli.main(["replay", "--reports", str(STAGING), "--certified", str(STAGING)])
        self.assertEqual(rc, 0)

    def test_a_perturbed_cell_is_refused(self) -> None:
        """c6's shape at grid level: move ONE cell and the grid refuses, naming
        it. The certified reports are log-prefixed, so they are read through
        `load_report` (the same reader the scorer uses) and written back as plain
        JSON, which that reader also accepts."""
        import shutil as _shutil

        tmp = Path(tempfile.mkdtemp())
        self.addCleanup(_shutil.rmtree, tmp, ignore_errors=True)
        reports = tmp / "reports"
        reports.mkdir()
        arm, corpus = replay.derive_cells()[0]
        for cell_arm, cell_corpus in replay.derive_cells():
            name = f"{cell_arm}_{cell_corpus}.json"
            doc = load_report(STAGING / name)
            if (cell_arm, cell_corpus) == (arm, corpus):
                rows = result_rows(doc)
                self.assertTrue(rows, "certified report has no rows to perturb")
                # Drop one scored instance: n is a compared quantity, so the
                # denominator moving is a real, structure-independent change.
                doc = {**doc, "results": list(rows)[1:]}
            (reports / name).write_text(json.dumps(doc))
        rc = cli.main(["replay", "--reports", str(reports), "--certified", str(STAGING)])
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
