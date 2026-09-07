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
    NOT_PUBLISHED,
    PENDING,
    PENDING_RELEASE,
    PinError,
    is_pending,
    is_release_pending,
    load_pins,
    validate_recert,
    validate_released_binary,
    released_binary_sha,
    released_binary_state,
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


def _release_not_published(reason: str | None = "internal tool; numbers verify offline") -> dict:
    """A doc whose release binary is declared NOT PUBLISHED with a reason — the
    founder's ruling state, in which `--flip` passes without any release identity."""
    doc = _filled()
    block: dict = {"state": NOT_PUBLISHED}
    if reason is not None:
        block["reason"] = reason
    doc["recert"]["released_binary"] = block
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

    def test_committed_pin_declares_not_published_and_the_flip_passes(self) -> None:
        # The SHIPPED state after the founder's ruling: the engine is internal and
        # is not published, declared with its reason, so both gates pass. The
        # PENDING-RELEASE refusal is still asserted — on a synthetic doc, in
        # NotPublishedStateTest — because the sentinel is still a real state this
        # file could hold; it is simply no longer the one committed here.
        doc = load_pins()
        validate_recert(doc)  # measurement complete
        self.assertFalse(is_release_pending(doc))
        state, reason = released_binary_state(doc)
        self.assertEqual(state, NOT_PUBLISHED)
        self.assertTrue(reason and reason.strip(), "the absence must be explained")
        validate_released_binary(doc)  # must not raise

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

    def test_cli_both_gates_pass_on_the_committed_pin(self) -> None:
        from ttg import cli

        # Both gates pass on the committed pin: the measurement is complete and
        # the release-binary position is RESOLVED (not-published, with a reason).
        self.assertEqual(cli.main(["validate-pins"]), 0)
        self.assertEqual(cli.main(["validate-pins", "--flip"]), 0)

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

    # --- EVERY url in the file, under a rule that FITS it ------------------
    #
    # The checks above walk `[[artifacts.files]]`, which is what
    # `artifact_targets` reads. PIN.toml carries urls OUTSIDE that array —
    # `[binary].url` and `[recert.cli_artifact].url` — and nothing looked at
    # them, so a url could point at an asset that no longer exists while the
    # authority file kept publishing it.
    #
    # The two shapes are NOT interchangeable, so there is no single regex:
    # GitHub release urls end `/download/<release_tag>/<asset>`, while the CLI
    # artifact is a different host and path grammar with no tag/asset pair at
    # all. One widened pattern would either fail on the CLI url or — the worse
    # outcome — skip what it could not parse while reporting success. So: a rule
    # per table, and a COUNT assertion proving every url in the parsed document
    # got one. A future table cannot slip past by being unrecognised.

    @staticmethod
    def _every_url(node: object, path: str = "") -> list[tuple[str, str, dict]]:
        """Every `(path, url, owning table)` in the parsed document.

        Walks the PARSED doc rather than grepping text, so a url added in a new
        section is covered the day it lands, not the day someone remembers to
        extend a list."""
        found: list[tuple[str, str, dict]] = []
        if isinstance(node, dict):
            for key, value in node.items():
                where = f"{path}.{key}" if path else key
                if key == "url" and isinstance(value, str):
                    found.append((where, value, node))
                else:
                    found.extend(ArtifactUrlConsistencyTest._every_url(value, where))
        elif isinstance(node, list):
            for i, value in enumerate(node):
                found.extend(
                    ArtifactUrlConsistencyTest._every_url(value, f"{path}[{i}]")
                )
        return found

    @staticmethod
    def _rule(where: str, owner: dict, doc: dict) -> tuple[str, str]:
        """`(how, fragment)` — the rule for THIS table: `("endswith", …)` for a
        GitHub release url, `("contains", …)` for the CLI artifact's grammar.

        Two named modes rather than one clever predicate, because the two url
        shapes really are different and a reader has to be able to see which rule
        applied. Raises for a url no rule covers, so an unrecognised table fails
        loudly instead of being skipped quietly."""
        if where == "recert.cli_artifact.url":
            # A different host and grammar: no tag/asset pair. The version it
            # must agree with is [recert].target_release — the field that would
            # be bumped at the next re-cert — so a version changed there and not
            # here is caught. cli_artifact carries no version or platform field
            # of its own to cross-check against.
            return "contains", f"/releases/{doc['recert']['target_release']}/"
        tag = owner.get("release_tag", doc.get("artifacts", {}).get("release_tag"))
        asset = owner.get("name") or owner.get("asset_name")
        if not (tag and asset):
            raise AssertionError(f"{where}: no rule covers this url")
        return "endswith", f"/download/{tag}/{asset}"

    def _offenders(self, doc: dict) -> tuple[list[str], int]:
        urls = self._every_url(doc)
        offenders = []
        for where, url, owner in urls:
            how, fragment = self._rule(where, owner, doc)
            ok = url.endswith(fragment) if how == "endswith" else fragment in url
            if not ok:
                offenders.append(where)
        return offenders, len(urls)

    def test_every_url_in_the_file_is_checked_and_agrees(self) -> None:
        doc = tomllib.loads((PKG / "PIN.toml").read_text())
        offenders, examined = self._offenders(doc)
        self.assertEqual(offenders, [], "a url disagrees with its own table's fields")
        # The count assertion: every url key in the document got a rule. Without
        # it, an unrecognised table could be skipped and the suite still green.
        self.assertEqual(
            examined,
            len(self._every_url(doc)),
            "some url was not examined — a silent skip is the failure this guards",
        )
        self.assertEqual(examined, 16, "PIN.toml carries 16 urls: 14 artifacts.files + binary + cli_artifact")

    def test_a_url_outside_artifacts_files_is_still_caught(self) -> None:
        """MUST-RED the old checks could not make: perturb `[binary].url`, which
        is outside `[[artifacts.files]]` entirely."""
        doc = tomllib.loads((PKG / "PIN.toml").read_text())
        doc["binary"]["url"] = "https://github.com/x/y/releases/download/GONE/deleted-asset"
        offenders, _ = self._offenders(doc)
        self.assertIn("binary.url", offenders)

    def test_a_cli_artifact_version_bumped_without_its_url_is_caught(self) -> None:
        """MUST-RED for the second grammar: bump the version in
        [recert].target_release and leave the CLI url pointing at the old one."""
        doc = tomllib.loads((PKG / "PIN.toml").read_text())
        doc["recert"]["target_release"] = "v9.9.9"
        offenders, _ = self._offenders(doc)
        self.assertIn("recert.cli_artifact.url", offenders)

    def test_a_url_no_rule_covers_fails_loudly(self) -> None:
        """A future table with a url and no tag/asset must RAISE, not be skipped:
        the silent-skip path is the one that would let a 404 through."""
        doc = tomllib.loads((PKG / "PIN.toml").read_text())
        doc["some_future_table"] = {"url": "https://example.test/thing"}
        with self.assertRaises(AssertionError):
            self._offenders(doc)



class NotPublishedStateTest(unittest.TestCase):
    """The founder ruled the eval binary is an INTERNAL tool and is not published.

    The contract forbids a SILENT absence, so "not published" is a declared state
    carrying its reason — never a blank field and never the PENDING-RELEASE
    sentinel, which means "not published YET" and is a different claim.
    """

    def test_not_published_with_a_reason_passes_the_flip_gate(self) -> None:
        validate_released_binary(_release_not_published())  # must not raise

    def test_not_published_without_a_reason_is_REFUSED(self) -> None:
        # MUST-RED: an unexplained absence is exactly what the artifact contract
        # forbids. A state with no reason is a silent absence wearing a label.
        with self.assertRaises(PinError):
            validate_released_binary(_release_not_published(reason=None))

    def test_a_blank_reason_is_REFUSED(self) -> None:
        for blank in ("", "   ", "\t"):
            with self.assertRaises(PinError):
                validate_released_binary(_release_not_published(reason=blank))

    def test_pending_release_is_still_REFUSED(self) -> None:
        # The old sentinel keeps its meaning: "not published YET", still a refusal.
        doc = _filled()
        doc["recert"]["released_binary"] = {
            "release_tag": PENDING_RELEASE,
            "asset_name": PENDING_RELEASE,
            "sha256": PENDING_RELEASE,
        }
        with self.assertRaises(PinError):
            validate_released_binary(doc)

    def test_the_three_markers_are_pairwise_DISTINCT(self) -> None:
        # PENDING-RUN (measurement pending), PENDING-RELEASE (publication pending),
        # not-published (publication ruled out) are three different claims. One
        # shared string would let filling one silently satisfy another.
        markers = {PENDING, PENDING_RELEASE, NOT_PUBLISHED}
        self.assertEqual(len(markers), 3)

    def test_a_filled_release_identity_still_passes(self) -> None:
        # The publishing path is not removed, only no longer the only accepted one.
        validate_released_binary(_release_filled())  # must not raise

    def test_not_published_yields_no_release_sha(self) -> None:
        self.assertIsNone(released_binary_sha(_release_not_published()))


if __name__ == "__main__":
    unittest.main()
