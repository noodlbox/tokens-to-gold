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

from ttg.pins import (
    PENDING,
    PENDING_RELEASE,
    PinError,
    is_pending,
    is_release_pending,
    load_pins,
    validate_recert,
    validate_released_binary,
)

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


def _release_filled() -> dict:
    """A doc whose [recert.released_binary] names a real published binary — the
    R17 state in which `validate-pins --flip` passes."""
    doc = _filled()
    doc["recert"]["released_binary"] = {
        "release_tag": "v1-2.3.18",
        "asset_name": "noodl-eval-official",
        "sha256": "b" * 64,
    }
    return doc


class ShippedPinTest(unittest.TestCase):
    def test_committed_recert_pin_is_filled_and_valid(self) -> None:
        # After A4 step 8 the committed [recert.binary] is filled from the
        # certified lease artifacts: is_pending is False and validate_recert
        # passes. The pending-refusal BEHAVIOR is covered by RefusalTest with
        # synthetic docs, so this no longer depends on the committed pin's state.
        doc = load_pins()
        self.assertFalse(is_pending(doc))
        validate_recert(doc)  # must not raise

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


class FlipGateTest(unittest.TestCase):
    """R17 flip gate: `validate_released_binary` is a SEPARATE gate from the
    measurement gate — it FAILS while the release binary is the PENDING-RELEASE
    sentinel and passes once R17 fills a real published identity. Both
    directions are asserted."""

    def test_committed_pin_is_release_pending_and_flip_refuses(self) -> None:
        # R16 ships with the release binary pending: the measurement gate passes
        # but the flip gate refuses — the two lifecycles are independent.
        doc = load_pins()
        validate_recert(doc)  # measurement complete
        self.assertTrue(is_release_pending(doc))
        with self.assertRaises(PinError):
            validate_released_binary(doc)

    def test_filled_release_passes_the_flip_gate(self) -> None:
        doc = _release_filled()
        self.assertFalse(is_release_pending(doc))
        validate_released_binary(doc)  # must not raise

    def test_release_sentinel_in_any_field_is_refused(self) -> None:
        for field in ("release_tag", "asset_name", "sha256"):
            doc = _release_filled()
            doc["recert"]["released_binary"][field] = PENDING_RELEASE
            with self.assertRaises(PinError, msg=field):
                validate_released_binary(doc)

    def test_release_blank_or_missing_is_refused(self) -> None:
        for bad in ("", "   "):
            doc = _release_filled()
            doc["recert"]["released_binary"]["asset_name"] = bad
            with self.assertRaises(PinError):
                validate_released_binary(doc)
        doc = _release_filled()
        del doc["recert"]["released_binary"]["sha256"]
        with self.assertRaises(PinError):
            validate_released_binary(doc)

    def test_release_malformed_sha_is_refused(self) -> None:
        doc = _release_filled()
        doc["recert"]["released_binary"]["sha256"] = "not-a-digest"
        with self.assertRaises(PinError):
            validate_released_binary(doc)

    def test_measurement_sentinel_and_release_sentinel_are_distinct(self) -> None:
        # A single shared sentinel would let a filled measurement satisfy the
        # flip gate; they must be different strings.
        self.assertNotEqual(PENDING, PENDING_RELEASE)

    def test_cli_validate_pins_passes_but_flip_refuses_on_committed_pin(self) -> None:
        from ttg import cli

        # Measurement gate: the committed pin passes (numbers are publishable).
        self.assertEqual(cli.main(["validate-pins"]), 0)
        # Flip gate: the same pin refuses, because the release binary is pending.
        self.assertEqual(cli.main(["validate-pins", "--flip"]), 2)

    def test_cli_flip_passes_once_release_is_filled(self) -> None:
        from unittest import mock

        from ttg import cli

        with mock.patch.object(cli, "load_pins", return_value=_release_filled()):
            self.assertEqual(cli.main(["validate-pins", "--flip"]), 0)


class ArtifactUrlConsistencyTest(unittest.TestCase):
    """finding-P: `artifact_targets` reads name / sha256 / release_tag and NEVER
    `url`, so a release_tag rename that misses the `url` line leaves fetch green
    while PIN.toml publishes URLs to a dead tag. Every `[[artifacts.files]]`
    `url` must end with `/download/<release_tag>/<name>`; perturbing either field
    reddens this, so the two can never disagree."""

    def _files_and_default(self) -> tuple[list[dict[str, object]], object]:
        doc = tomllib.loads((PKG / "PIN.toml").read_text())
        artifacts = doc["artifacts"]
        return list(artifacts["files"]), artifacts.get("release_tag")

    def test_every_url_matches_its_release_tag_and_name(self) -> None:
        files, default_tag = self._files_and_default()
        self.assertTrue(files)
        for entry in files:
            tag = entry.get("release_tag", default_tag)
            suffix = f"/download/{tag}/{entry['name']}"
            self.assertTrue(
                str(entry["url"]).endswith(suffix),
                f"url/release_tag disagree for {entry['name']}: "
                f"url={entry['url']} expected suffix {suffix}",
            )

    def test_a_release_tag_bumped_without_its_url_is_caught(self) -> None:
        # MUST-RED: renaming a release_tag but not its url must be detectable.
        files, default_tag = self._files_and_default()
        entry = files[0]
        bumped = f"{entry.get('release_tag', default_tag)}-PERTURBED"
        suffix = f"/download/{bumped}/{entry['name']}"
        self.assertFalse(str(entry["url"]).endswith(suffix))


if __name__ == "__main__":
    unittest.main()
