"""MR-2: a ranked-list ceiling report is never publishable as delivered."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from ttg.cli import main
from ttg.delivered_page import render_headline
from ttg.publication import ArmKind, CeilingNotPublishable, arm_kind, publishable_as_delivered

ENGINE_REPORT = {"arm": "shipped_treatment", "results": []}
DELIVERED_REPORT = {
    "arm": "delivered", "arm_kind": "delivered", "publishable_as_delivered": True, "corpus": "ts40",
    "rows": {"grep.8000": {"summary": {
        "gold_delivered": 0.5, "gold_delivered_upper": 0.5, "ambiguous_hits": 0, "ambiguity_flag": False,
        "reach_at_80_within_budget": 0.25, "ttg_wire_median": 900, "ttg_wire_p90": 1200, "ttg_wire_max": 1500,
        "ttg_stdout_median": 700, "ttg_stderr_median": 200, "over_budget_cells": 0, "failed_cells": [],
        "publishable": True}}},
}


def assert_refuses_ceiling(testcase: unittest.TestCase, renderer) -> None:
    """MR-2's property: rendering an engine report as a headline must fail."""
    with testcase.assertRaises(CeilingNotPublishable):
        renderer([ENGINE_REPORT])


class CeilingIsNotDelivered(unittest.TestCase):
    def test_an_engine_report_is_a_ceiling_by_construction(self) -> None:
        self.assertIs(arm_kind(ENGINE_REPORT), ArmKind.RANKED_LIST_CEILING)
        self.assertFalse(publishable_as_delivered(ENGINE_REPORT))

    def test_a_ceiling_report_cannot_claim_to_be_delivered_by_one_flag(self) -> None:
        self.assertFalse(publishable_as_delivered({**ENGINE_REPORT, "publishable_as_delivered": True}))

    def test_mr2_the_headline_renderer_refuses_a_ceiling_report(self) -> None:
        assert_refuses_ceiling(self, render_headline)

    def test_mr2_red_an_unguarded_renderer_is_caught(self) -> None:
        def unguarded(reports):  # renders whatever it is handed
            return "\n".join(str(r.get("arm")) for r in reports)

        with self.assertRaises(AssertionError):
            assert_refuses_ceiling(self, unguarded)

    def test_a_delivered_report_renders_with_its_headline_row(self) -> None:
        page = render_headline([DELIVERED_REPORT])
        self.assertIn("`grep.8000` **(headline)** | 0.5000", page)
        self.assertIn("900 / 1,200 / 1,500", page)


    def test_mr2_the_cli_refuses_a_ceiling_report_as_a_page(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "shipped_treatment_ts40.json"
            path.write_text(json.dumps(ENGINE_REPORT))
            with contextlib.redirect_stderr(io.StringIO()) as err:
                code = main(["delivered-page", str(path)])
        self.assertEqual(code, 2)
        self.assertIn("ranked_list_ceiling", err.getvalue())


if __name__ == "__main__":
    unittest.main()
