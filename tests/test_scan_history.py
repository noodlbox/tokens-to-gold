"""R18: the git-history privacy scan on BOTH surfaces — the held-out corpus name
must appear in no commit MESSAGE and in no committed CONTENT (both ship in every
clone). Offline by construction: the message parser is tested from synthetic log
text; the content scanner is tested against a scratch repo whose planted commit
is REMOVED by a later commit (a clean tip, dirty history — the axis the earlier
guards missed); the live scan over THIS repo is asserted clean.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

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

    def test_larger_word_substring_is_flagged(self) -> None:
        # SUBSTRING GATE (RULED c): the token inside a larger word (a letter on
        # either side) IS a hit — the history scan is the substring gate, no
        # boundary exception, same as every other text surface.
        t = privacy.PRIVATE_CORPUS
        log = f"dddddddddddd\x1fword tor{t}ge in the body\n\x1e"
        self.assertEqual(cli._history_offenders(log), ["dddddddddddd"])


class ContentCarrierTest(unittest.TestCase):
    """MUST-RED (content-across-history axis): a commit whose BLOB carries the
    token, REMOVED by a later commit, leaves a CLEAN tip yet ships in every clone.
    `_content_carriers` (the new authoritative surface) REPORTS the carrying
    commit; the message scan and a tip-only scan do NOT — the wrong-axis miss.
    The token is built at runtime through the resolver, never a literal here."""

    def _git(self, repo: Path, *args: str) -> str:
        out = subprocess.run(
            ["git", "-c", "user.email=t@t", "-c", "user.name=t", *args],
            cwd=repo, capture_output=True, text=True, check=True,
        )
        return out.stdout

    def _scratch_repo(self, tmp: Path) -> tuple[Path, str]:
        """A repo whose first commit's blob carries the token and whose second
        commit removes it. Returns (repo, carrying_sha12)."""
        repo = tmp / "scratch"
        repo.mkdir()
        self._git(repo, "init", "-q")
        token = privacy.PRIVATE_CORPUS  # resolved, never a literal
        f = repo / "notes.sql"
        f.write_text(f"-- select rows for {token} here\n")
        self._git(repo, "add", "notes.sql")
        # CLEAN message — the message surface must NOT catch this.
        self._git(repo, "commit", "-q", "-m", "add notes")
        carrier = self._git(repo, "rev-parse", "HEAD").strip()[:12]
        # A later commit REMOVES the token: the tip tree is now clean.
        f.write_text("-- select rows here\n")
        self._git(repo, "add", "notes.sql")
        self._git(repo, "commit", "-q", "-m", "scrub notes")
        return repo, carrier

    def test_content_scan_reports_the_carrier_the_other_surfaces_miss(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            repo, carrier = self._scratch_repo(Path(tmpdir))

            # NEW authoritative content surface: the carrier IS reported.
            examined, carriers = cli._content_carriers(repo)
            self.assertEqual(examined, 2)
            self.assertEqual(carriers, [carrier])

            # OLD message surface: GREEN (messages are clean) — the wrong axis.
            log = self._git(repo, "log", "--format=%H%x1f%B%x1e")
            self.assertEqual(cli._history_offenders(log), [])

            # Tip-tree surface (T6's axis): GREEN — the tip is clean, proving the
            # carrier survives only in history.
            tip_clean = subprocess.run(
                ["git", "grep", "-F", "-i", "-q", "-e", privacy.PRIVATE_CORPUS, "HEAD"],
                cwd=repo, capture_output=True, text=True,
            )
            self.assertEqual(tip_clean.returncode, 1)  # 1 == no match at the tip


class ScanHistoryCliTest(unittest.TestCase):
    def test_this_repos_history_is_clean(self) -> None:
        # The live R18 gate over THIS repo's full history: exit 0 (clean on BOTH
        # the message and the content surface).
        self.assertEqual(cli.main(["scan-history"]), 0)


if __name__ == "__main__":
    unittest.main()
