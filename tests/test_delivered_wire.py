"""The delivered-wire readers (B64 addendum, B63 lean wire).

Pinned here:
* PARITY: on real B63 Step 2 cells, the readers yield exactly what the B63
  grader (`grade_b63.py`) yields on the same cell -- JSON identities for an M0
  (objects) and a D+id (lines) cell, and the grep hits of a G0 (flat) and a G2
  (headed) cell. The reference parsers below are copied verbatim from
  noodlbox-wiki `strategy/projects/agent-work-packet/campaign/followthrough-2026-09/
  lane21/evidence/b63/step2/grade_b63.py` (wiki f40f1bfdf, sha256 a1396e4e…85ed);
  the grep reference records each hit's `(path, line)` where the grader credits
  its content tokens, because ttg joins a hit through the oracle by that key.
  The cells are `ts40/ofetch-per-origin-circuit-breaker/main/*.c4k` of the B63
  bundles (lane-evidence/l21/b63/results/out).
* NAME GRAMMAR (L21/L18 ruling): a whitespace, newline or leading-quote name
  round-trips through its JSON literal; a malformed literal and an unquoted
  whitespace name raise.
* LINE BASES: the same symbol in both shapes yields the same oracle key.
* EXHAUSTIVE DISPATCH: a mixed or unknown envelope raises; nothing falls through.
* HEADED GREP: an indented hit before any heading raises; a column-0 line that
  is not a delivered path is a continuation (Amendment 1).
"""

from __future__ import annotations

import json
import re
import unittest
from pathlib import Path

from ttg.delivered import DeliveredScoringError, grep_identities, json_identities
from ttg.delivered_wire import WireError, grep_hits, json_rows, recall_line, symbol_line

CELLS = Path(__file__).parent / "fixtures" / "b63_cells"

# --- reference: grade_b63.py (verbatim, see the module docstring) -----------
SPAN = re.compile(r"^\d+(-\d+)?$")
HEX12 = re.compile(r"^[0-9a-f]{12}$")


def reference_file_index(result):
    names = []
    for group in result.get("file_index", []):
        for row in group.get("rows", []):
            if isinstance(row, str):
                tokens = row.split(" ")
                tokens = tokens[1:] if SPAN.match(tokens[0]) else tokens
                names.append(f"{group['file_path']}:{tokens[1]}")
            else:
                names.append(f"{group['file_path']}:{row['name']}")
    return names


def reference_json_located(result):
    if "files" in result:
        names = []
        for group in result["files"]:
            for row in group["symbols"]:
                if isinstance(row, str):
                    tokens = row.split(" ")
                    tokens = tokens[1:] if HEX12.match(tokens[0]) else tokens
                    tokens = tokens[1:] if SPAN.match(tokens[0]) else tokens
                    names.append(f"{group['file_path']}:{tokens[1]}")
                else:
                    names.append(f"{group['file_path']}:{row['name']}")
        return names + reference_file_index(result)
    names = [f"{s['location']['file_path']}:{s['name']}" for s in result.get("symbols", [])]
    return names + reference_file_index(result)


def reference_grep_hits(text, known_paths):
    """`grep_located`'s hit parse, recording `(path, line)` per hit."""
    hits = []
    path = None
    for line in text.split("\n"):
        hit = re.match(r"^  (\d+):(.*)$", line)
        if hit and path is not None:
            hits.append((path, int(hit.group(1))))
        elif line in known_paths:
            path = line
            continue
        else:
            match = re.match(r"^(.*?):(\d+):(.*)$", line)
            if not match or match.group(1) not in known_paths:
                continue
            path = match.group(1)
            hits.append((path, int(match.group(2))))
    return hits
# -----------------------------------------------------------------------------


def cell(name: str) -> str:
    return (CELLS / f"{name}.stdout").read_text(encoding="utf-8")


def delivered_paths() -> frozenset[str]:
    """Every path the retrieval delivered in its JSON cells (the grader's
    `delivered_paths`)."""
    return frozenset(
        located.rsplit(":", 1)[0]
        for name in ("json.M0.c4k", "json.Did.c4k")
        for located in reference_json_located(json.loads(cell(name))["result"])
    )


def envelope(result: dict) -> str:
    return json.dumps({"result": result})


def line_envelope(*symbol_lines: str, path: str = "src/a.ts") -> str:
    return envelope({"files": [{"file_path": path, "symbols": list(symbol_lines)}]})


class B63CellParity(unittest.TestCase):
    """The readers agree with the B63 grader on the same real cells."""

    def test_json_identities_match_the_grader_on_both_shapes(self):
        for name in ("json.M0.c4k", "json.Did.c4k"):
            with self.subTest(cell=name):
                text = cell(name)
                expected = reference_json_located(json.loads(text)["result"])
                self.assertTrue(expected, "non-vacuity: the cell delivers identities")
                self.assertEqual(json_identities(text), expected)

    def test_grep_hits_match_the_grader_on_flat_and_headed_blocks(self):
        known = delivered_paths()
        for name in ("grep.G0.c4k", "grep.G2.c4k"):
            with self.subTest(cell=name):
                text = cell(name)
                expected = reference_grep_hits(text, known)
                self.assertTrue(expected, "non-vacuity: the block carries hits")
                self.assertEqual(grep_hits(text, known), expected)

    def test_the_headed_block_carries_the_flat_blocks_hits(self):
        known = delivered_paths()
        self.assertEqual(
            sorted(grep_hits(cell("grep.G2.c4k"), known)),
            sorted(grep_hits(cell("grep.G0.c4k"), known)),
        )


class NameGrammar(unittest.TestCase):
    """A name is bare, or a JSON literal when it could split the row."""

    def row(self, name_column: str) -> str:
        return f"0123456789ab 8-12 function {name_column} definition query_match fn f()"

    def test_quoted_names_round_trip_exactly(self):
        for name in ("Frame time", "line\nbreak", '"quoted', ""):
            with self.subTest(name=name):
                row = symbol_line("src/a.ts", self.row(json.dumps(name)))
                self.assertIsNotNone(row)
                self.assertEqual(row.name, name)

    def test_a_bare_name_is_read_as_one_token(self):
        row = symbol_line("src/a.ts", self.row("[Symbol.iterator]"))
        self.assertEqual((row.name, row.line), ("[Symbol.iterator]", 8))

    def test_an_unquoted_whitespace_name_raises(self):
        # The pre-ruling wire: `Frame time` bare shifts `time` into the role column.
        with self.assertRaises(WireError):
            symbol_line("src/a.ts", self.row("Frame time"))

    def test_a_malformed_literal_raises(self):
        with self.assertRaises(WireError):
            symbol_line("src/a.ts", self.row('"unterminated'))
        with self.assertRaises(WireError):
            symbol_line("src/a.ts", self.row('"glued"tail'))

    def test_recall_rows_share_the_name_grammar(self):
        self.assertEqual(recall_line("src/a.ts", '4 attribute "a b" x: number').name, "a b")
        self.assertEqual(recall_line("src/a.ts", "function helper").line, None)

    def test_the_row_must_lead_with_a_12_hex_id(self):
        with self.assertRaises(WireError):
            symbol_line("src/a.ts", "abc 8-12 function f definition query_match")


class LineBases(unittest.TestCase):
    """Both shapes key the oracle on the same `(path, 1-based line)`."""

    def test_one_symbol_in_both_shapes_yields_one_key(self):
        objects = envelope({"symbols": [
            {"name": "alpha", "location": {"file_path": "src/a.ts", "start_line": 21}}]})
        lines = line_envelope("0123456789ab 22-30 function alpha definition query_match")
        key_objects = [(r.path, r.line) for r in json_rows(json.loads(objects)["result"])]
        key_lines = [(r.path, r.line) for r in json_rows(json.loads(lines)["result"])]
        self.assertEqual(key_objects, [("src/a.ts", 22)])
        self.assertEqual(key_lines, key_objects)

    def test_a_grep_hit_joins_a_lines_oracle(self):
        oracle = line_envelope("0123456789ab 22-30 function alpha definition query_match")
        identities = grep_identities("src/a.ts:22:export function alpha()", oracle)
        self.assertEqual(identities.lower, ["src/a.ts:alpha"])


class ExhaustiveDispatch(unittest.TestCase):
    def test_a_mixed_envelope_raises(self):
        mixed = envelope({
            "symbols": [{"name": "a", "location": {"file_path": "src/a.ts"}}],
            "files": [{"file_path": "src/a.ts", "symbols": []}],
        })
        with self.assertRaises(DeliveredScoringError):
            json_identities(mixed)

    def test_mixed_recall_rows_raise(self):
        mixed = envelope({"file_index": [{"file_path": "src/a.ts", "rows": [
            {"name": "a", "line": 1}, "2 function b"]}]})
        with self.assertRaises(DeliveredScoringError):
            json_identities(mixed)

    def test_a_line_shape_with_object_recall_rows_raises(self):
        mixed = envelope({
            "files": [{"file_path": "src/a.ts", "symbols": [
                "0123456789ab 1-2 function a definition query_match"]}],
            "file_index": [{"file_path": "src/a.ts", "rows": [{"name": "b", "line": 3}]}],
        })
        with self.assertRaises(DeliveredScoringError):
            json_identities(mixed)

    def test_an_object_in_the_lines_lane_raises(self):
        with self.assertRaises(DeliveredScoringError):
            json_identities(envelope({"files": [{"file_path": "src/a.ts", "symbols": [{"name": "a"}]}]}))

    def test_an_envelope_with_no_rows_delivers_nothing(self):
        self.assertEqual(json_identities(envelope({"workflows": []})), [])


class HeadedGrep(unittest.TestCase):
    PATHS = frozenset({"src/a.ts", "src/b.ts"})

    def test_hits_take_their_heading(self):
        text = "src/a.ts\n  3:[def q] alpha\nsrc/b.ts\n  7:[def x] beta\n"
        self.assertEqual(grep_hits(text, self.PATHS), [("src/a.ts", 3), ("src/b.ts", 7)])

    def test_an_indented_hit_before_any_heading_raises(self):
        with self.assertRaises(WireError):
            grep_hits("  3:[def q] alpha\n", self.PATHS)

    def test_a_raw_newline_continuation_carries_no_identity(self):
        text = "src/a.ts\n  3:[def q] a multi\nline content: 12: here\nsrc/zz.ts:4:not delivered\n"
        self.assertEqual(grep_hits(text, self.PATHS), [("src/a.ts", 3)])


if __name__ == "__main__":
    unittest.main()
