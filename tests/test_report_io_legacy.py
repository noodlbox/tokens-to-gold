"""Reports written before LEDGER B64's rename read under the current names."""

from __future__ import annotations

import json
import unittest

from ttg.report_io import ReportFormatError, loads_report


class LegacyRowKeys(unittest.TestCase):
    def test_a_pre_rename_report_reads_under_the_current_names(self) -> None:
        text = json.dumps({"results": [{"instance_id": "a",
                                        "token_coverage_wire": {"by_budget": {"8000": 0.5}},
                                        "retrieved_wire_positions": [3, 7]}]})
        row = loads_report(text)["results"][0]
        self.assertEqual(row["token_coverage_ranked_list"], {"by_budget": {"8000": 0.5}})
        self.assertEqual(row["retrieved_ranked_list_positions"], [3, 7])
        self.assertNotIn("token_coverage_wire", row)

    def test_a_row_with_both_spellings_is_refused(self) -> None:
        text = json.dumps({"results": [{"instance_id": "a",
                                        "token_coverage_wire": {}, "token_coverage_ranked_list": {}}]})
        with self.assertRaises(ReportFormatError):
            loads_report(text)


if __name__ == "__main__":
    unittest.main()
