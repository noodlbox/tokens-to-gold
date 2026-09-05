"""A4 re-cert pin gate: a half-filled pin must be unusable.

The re-cert pins are prepared before the lease run, so the danger is not a
missing file — it is a pin that LOOKS complete. Every way of being unfilled
(the sentinel, a missing key, a blank string, a malformed digest) must be
refused, and the shipped PIN.toml must currently be refused, because the run
has not happened yet.
"""

from __future__ import annotations

import copy
import tomllib
import unittest
from pathlib import Path

from ttg.pins import PENDING, PinError, is_pending, load_pins, validate_recert

PKG = Path(__file__).resolve().parent.parent


def _filled() -> dict:
    doc = copy.deepcopy(dict(load_pins()))
    doc["recert"] = copy.deepcopy(dict(doc["recert"]))
    doc["recert"]["status"] = "COMPLETE"
    doc["recert"]["binary"] = {
        "eval_features": "rust-analysis",
        "build_commit": "573bfcfb2",
        "sha256": "a" * 64,
    }
    return doc


class ShippedPinTest(unittest.TestCase):
    def test_shipped_pin_is_pending_and_refused(self) -> None:
        doc = load_pins()
        self.assertTrue(is_pending(doc))
        with self.assertRaises(PinError):
            validate_recert(doc)

    def test_cli_artifact_sha_is_pinned_and_well_formed(self) -> None:
        art = load_pins()["recert"]["cli_artifact"]
        self.assertEqual(len(art["sha256"]), 64)
        self.assertTrue(art["url"].endswith("/v2.3.18/macos-arm64/nbx.tar.gz"))

    def test_pin_file_parses_and_keeps_the_v1_sections(self) -> None:
        doc = tomllib.loads((PKG / "PIN.toml").read_text())
        for section in ("repo", "binary", "artifacts", "gold", "provenance"):
            self.assertIn(section, doc, f"V1 section [{section}] must survive")


class RefusalTest(unittest.TestCase):
    def test_a_fully_filled_pin_is_accepted(self) -> None:
        validate_recert(_filled())  # must not raise

    def test_sentinel_in_any_binary_field_is_refused(self) -> None:
        for field in ("build_commit", "sha256", "eval_features"):
            doc = _filled()
            doc["recert"]["binary"][field] = PENDING
            with self.assertRaises(PinError, msg=field):
                validate_recert(doc)

    def test_blank_or_missing_is_refused_not_treated_as_absent(self) -> None:
        for bad in ("", "   "):
            doc = _filled()
            doc["recert"]["binary"]["build_commit"] = bad
            with self.assertRaises(PinError):
                validate_recert(doc)
        doc = _filled()
        del doc["recert"]["binary"]["sha256"]
        with self.assertRaises(PinError):
            validate_recert(doc)

    def test_malformed_digest_or_commit_is_refused(self) -> None:
        doc = _filled()
        doc["recert"]["binary"]["sha256"] = "not-a-digest"
        with self.assertRaises(PinError):
            validate_recert(doc)
        doc = _filled()
        doc["recert"]["binary"]["build_commit"] = "zzzz"
        with self.assertRaises(PinError):
            validate_recert(doc)

    def test_status_alone_cannot_unlock_a_pending_binary(self) -> None:
        # Flipping status without filling the identity must still refuse.
        doc = _filled()
        doc["recert"]["binary"]["sha256"] = PENDING
        doc["recert"]["status"] = "COMPLETE"
        with self.assertRaises(PinError):
            validate_recert(doc)


if __name__ == "__main__":
    unittest.main()
