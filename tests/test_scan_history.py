"""R18b: the git-history privacy scan — the held-out corpus name must not appear
in any commit message (they ship in every clone). Offline by construction: the
record parser is tested from synthetic log text; the live scan over THIS repo's
history is asserted clean.
"""

from __future__ import annotations

import unittest

from ttg import cli, privacy


class HistoryOffendersTest(unittest.TestCase):
    def test_flags_the_commit_naming_the_corpus(self) -> None:
        t = privacy.PRIVATE_CORPUS
        log = f"aaaaaaaaaaaa\x1fclean subject\n\x1ebbbbbbbbbbbb\x1fmention {t} here\n\x1e"
        self.assertEqual(cli._history_offenders(log), ["bbbbbbbbbbbb"])

    def test_clean_history_has_no_offenders(self) -> None:
        log = "aaaaaaaaaaaa\x1fdocs: the held-out corpus, referred to safely\n\x1e"
        self.assertEqual(cli._history_offenders(log), [])

    def test_multiline_body_is_one_record(self) -> None:
        t = privacy.PRIVATE_CORPUS
        log = f"cccccccccccc\x1fsubject line\n\nbody names {t}\ntrailer\n\x1e"
        self.assertEqual(cli._history_offenders(log), ["cccccccccccc"])

    def test_larger_word_substring_is_not_flagged(self) -> None:
        # NEGATIVE CONTROL: the token inside a larger word (a letter on either
        # side) is not a hit — the same boundary rule as the file scan.
        t = privacy.PRIVATE_CORPUS
        log = f"dddddddddddd\x1fword tor{t}ge in the body\n\x1e"
        self.assertEqual(cli._history_offenders(log), [])


class ScanHistoryCliTest(unittest.TestCase):
    def test_this_repos_history_is_clean(self) -> None:
        # The live R18b gate over THIS repo's full history: exit 0 (clean).
        self.assertEqual(cli.main(["scan-history"]), 0)


if __name__ == "__main__":
    unittest.main()
