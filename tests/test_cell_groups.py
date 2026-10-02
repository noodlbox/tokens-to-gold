"""`cell_groups`: which cells may run at once (EVAL-CLONE-RACE, noodlbox-app #2129).

Cells of different stores may overlap; cells of one store (a REUSE arm and the
FRESH arm whose store it reads) run in order, the FRESH cell first.

DISCIPLINE (as tests/test_harness.py): the grouping's two safety checks each
carry a PERMANENT NEGATIVE CONTROL -- the naive grouping it replaced, asserted to
FAIL the same check -- so a future "simplification" cannot quietly bring the race
or the out-of-order REUSE back.
"""

from __future__ import annotations

import contextlib
import io
import itertools
import unittest
from collections import Counter

from arms.arm_matrix import ArmError, CellGroup, cell_groups, reuses_a_store, store_name
from ttg.cli import main as cli_main

ARMS = ["levers_off_ablation", "shipped_treatment", "shipped_explore", "native_floor"]
CORPORA = ["ts40", "go34"]


def naive_per_cell_groups(arms: list[str], corpora: list[str]) -> list[CellGroup]:
    """The grouping a per-cell runner implies: every cell its own group, in the
    order given. A REUSE cell then sits apart from the FRESH cell whose store it
    reads, so the two would run at once on one store."""
    return [
        CellGroup(f"{arm}_{corpus}", corpus, (arm,))
        for arm, corpus in itertools.product(arms, corpora)
    ]


def groups_touching_one_store(groups: list[CellGroup]) -> list[str]:
    """Stores more than one group would touch: a store whose cells could overlap.
    A group touches the store its first arm runs in (every arm of a correct
    group runs in the same one, which test_a_group_never_mixes_stores pins)."""
    touched = Counter(store_name(group.arms[0], group.corpus) for group in groups)
    return sorted(store for store, count in touched.items() if count > 1)


def groups_running_a_reuse_cell_first(groups: list[CellGroup]) -> list[str]:
    """Groups of several cells whose first cell reuses a store another cell makes."""
    return [group.store for group in groups if len(group.arms) > 1 and reuses_a_store(group.arms[0])]


class CellGroupsTest(unittest.TestCase):
    def test_no_store_is_touched_by_two_groups(self) -> None:
        self.assertEqual(groups_touching_one_store(cell_groups(ARMS, CORPORA)), [])
        # Negative control: per-cell groups put levers_off_ablation (which reads
        # shipped_treatment's store) beside shipped_treatment, on the same store.
        self.assertEqual(
            groups_touching_one_store(naive_per_cell_groups(ARMS, CORPORA)),
            ["shipped_treatment_go34", "shipped_treatment_ts40"],
        )

    def test_a_reuse_cell_never_runs_before_its_source(self) -> None:
        self.assertEqual(groups_running_a_reuse_cell_first(cell_groups(ARMS, CORPORA)), [])
        # Negative control: keeping the order given (REUSE arm listed first) in a
        # shared group runs the REUSE cell before the store it reads exists.
        unsorted = [
            CellGroup("shipped_treatment_ts40", "ts40", ("levers_off_ablation", "shipped_treatment"))
        ]
        self.assertEqual(groups_running_a_reuse_cell_first(unsorted), ["shipped_treatment_ts40"])

    def test_a_group_never_mixes_stores(self) -> None:
        self.assertEqual(
            cell_groups(ARMS, CORPORA),
            [
                CellGroup("shipped_treatment_ts40", "ts40", ("shipped_treatment", "levers_off_ablation")),
                CellGroup("shipped_treatment_go34", "go34", ("shipped_treatment", "levers_off_ablation")),
                CellGroup("shipped_explore_ts40", "ts40", ("shipped_explore",)),
                CellGroup("shipped_explore_go34", "go34", ("shipped_explore",)),
                CellGroup("native_floor_ts40", "ts40", ("native_floor",)),
                CellGroup("native_floor_go34", "go34", ("native_floor",)),
            ],
        )
        # The grouping is store_name's: the REUSE arm names its source's store.
        self.assertEqual(store_name("levers_off_ablation", "go34"), "shipped_treatment_go34")

    def test_groups_come_arm_by_arm_so_the_first_ones_cover_different_corpora(self) -> None:
        groups = cell_groups(["shipped_treatment", "shipped_explore"], CORPORA)
        self.assertEqual([group.corpus for group in groups[:2]], ["ts40", "go34"])

    def test_an_empty_or_repeated_arm_or_corpus_is_refused(self) -> None:
        for arms, corpora, message in (
            ([], CORPORA, "no arm to run"),
            (ARMS, [], "no corpus to run"),
            (["shipped_treatment", "shipped_treatment"], CORPORA, "arm listed more than once"),
            (ARMS, ["ts40", "ts40"], "corpus listed more than once"),
        ):
            with self.subTest(message=message), self.assertRaisesRegex(ArmError, message):
                cell_groups(arms, corpora)

    def test_an_unknown_arm_is_refused(self) -> None:
        with self.assertRaises(ArmError):
            cell_groups(["no_such_arm"], ["ts40"])

    def test_the_cli_prints_one_whitespace_split_line_per_group(self) -> None:
        # arms/run_matrix.sh splits these lines on whitespace: pin the format.
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = cli_main(["cell-groups", "--arms", "levers_off_ablation,shipped_treatment",
                           "--corpora", "ts40"])
        self.assertEqual(rc, 0)
        self.assertEqual(
            out.getvalue(), "shipped_treatment_ts40 ts40 shipped_treatment levers_off_ablation\n"
        )


if __name__ == "__main__":
    unittest.main()
