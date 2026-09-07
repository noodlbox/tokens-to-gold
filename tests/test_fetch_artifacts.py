"""fetch-artifacts: the pinned-attachment fetch + sha-verify gate (A5).

Offline by construction — the sha-verify logic and the target parsing are tested
without the network; the live `gh release download` is exercised by the
acceptance workflow post-R16-upload.
"""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ttg import cli
from ttg.pins import ArtifactTarget, artifact_targets, load_pins


class VerifyArtifactTest(unittest.TestCase):
    def test_match_mismatch_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            f = Path(tmp) / "x.json"
            f.write_bytes(b"hello")
            good = hashlib.sha256(b"hello").hexdigest()
            self.assertIsNone(cli._verify_artifact(f, good))
            self.assertIn("sha", cli._verify_artifact(f, "0" * 64))
            self.assertIn("not present", cli._verify_artifact(Path(tmp) / "no.json", good))


class ArtifactTargetsTest(unittest.TestCase):
    def test_pin_targets_split_by_tag(self) -> None:
        targets = artifact_targets(load_pins())
        names = {t.name for t in targets}
        # the 12 re-cert reports + the V1 deepswe pair are the ONLY fetch targets.
        self.assertIn("native_floor_ts40.json", names)
        self.assertIn("shipped_treatment_go34.json", names)
        self.assertIn("deepswe_frozen_ts40.json", names)
        recert = [t for t in targets if t.name.endswith(".json") and not t.name.startswith("deepswe")]
        self.assertEqual(len(recert), 12, sorted(t.name for t in recert))
        self.assertTrue(all(t.release_tag == "v1-2.3.18" for t in recert))
        deepswe = [t for t in targets if t.name.startswith("deepswe")]
        self.assertEqual(len(deepswe), 2)
        self.assertTrue(all(t.release_tag == "v1.0.0-rc1" for t in deepswe))

    def test_no_binary_is_a_fetch_target(self) -> None:
        # Binary-drop: a binary file digest is not a reproduction target
        # (BUNDLE.md contract row 13), so `artifact_targets` fetches 14 files —
        # the 12 re-cert reports + the 2 V1 reports — and NO binary. Every
        # target is a .json report.
        targets = artifact_targets(load_pins())
        self.assertEqual(len(targets), 14, sorted(t.name for t in targets))
        self.assertTrue(
            all(t.name.endswith(".json") for t in targets),
            [t.name for t in targets if not t.name.endswith(".json")],
        )
        self.assertFalse(any("noodl-eval" in t.name for t in targets))


class FetchArtifactsCliTest(unittest.TestCase):
    def test_verify_only_refuses_when_absent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(cli.main(["fetch-artifacts", "--out", tmp, "--verify-only"]), 1)

    def test_verify_only_green_on_matching_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.json").write_bytes(b"data")
            sha = hashlib.sha256(b"data").hexdigest()
            with mock.patch.object(
                cli, "artifact_targets", return_value=[ArtifactTarget("a.json", sha, "vX")]
            ):
                self.assertEqual(cli.main(["fetch-artifacts", "--out", tmp, "--verify-only"]), 0)

    def test_verify_only_refuses_on_corrupt_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "a.json").write_bytes(b"tampered")
            sha = hashlib.sha256(b"original").hexdigest()
            with mock.patch.object(
                cli, "artifact_targets", return_value=[ArtifactTarget("a.json", sha, "vX")]
            ):
                self.assertEqual(cli.main(["fetch-artifacts", "--out", tmp, "--verify-only"]), 1)


if __name__ == "__main__":
    unittest.main()
