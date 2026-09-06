"""R15/R17: the privacy-scan-binary release gate.

A byte scan catches the held-out corpus name embedded in a compiled artifact (an
SQL-comment string in the eval binary, the R17 case) that a source scan misses.
The plant token comes THROUGH the resolver, written to a throwaway temp path.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ttg import privacy
from ttg.privacy import scan_bytes


class ScanBytesTest(unittest.TestCase):
    def test_embedded_token_is_found(self) -> None:
        blob = b"\x00\x01-- get " + privacy.PRIVATE_CORPUS.encode() + b" rows\x00\xff"
        hits = scan_bytes(blob)
        self.assertEqual(len(hits), 1)
        offset, ctx = hits[0]
        self.assertGreater(offset, 0)
        # The reported context is REDACTED — the gate output is not a leak.
        self.assertIn(privacy.REDACTION, ctx)
        self.assertNotIn(privacy.PRIVATE_CORPUS, ctx)

    def test_clean_binary_has_no_hit(self) -> None:
        self.assertEqual(scan_bytes(b"\x00 hello world get_data() \xff\xfe"), [])

    def test_larger_word_substring_is_not_flagged(self) -> None:
        # NEGATIVE CONTROL: the token as a substring of a larger word (a letter
        # on either side) is not a hit — the boundary matcher, byte-side too.
        blob = b"xx tor" + privacy.PRIVATE_CORPUS.encode() + b"ge yy"
        self.assertEqual(scan_bytes(blob), [])

    def test_underscore_embedded_component_is_found(self) -> None:
        # A symbol like get_<token>_rows in a binary's string table IS a hit.
        blob = b"\x07get_" + privacy.PRIVATE_CORPUS.encode() + b"_rows\x00"
        self.assertEqual(len(scan_bytes(blob)), 1)


class ScanBinaryCliTest(unittest.TestCase):
    def _run(self, blob: bytes) -> int:
        from ttg import cli

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "artifact.bin"  # fresh throwaway path
            path.write_bytes(blob)
            return cli.main(["scan-binary", "--path", str(path)])

    def test_cli_refuses_on_hit(self) -> None:
        blob = b"-- " + privacy.PRIVATE_CORPUS.encode() + b" --"
        self.assertEqual(self._run(blob), 1)

    def test_cli_allows_clean(self) -> None:
        self.assertEqual(self._run(b"clean artifact bytes"), 0)


if __name__ == "__main__":
    unittest.main()
