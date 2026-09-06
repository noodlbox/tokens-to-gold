"""R18a: the privacy token resolver, its self-canary, and the plant cycle.

Every must-red obtains the plant token THROUGH the resolver, so the test can
never drift from what production resolves; the plant/scrub/detect cycle runs in
BOTH modes. Reverting any one guard turns its must-red RED:
  * resolve() external arm -> a silent in-module fallback: the absent/empty
    tests stop raising;
  * _self_canary -> a no-op: the wrong-token test stops aborting;
  * _matcher -> case-sensitive: the mixed-case scrub test leaks casings.
"""

from __future__ import annotations

import os
import unittest
from unittest import mock

from ttg import privacy


class ResolverTest(unittest.TestCase):
    def test_default_is_in_module(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            mode, token = privacy.resolve()
        self.assertEqual(mode, privacy.MODE_IN_MODULE)
        self.assertTrue(token)

    def test_external_absent_throws(self) -> None:
        # MUST-RED: MODE=external but no token env -> works-or-throws.
        with mock.patch.dict(
            os.environ, {"TTG_PRIVATE_CORPUS_MODE": "external"}, clear=True
        ):
            with self.assertRaises(privacy.PrivacyError):
                privacy.resolve()

    def test_external_empty_throws(self) -> None:
        # MUST-RED: present but blank is empty -> throws, never a fallback.
        with mock.patch.dict(
            os.environ,
            {"TTG_PRIVATE_CORPUS_MODE": "external", "TTG_PRIVATE_CORPUS": "   "},
            clear=True,
        ):
            with self.assertRaises(privacy.PrivacyError):
                privacy.resolve()

    def test_external_present_resolves(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"TTG_PRIVATE_CORPUS_MODE": "external", "TTG_PRIVATE_CORPUS": "SecretCorp"},
            clear=True,
        ):
            mode, token = privacy.resolve()
        self.assertEqual(mode, privacy.MODE_EXTERNAL)
        self.assertEqual(token, "secretcorp")  # normalized to lowercase

    def test_unknown_mode_throws(self) -> None:
        with mock.patch.dict(
            os.environ, {"TTG_PRIVATE_CORPUS_MODE": "sideways"}, clear=True
        ):
            with self.assertRaises(privacy.PrivacyError):
                privacy.resolve()

    def test_mode_reports_name_never_value(self) -> None:
        self.assertIn(privacy.mode(), (privacy.MODE_IN_MODULE, privacy.MODE_EXTERNAL))
        self.assertNotIn(privacy.PRIVATE_CORPUS, privacy.mode())


class SelfCanaryTest(unittest.TestCase):
    def test_matching_token_passes(self) -> None:
        privacy._self_canary(privacy.PRIVATE_CORPUS, privacy.contains_private)

    def test_wrong_token_aborts(self) -> None:
        # MUST-RED: a token the live matcher does not detect -> canary aborts.
        with self.assertRaises(privacy.PrivacyError):
            privacy._self_canary(
                "a-token-the-matcher-will-not-find", privacy.contains_private
            )


class ScrubTest(unittest.TestCase):
    def test_mixed_case_all_redacted(self) -> None:
        # MUST-RED: one case-insensitive matcher, so scrub redacts EVERY casing
        # (the mixed-case bug: previously DETECTED but left un-redacted).
        token = privacy.PRIVATE_CORPUS
        text = f"{token.upper()} {token.capitalize()} {token}"
        scrubbed = privacy.scrub(text)
        self.assertNotIn(token, scrubbed.lower())
        self.assertEqual(scrubbed.count(privacy.REDACTION), 3)


class BoundaryTest(unittest.TestCase):
    """Fold I: the token embedded in a larger WORD does not match; a whole word
    and an underscore-separated identifier component DO. (Underscore is a
    separator here, not a word char — so the scrubber still catches the token in
    witness-log test identifiers, which `\\b` would miss.)"""

    def test_substring_of_larger_word_does_not_match(self) -> None:
        # A longer WORD that merely CONTAINS the token as a substring — a letter
        # glued on before, after, or both — must NOT match. Every example is
        # ASSEMBLED at runtime from the resolved token, so this file never spells
        # the contiguous token (a literal would be a leak the boundary matcher
        # passes but a raw content grep counts).
        t = privacy.PRIVATE_CORPUS
        self.assertFalse(privacy.contains_private("tor" + t))  # letter before
        self.assertFalse(privacy.contains_private(t + "ge"))  # letter after
        self.assertFalse(privacy.contains_private("x" + t + "9"))  # alnum both sides

    def test_whole_word_and_identifier_component_match(self) -> None:
        t = privacy.PRIVATE_CORPUS
        self.assertTrue(privacy.contains_private(t))  # standalone
        self.assertTrue(privacy.contains_private(f"the {t} corpus"))  # spaced
        self.assertTrue(privacy.contains_private(f"test_{t}_case"))  # underscore comp
        self.assertTrue(privacy.contains_private(f"corpora/{t}/x"))  # slash-delimited


class PlantCycleBothModesTest(unittest.TestCase):
    """Obtain the plant token THROUGH the resolver, then run the plant/scrub/
    detect cycle in BOTH modes."""

    def _plant_cycle(self, token: str) -> None:
        matcher = privacy._matcher(token)
        planted = f"log line for test_{token}_case here"
        self.assertTrue(matcher.search(planted))
        redacted = matcher.sub(privacy.REDACTION, planted)
        self.assertNotIn(token, redacted.lower())
        self.assertIn(privacy.REDACTION, redacted)

    def test_in_module_mode(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            mode, token = privacy.resolve()
        self.assertEqual(mode, privacy.MODE_IN_MODULE)
        self._plant_cycle(token)

    def test_external_mode(self) -> None:
        with mock.patch.dict(
            os.environ,
            {"TTG_PRIVATE_CORPUS_MODE": "external", "TTG_PRIVATE_CORPUS": "heldoutcorp"},
            clear=True,
        ):
            mode, token = privacy.resolve()
        self.assertEqual(mode, privacy.MODE_EXTERNAL)
        self._plant_cycle(token)


if __name__ == "__main__":
    unittest.main()
