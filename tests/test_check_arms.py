"""The (arm, corpus) grid must resolve BEFORE any stage runs.

An arm's flags can depend on per-corpus data: every waterfill and
per-file-caps cell derives its char budget from a corpus `base_20k`, which
only the V1 tiers carry. Without a t=0 check, an unresolvable pair surfaces in
run_matrix after provisioning, derivation and the drift sidecar -- hours of
work discarded for a fact knowable at the start.

The RED here is exactly the pair that was nearly hit in the 2026-09 re-cert:
(wf_b3, go34).
"""

from __future__ import annotations

import unittest

from arms.arm_matrix import ArmError, flags_for
from ttg.cli import main

RECERT_ARMS = "shipped_treatment,levers_off_ablation,native_floor"
ALL_TIERS = "ts40,py_nosphinx,go34,rust43"


class CheckArmsTest(unittest.TestCase):
    def test_the_near_miss_pair_is_refused(self) -> None:
        # wf_b3 x go34 -- the cell reproduce.sh's DEFAULT arms would have hit.
        self.assertEqual(main(["check-arms", "--arms", "wf_b3",
                               "--corpora", "go34"]), 2)

    def test_default_arms_are_refused_on_the_new_tiers(self) -> None:
        # Guards the actual mistake: running the re-cert with default arms.
        self.assertEqual(main(["check-arms", "--arms", "default",
                               "--corpora", ALL_TIERS]), 2)

    def test_the_preregistered_recert_set_resolves_on_all_four_tiers(self) -> None:
        self.assertEqual(main(["check-arms", "--arms", RECERT_ARMS,
                               "--corpora", ALL_TIERS]), 0)

    def test_v1_arms_still_resolve_on_the_v1_tiers(self) -> None:
        # The sweep must keep working where it always did.
        self.assertEqual(main(["check-arms", "--arms", "all",
                               "--corpora", "ts40,py_nosphinx"]), 0)

    def test_every_recert_cell_resolves_individually(self) -> None:
        for arm in RECERT_ARMS.split(","):
            for corpus in ALL_TIERS.split(","):
                with self.subTest(arm=arm, corpus=corpus):
                    flags_for(arm, corpus)  # must not raise

    def test_a_budgeted_arm_on_a_new_tier_raises_armerror(self) -> None:
        with self.assertRaises(ArmError):
            flags_for("pfc_b1", "rust43")


if __name__ == "__main__":
    unittest.main()
