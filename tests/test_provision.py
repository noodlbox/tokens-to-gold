"""Provisioning inspection + R-B2 decider — witnessed against local git repos.

The network clone is a lease step; the load-bearing logic (tree-sha pinning,
`.rs` counting excluding nothing, the discovery-equivalence decider) is pure and
tested here against throwaway git repos, so a wrong `.rs` count — which would
silently mis-decide one-vs-two binaries — cannot ship.
"""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from ttg.provision import (
    CheckoutFacts,
    ManifestRow,
    UnsafeCorpusInputError,
    build_manifest,
    write_manifest,
    _validated_commit,
    _validated_dest,
    _validated_url,
    inspect_checkout,
    new_file_fraction,
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
        return ManifestRow(iid, "o/r", "c" * 40, "t" * 40, rs, 0.0)

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


class NewFileFractionTest(unittest.TestCase):
    """R-G3: the mechanical explanation for a zero-gold instance, recomputable
    by a third party from the patch alone."""

    def _patch(self, entries: list[tuple[str, bool]]) -> str:
        out = []
        for path, is_new in entries:
            out.append(f"diff --git a/{path} b/{path}")
            if is_new:
                out.append("new file mode 100644")
            out.append(f"--- a/{path}\n+++ b/{path}\n@@ -1 +1 @@\n+x")
        return "\n".join(out) + "\n"

    def test_all_new_files_is_one(self) -> None:
        self.assertEqual(
            new_file_fraction(self._patch([("a.go", True), ("b.go", True)])), 1.0)

    def test_no_new_files_is_zero(self) -> None:
        self.assertEqual(
            new_file_fraction(self._patch([("a.go", False), ("b.go", False)])), 0.0)

    def test_mixed_patch(self) -> None:
        self.assertEqual(new_file_fraction(self._patch(
            [("a.go", True), ("b.go", False), ("c.go", False), ("d.go", True)])), 0.5)

    def test_empty_patch_does_not_divide_by_zero(self) -> None:
        self.assertEqual(new_file_fraction(""), 0.0)

    def test_matches_the_measured_go34_zero_gold_shape(self) -> None:
        # dasel-html-document-format: 4 of 4 touched files created.
        self.assertEqual(new_file_fraction(self._patch(
            [(f"parsing/html/{n}.go", True)
             for n in ("html", "parser", "reader", "writer")])), 1.0)


class ManifestEmissionTest(unittest.TestCase):
    """R-P4/R-P5: the manifest is the public checkout-set proof, and a
    provisioning failure is a recorded exclusion — never a dropped instance."""

    def setUp(self) -> None:
        self.dir = Path(tempfile.mkdtemp())
        self.addCleanup(lambda: subprocess.run(["rm", "-rf", str(self.dir)]))

    def _jsonl(self, rows: list[dict]) -> Path:
        p = self.dir / "corpus.jsonl"
        p.write_text("".join(json.dumps(r) + "\n" for r in rows))
        return p

    def test_provisioning_failure_is_recorded_not_dropped(self) -> None:
        jsonl = self._jsonl([
            {"instance_id": "ok-one", "repo": "o/r", "base_commit": "a" * 40},
            {"instance_id": "bad-one", "repo": "o/r", "base_commit": "b" * 40},
        ])
        good = CheckoutFacts(tree_sha="t" * 40, rs_file_count=0)

        def fake(repo: str, base_commit: str, dest: Path) -> CheckoutFacts:
            if base_commit.startswith("b"):
                raise subprocess.CalledProcessError(
                    128, ["git", "fetch"], stderr="fatal: could not read commit")
            return good

        with mock.patch("ttg.provision.provision_instance", side_effect=fake):
            result = build_manifest(jsonl, self.dir / "checkouts")

        self.assertEqual([r.instance_id for r in result.rows], ["ok-one"])
        self.assertEqual([e.instance_id for e in result.errors], ["bad-one"])
        # nothing vanished: every input instance is in exactly one bucket
        self.assertEqual(len(result.rows) + len(result.errors), 2)
        self.assertIn("could not read commit", result.errors[0].reason)

    def test_unsafe_row_still_raises_rather_than_becoming_an_exclusion(self) -> None:
        jsonl = self._jsonl(
            [{"instance_id": "../evil", "repo": "o/r", "base_commit": "a" * 40}])
        with mock.patch("ttg.provision.provision_instance"):
            with self.assertRaises(UnsafeCorpusInputError):
                build_manifest(jsonl, self.dir / "checkouts")

    def test_manifest_carries_only_public_fields(self) -> None:
        out = self.dir / "m.jsonl"
        write_manifest([ManifestRow("i", "o/r", "c" * 40, "t" * 40, 3, 0.25)], out)
        row = json.loads(out.read_text().splitlines()[0])
        self.assertEqual(
            sorted(row),
            ["base_commit", "instance_id", "new_file_fraction", "repo",
             "rs_file_count", "tree_sha"])
        # U3: a patch or problem statement must never reach the public manifest
        self.assertNotIn("patch", row)
        self.assertNotIn("problem_statement", row)


if __name__ == "__main__":
    unittest.main()
