"""Provisioning inspection + R-B2 decider — witnessed against local git repos.

The network clone is a lease step; the load-bearing logic (tree-sha pinning,
`.rs` counting excluding nothing, the discovery-equivalence decider) is pure and
tested here against throwaway git repos, so a wrong `.rs` count — which would
silently mis-decide one-vs-two binaries — cannot ship.
"""

from __future__ import annotations

import subprocess
import tempfile
import unittest
from pathlib import Path

from ttg.provision import (
    ManifestRow,
    UnsafeCorpusInputError,
    _validated_commit,
    _validated_dest,
    _validated_url,
    inspect_checkout,
    ts_py_discovery_equivalent,
)


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True).stdout.strip()


def _repo_with(files: dict[str, str]) -> Path:
    d = Path(tempfile.mkdtemp())
    _git(d, "init", "-q")
    _git(d, "config", "user.email", "t@t")
    _git(d, "config", "user.name", "t")
    for rel, body in files.items():
        p = d / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body)
    _git(d, "add", "-A")
    _git(d, "commit", "-q", "-m", "seed")
    return d


class InspectCheckoutTest(unittest.TestCase):
    def test_counts_rs_excluding_nothing_but_dotgit(self) -> None:
        repo = _repo_with({
            "src/main.rs": "fn main() {}\n",
            "vendor/dep.rs": "// vendored still counts\n",
            "README.md": "# x\n",
            "app.py": "print(1)\n",
        })
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(repo)]))
        facts = inspect_checkout(repo)
        self.assertEqual(facts.rs_file_count, 2, "vendored .rs must count")
        self.assertEqual(facts.tree_sha, _git(repo, "rev-parse", "HEAD^{tree}"))
        self.assertEqual(len(facts.tree_sha), 40)

    def test_zero_rs_repo(self) -> None:
        repo = _repo_with({"index.ts": "export const x = 1;\n"})
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(repo)]))
        self.assertEqual(inspect_checkout(repo).rs_file_count, 0)


class DiscoveryEquivalenceTest(unittest.TestCase):
    def _row(self, iid: str, rs: int) -> ManifestRow:
        return ManifestRow(iid, "o/r", "c" * 40, "t" * 40, rs)

    def test_all_zero_is_equivalent(self) -> None:
        rows = [self._row("a", 0), self._row("b", 0)]
        self.assertTrue(ts_py_discovery_equivalent(rows))

    def test_any_nonzero_breaks_equivalence(self) -> None:
        rows = [self._row("a", 0), self._row("b", 3)]
        self.assertFalse(ts_py_discovery_equivalent(rows))


class UntrustedInputTest(unittest.TestCase):
    """The public 'run on your own repo' path feeds untrusted JSONL into git
    args and paths — these must fail closed (argument-injection + traversal)."""

    def test_commit_must_be_hex(self) -> None:
        self.assertEqual(_validated_commit("68dafce"), "68dafce")
        for bad in ("--upload-pack=x", "-e", "main", "68dafce; rm -rf /", ""):
            with self.assertRaises(UnsafeCorpusInputError):
                _validated_commit(bad)

    def test_repo_rejects_flag_and_bad_slug(self) -> None:
        self.assertEqual(_validated_url("o/r"), "https://github.com/o/r.git")
        self.assertEqual(_validated_url("https://x/y"), "https://x/y")
        for bad in ("--upload-pack=x", "-o/r", "not a slug", "a/b/c", "/etc"):
            with self.assertRaises(UnsafeCorpusInputError):
                _validated_url(bad)

    def test_instance_id_cannot_escape_the_root(self) -> None:
        root = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(root)]))
        self.assertEqual(_validated_dest(root, "good-id"), (root / "good-id").resolve())
        for bad in ("..", ".", "../evil", "a/b", "/abs", "x/../..", ""):
            with self.assertRaises(UnsafeCorpusInputError):
                _validated_dest(root, bad)


if __name__ == "__main__":
    unittest.main()
