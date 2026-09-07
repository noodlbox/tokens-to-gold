"""R15/R17 + G1/G2: the privacy-scan-binary release gate.

The bytes tier is the SAME scanner as the text tier: `scan_bytes` decodes with
`latin-1` (bijective, so a byte-substring scan is exactly a text-substring scan)
and delegates to `scan_text`, inheriting the identifier-scoped `AllowEntry` walk.
The window-scoped `tuple[str, ...]` allowlist is GONE — a window form can excuse
a hit two identifiers away, which is the shape ruled against for the text tier.

Every plant is assembled from the resolver at runtime; this file contains no
token literal and no token fragment spelled contiguously.
"""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from ttg import privacy
from ttg.privacy import AllowEntry, PrivacyError, scan_bytes

ASSET = "artifact.bin"


class ScanBytesTest(unittest.TestCase):
    def test_embedded_token_is_found(self) -> None:
        blob = b"\x00\x01-- get " + privacy.PRIVATE_CORPUS.encode() + b" rows\x00\xff"
        violations, allowlisted = scan_bytes(blob, ASSET)
        self.assertEqual((len(violations), allowlisted), (1, {}))
        _offset, ctx = violations[0]
        # The reported context is REDACTED — the gate output is not a leak (b7).
        self.assertIn(privacy.REDACTION, ctx)
        self.assertNotIn(privacy.PRIVATE_CORPUS, ctx)

    def test_clean_binary_has_no_hit(self) -> None:
        self.assertEqual(scan_bytes(b"\x00 hello world get_data() \xff\xfe", ASSET), ([], {}))

    def test_in_word_occurrence_is_a_violation(self) -> None:
        blob = b"xx tor" + privacy.PRIVATE_CORPUS.encode() + b"ge yy"
        self.assertEqual(len(scan_bytes(blob, ASSET)[0]), 1)

    def test_underscore_embedded_component_is_a_violation(self) -> None:
        blob = b"\x07get_" + privacy.PRIVATE_CORPUS.encode() + b"_rows\x00"
        self.assertEqual(len(scan_bytes(blob, ASSET)[0]), 1)

    # --- the six ruled must-reds, on the bytes tier ------------------------

    def test_i_enclosing_run_without_the_pattern_is_a_violation(self) -> None:
        """(i) IDENTIFIER-scoped, not window-scoped: the pattern sits in the ±24
        WINDOW but not in the hit's own enclosing run -> violation."""
        t = privacy.PRIVATE_CORPUS
        entry = AllowEntry("seam", ASSET, "MismatchTimeZone", "test")
        blob = b"MismatchTimeZone ; unrelated_" + t.encode() + b"_ident"
        violations, allowlisted = scan_bytes(blob, ASSET, (entry,))
        self.assertEqual((len(violations), allowlisted), (1, {}))

    def test_ii_same_run_under_a_different_asset_is_a_violation(self) -> None:
        """(ii) ASSET-scoped: the identical benign run in another asset fails."""
        t = privacy.PRIVATE_CORPUS
        entry = AllowEntry("seam", ASSET, "MismatchTimeZone", "test")
        blob = b"MismatchTimeZone" + t.encode() + b"largest"
        self.assertEqual(scan_bytes(blob, ASSET, (entry,))[1], {"seam": 1})
        violations, allowlisted = scan_bytes(blob, "other.bin", (entry,))
        self.assertEqual((len(violations), allowlisted), (1, {}))

    def test_iii_the_seam_shape_is_allowlisted_only_with_the_pattern(self) -> None:
        """(iii) the R22 jiff seam: two abutting identifiers spell the token
        across the boundary. With the entry -> 0 violations / 1 allowlisted;
        with the pattern absent from the run -> violation."""
        t = privacy.PRIVATE_CORPUS
        entry = AllowEntry("seam", ASSET, "MismatchTimeZone", "test")
        seam = b"MismatchTimeZone" + t.encode() + b"largestFilePathError"
        violations, allowlisted = scan_bytes(seam, ASSET, (entry,))
        self.assertEqual((len(violations), allowlisted), (0, {"seam": 1}))
        without = b"SomeOtherType" + t.encode() + b"largestFilePathError"
        self.assertEqual(len(scan_bytes(without, ASSET, (entry,))[0]), 1)

    def test_iv_prose_can_never_be_allowlisted_by_any_entry(self) -> None:
        """(iv) THE G3 GUARANTEE: an R17-shaped prose hit's enclosing run is the
        BARE token, so no identifier entry can ever cover it."""
        t = privacy.PRIVATE_CORPUS
        entry = AllowEntry("seam", ASSET, "MismatchTimeZone", "test")
        prose = b"-- Measured on a " + t.encode() + b"-scale catalog (31,622 rows)"
        violations, allowlisted = scan_bytes(prose, ASSET, (entry,))
        self.assertEqual((len(violations), allowlisted), (1, {}))

    def test_v_latin1_high_bytes_do_not_extend_an_identifier_run(self) -> None:
        """(v) the identifier class is explicit ASCII [A-Za-z0-9_]. Under
        latin-1, bytes 0xC0-0xFF decode to accented letters that `str.isalnum()`
        accepts; if they extended the run, binary garbage could carry a pattern
        into a hit's 'identifier' and widen what an entry covers."""
        t = privacy.PRIVATE_CORPUS
        entry = AllowEntry("seam", ASSET, "MismatchTimeZone", "test")
        # 0xC9 is a high byte; the pattern is separated from the hit by it, so the
        # enclosing ASCII run around the token must NOT reach the pattern.
        blob = b"MismatchTimeZone\xc9" + t.encode()
        violations, allowlisted = scan_bytes(blob, ASSET, (entry,))
        self.assertEqual((len(violations), allowlisted), (1, {}))

    def test_vi_an_entry_whose_pattern_is_part_of_the_token_RAISES(self) -> None:
        """(vi, the rider): an entry whose pattern is a case-insensitive
        substring of the token would match the BARE-token run and allowlist
        prose, destroying the (iv) guarantee. Validated at the scanner entry,
        before the first byte is examined: a REFUSAL, never a violation, never a
        silent skip. The fragment is built at runtime — no literal here."""
        t = privacy.PRIVATE_CORPUS
        fragment = t[: max(1, len(t) - 1)]
        bad = AllowEntry("bad", ASSET, fragment, "test")
        with self.assertRaises(PrivacyError):
            scan_bytes(b"anything", ASSET, (bad,))
        # the whole token as a pattern is refused too, and casing does not evade
        with self.assertRaises(PrivacyError):
            scan_bytes(b"anything", ASSET, (AllowEntry("bad", ASSET, t.upper(), "t"),))
        # the R22 entry pattern passes validation trivially
        scan_bytes(b"anything", ASSET, (AllowEntry("seam", ASSET, "MismatchTimeZone", "t"),))


class BinaryAllowlistTest(unittest.TestCase):
    def test_ships_empty_until_r22_supplies_evidence(self) -> None:
        """G2: the MECHANISM ships now; the seam entry is added only at R22 with
        the empirical confirmation attached, so it cannot be added without it."""
        self.assertEqual(privacy.BINARY_ALLOWLIST, ())

    def test_every_shipped_entry_validates_against_the_token(self) -> None:
        for entry in privacy.BINARY_ALLOWLIST + privacy.TEXT_ALLOWLIST:
            entry.validate(privacy.PRIVATE_CORPUS)


class ScanBinaryCliTest(unittest.TestCase):
    def _run(self, blob: bytes, *extra: str) -> int:
        from ttg import cli

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / ASSET  # fresh throwaway path
            path.write_bytes(blob)
            return cli.main(["scan-binary", "--path", str(path), *extra])

    def test_cli_refuses_on_hit(self) -> None:
        self.assertEqual(self._run(b"-- " + privacy.PRIVATE_CORPUS.encode() + b" --"), 1)

    def test_cli_allows_clean(self) -> None:
        self.assertEqual(self._run(b"clean artifact bytes"), 0)

    def test_cli_refuses_when_expectation_is_unmet(self) -> None:
        """--expect-allowlisted turns the pre-registered count into a gate: a
        clean scan that allowlisted NOTHING must still fail when one was
        expected, so R22 cannot pass by scanning the wrong artifact."""
        self.assertEqual(self._run(b"clean bytes", "--expect-allowlisted", "seam=1"), 1)

    def test_cli_accepts_a_met_expectation(self) -> None:
        self.assertEqual(self._run(b"clean bytes", "--expect-allowlisted", "seam=0"), 0)

    def test_cli_rejects_a_malformed_expectation(self) -> None:
        self.assertEqual(self._run(b"clean bytes", "--expect-allowlisted", "seam"), 2)


if __name__ == "__main__":
    unittest.main()
