"""`cell_groups`: which cells may run at once (EVAL-CLONE-RACE, noodlbox-app #2129).

Cells of different stores may overlap; cells of one store (a REUSE arm and the
FRESH arm whose store it reads) run in order, the FRESH cell first. Each check
carries a negative control: the naive ordering it replaces, asserted to differ.
"""

from __future__ import annotations

import unittest

from arms.arm_matrix import ArmError, CellGroup, cell_groups, store_name


class CellGroupsTest(unittest.TestCase):
    def test_every_store_is_one_group_in_first_appearance_order(self) -> None:
        groups = cell_groups(["shipped_treatment", "shipped_explore"], ["ts40", "go34"])
        self.assertEqual(
            [group.store for group in groups],
            ["shipped_treatment_ts40", "shipped_explore_ts40",
             "shipped_treatment_go34", "shipped_explore_go34"],
        )
        self.assertEqual(groups[0], CellGroup("shipped_treatment_ts40", "ts40", ("shipped_treatment",)))

    def test_a_reuse_arm_joins_its_source_and_runs_after_it(self) -> None:
        listed = ["levers_off_ablation", "shipped_treatment"]
        groups = cell_groups(listed, ["ts40"])
        self.assertEqual(
            groups,
            [CellGroup("shipped_treatment_ts40", "ts40", ("shipped_treatment", "levers_off_ablation"))],
        )
        # Negative control: the order given would run the REUSE cell first.
        self.assertNotEqual(tuple(listed), groups[0].arms)

    def test_a_group_never_mixes_stores(self) -> None:
        arms = ["shipped_treatment", "levers_off_ablation", "shipped_explore", "native_floor"]
        self.assertEqual(
            cell_groups(arms, ["ts40", "go34"]),
            [
                CellGroup("shipped_treatment_ts40", "ts40", ("shipped_treatment", "levers_off_ablation")),
                CellGroup("shipped_explore_ts40", "ts40", ("shipped_explore",)),
                CellGroup("native_floor_ts40", "ts40", ("native_floor",)),
                CellGroup("shipped_treatment_go34", "go34", ("shipped_treatment", "levers_off_ablation")),
                CellGroup("shipped_explore_go34", "go34", ("shipped_explore",)),
                CellGroup("native_floor_go34", "go34", ("native_floor",)),
            ],
        )
        # The grouping is store_name's: the REUSE arm names its source's store.
        self.assertEqual(store_name("levers_off_ablation", "go34"), "shipped_treatment_go34")

    def test_an_unknown_arm_is_refused(self) -> None:
        with self.assertRaises(ArmError):
            cell_groups(["no_such_arm"], ["ts40"])


if __name__ == "__main__":
    unittest.main()
