"""TRIPLE must-red for the commit-msg privacy hook, run against the hook
DIRECTLY (subprocess). The three outcomes are distinguished, exactly ONE exits
0, and the verdict is NEVER 0 on a check failure.

The private token is obtained THROUGH the resolver and written to a throwaway
temp path that collides with nothing tracked.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from ttg import privacy

PKG = Path(__file__).resolve().parent.parent
HOOK = PKG / "scripts" / "git-hooks" / "commit-msg"


def _run_hook(hook: Path, message: str, cwd: Path | None = None) -> subprocess.CompletedProcess:
    with tempfile.TemporaryDirectory() as tmp:
        msg = Path(tmp) / "COMMIT_EDITMSG"  # fresh throwaway path
        msg.write_text(message, encoding="utf-8")
        env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
        return subprocess.run(
            ["bash", str(hook), str(msg)],
            capture_output=True, text=True, cwd=cwd, env=env,
        )


class CommitMsgHookTest(unittest.TestCase):
    def test_positive_names_corpus_is_refused(self) -> None:
        r = _run_hook(HOOK, f"docs: mention {privacy.PRIVATE_CORPUS} here\n")
        self.assertEqual(r.returncode, 1)
        self.assertIn("names the held-out corpus", r.stderr)
        self.assertIn("mode", r.stderr)  # the resolved MODE is reported

    def test_negative_clean_message_is_allowed(self) -> None:
        # THE DISCRIMINATOR: a verified-clean message is the ONE exit-0 path.
        r = _run_hook(HOOK, "docs: refer to the held-out corpus safely\n")
        self.assertEqual(r.returncode, 0)
        self.assertIn("mode", r.stderr)  # mode reported even on allow

    def test_induced_import_failure_is_refused_distinctly(self) -> None:
        # A GENUINE import failure: run the hook where neither its own root nor
        # the cwd has a `ttg` package (and PYTHONPATH is stripped). The verdict
        # must be non-zero (never silently allow) with a DISTINCT diagnostic —
        # not the privacy-violation message.
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "scripts" / "git-hooks"
            dest.mkdir(parents=True)
            shutil.copy(HOOK, dest / "commit-msg")
            r = _run_hook(
                dest / "commit-msg", "docs: a perfectly clean message\n", cwd=Path(tmp)
            )
        self.assertNotEqual(r.returncode, 0)  # verdict NEVER 0 on a check failure
        self.assertIn("check could not run", r.stderr)  # distinct diagnostic
        self.assertNotIn("names the held-out corpus", r.stderr)  # NOT the violation
        self.assertIn("CHECKFAIL", r.stderr)


if __name__ == "__main__":
    unittest.main()
