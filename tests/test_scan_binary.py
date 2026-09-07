"""R15/R17: the privacy-scan-binary release gate — a SUBSTRING scan (RULED c)
with a reviewed allowlist of known identifier-table coincidences. The plant
token comes THROUGH the resolver, written to a throwaway temp path; no literal.
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
        violations, skipped = scan_bytes(blob)
        self.assertEqual((len(violations), skipped), (1, 0))
        _offset, ctx = violations[0]
        # The reported context is REDACTED — the gate output is not a leak.
        self.assertIn(privacy.REDACTION, ctx)
        self.assertNotIn(privacy.PRIVATE_CORPUS, ctx)

    def test_clean_binary_has_no_hit(self) -> None:
        self.assertEqual(scan_bytes(b"\x00 hello world get_data() \xff\xfe"), ([], 0))

    def test_in_word_occurrence_is_a_violation(self) -> None:
        # Substring gate (RULED c): the token inside a larger word IS a violation
        # — no boundary exception. Assembled at runtime, never a literal.
        blob = b"xx tor" + privacy.PRIVATE_CORPUS.encode() + b"ge yy"
        violations, skipped = scan_bytes(blob)
        self.assertEqual((len(violations), skipped), (1, 0))

    def test_underscore_embedded_component_is_a_violation(self) -> None:
        blob = b"\x07get_" + privacy.PRIVATE_CORPUS.encode() + b"_rows\x00"
        self.assertEqual(len(scan_bytes(blob)[0]), 1)

    def test_allowlisted_coincidence_is_skipped_and_counted(self) -> None:
        # MUST-RED: an identifier-table coincidence is a violation UNLESS a NAMED
        # allowlist entry covers its context — never a silent skip. Both the
        # coincidence and the allowlist entry are built at runtime (no literal).
        t = privacy.PRIVATE_CORPUS
        blob = b"symbol get_" + t.encode() + b"_helper end"
        # not allowlisted -> a violation, nothing skipped
        violations, skipped = scan_bytes(blob)
        self.assertEqual((len(violations), skipped), (1, 0))
        # allowlisted -> skipped and COUNTED, no violation
        violations, skipped = scan_bytes(blob, (f"get_{t}_helper",))
        self.assertEqual((len(violations), skipped), (0, 1))


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
