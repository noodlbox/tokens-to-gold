"""The delivered arm's identity, pricing and fail-closed rules (B64 addenda).

Must-reds pinned here:
* MR-1 byte sensitivity: two responses that deliver the SAME identities in
  different bytes must price differently. The B62 defect shape -- a fixed price
  per row -- is shown to fail the same property.
* MR-3 grep fail-closed: a grep hit with no identity-oracle row fails the cell.
"""

from __future__ import annotations

import json
import unittest

from ttg.delivered import (
    DeliveredScoringError,
    UnjoinableHit,
    grep_identities,
    json_identities,
    price,
    recall,
)


def envelope(symbols=(), file_index=()) -> str:
    return json.dumps({"result": {"symbols": list(symbols), "file_index": list(file_index)}})


def symbol(path: str, name: str, line: int) -> dict:
    return {"name": name, "location": {"file_path": path, "start_line": line}}


def whitespace_count(data: bytes) -> int:
    """A deterministic stand-in counter: whitespace-separated pieces."""
    return len(data.split())


ORACLE = envelope(
    symbols=[
        symbol("src/a.ts", "alpha", 9),
        symbol("src/a.ts", "beta", 19),
        symbol("src/b.ts", "gamma", 4),
        symbol("src/b.ts", "delta", 4),  # same line: an ambiguous key
    ],
    file_index=[{"file_path": "src/c.ts", "rows": [{"name": "eps", "line": 0}]}],
)


class JsonIdentities(unittest.TestCase):
    def test_located_symbols_then_file_index_in_wire_order(self) -> None:
        text = envelope(
            symbols=[symbol("src/a.ts", "alpha", 1), {"name": "unlocated", "location": {"file_path": ""}}],
            file_index=[{"file_path": "src/c.ts", "rows": [{"name": "eps", "line": 0}]}],
        )
        self.assertEqual(json_identities(text), ["src/a.ts:alpha", "src/c.ts:eps"])

    def test_counts_are_not_identities(self) -> None:
        zero = {"total": 0, "included": 0, "omitted": 0}
        text = json.dumps({"result": {"symbols": [], "file_index": [
            {"file_path": "src/c.ts", "rows": [], "more_members": 7}]},
            "coverage": {section: zero for section in (
                "workflow_symbols", "definitions", "related_symbols", "blast_radius", "file_index")}})
        self.assertEqual(json_identities(text), [])

    def test_unparseable_payload_fails_the_cell(self) -> None:
        with self.assertRaises(DeliveredScoringError):
            json_identities("not json")


class GrepIdentitiesRule(unittest.TestCase):
    def test_unique_keys_credit_their_one_name(self) -> None:
        got = grep_identities(
            "src/a.ts:10:[definition · exact] function alpha()\nsrc/c.ts:1:[recall · same-file] eps",
            ORACLE, one_line_per_hit=True,
        )
        self.assertEqual(got.lower, ["src/a.ts:alpha", "src/c.ts:eps"])
        self.assertEqual(got.upper, got.lower)
        self.assertEqual(got.ambiguous_hits, 0)

    def test_ambiguous_key_credits_nothing_in_the_headline(self) -> None:
        got = grep_identities("src/b.ts:5:const gamma = 1, delta = 2", ORACLE, one_line_per_hit=True)
        self.assertEqual(got.lower, [])
        self.assertEqual(got.upper, ["src/b.ts:gamma", "src/b.ts:delta"])
        self.assertEqual(got.ambiguous_hits, 1)

    def test_a_non_hit_line_is_a_counted_continuation_only_before_1791(self) -> None:
        pre = grep_identities("# callers\n", ORACLE, one_line_per_hit=False)
        self.assertEqual((pre.lower, pre.continuation_lines), ([], 1))
        with self.assertRaises(DeliveredScoringError):
            grep_identities("# callers\n", ORACLE, one_line_per_hit=True)

    def test_mr3_unjoinable_hit_fails_the_cell(self) -> None:
        with self.assertRaises(UnjoinableHit):
            grep_identities("src/a.ts:11:function notInOracle()", ORACLE, one_line_per_hit=True)

    def test_empty_block_is_no_hits_not_a_failure(self) -> None:
        self.assertEqual(grep_identities("", ORACLE, one_line_per_hit=True).lower, [])


def assert_byte_sensitive(testcase: unittest.TestCase, pricer) -> None:
    """MR-1's property: same identities, different bytes -> different price."""
    terse = envelope(symbols=[symbol("src/a.ts", "alpha", 1)]).encode()
    verbose = json.dumps(
        {"result": {"symbols": [symbol("src/a.ts", "alpha", 1) | {"signature": "function alpha(x: number, y: string): Promise<void>"}]}},
        indent=2,
    ).encode()
    testcase.assertEqual(json_identities(terse.decode()), json_identities(verbose.decode()))
    testcase.assertNotEqual(pricer(terse), pricer(verbose))


class Pricing(unittest.TestCase):
    def test_mr1_price_follows_the_delivered_bytes(self) -> None:
        assert_byte_sensitive(self, lambda data: price(data, b"", whitespace_count).wire)

    def test_mr1_red_a_fixed_per_row_price_is_caught(self) -> None:
        def per_row(data: bytes) -> int:  # the B62 defect shape: ~10 tokens a row
            return 10 * len(json_identities(data.decode()))

        with self.assertRaises(AssertionError):
            assert_byte_sensitive(self, per_row)

    def test_headline_counts_stdout_and_stderr_as_one_concatenation(self) -> None:
        # "a b" + "c d e" is "a bc d e": the concatenation is priced as one
        # string (4 pieces), not as the sum of the two streams (5).
        got = price(b"a b", b"c d e", whitespace_count)
        self.assertEqual((got.wire, got.stdout, got.stderr), (4, 2, 3))


class Recall(unittest.TestCase):
    def test_unchanged_matcher_over_delivered_identities(self) -> None:
        self.assertEqual(recall(["src/a.ts:alpha", "src/x.ts:zeta"], ["src/a.ts:alpha"]), 0.5)


if __name__ == "__main__":
    unittest.main()
