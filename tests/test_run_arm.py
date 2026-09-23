"""`arms/run_arm.sh` end to end with a stub `noodl-eval` (lane 4F).

The stub stands in for the engine: `capabilities` prints a language list, and
`swe-bench` records that it ran and installs the reranker files named by the
test into its `NOODLBOX_DATA_DIR` (as a cold-cache engine run does). The
package is copied into a temp dir so its corpus pins can name the test corpus
without any test-only switch in the runner.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
COMMIT = "c" * 40
MODEL = b"onnx-bytes"
TOKENIZER = b"{}"
CACHE_DIR = "models/reranker/jina/rev1"
LOCK = f"""\
revision = "rev1"
cache_dir = "{CACHE_DIR}"

[[files]]
path = "onnx/model.onnx"
sha256 = "{hashlib.sha256(MODEL).hexdigest()}"

[[files]]
path = "tokenizer.json"
sha256 = "{hashlib.sha256(TOKENIZER).hexdigest()}"
"""

STUB = """#!/usr/bin/env python3
import os, sys, pathlib
if sys.argv[1] == "capabilities":
    print('{"analysis_languages": ["python", "typescript", "go", "rust"]}')
    sys.exit(0)
store = pathlib.Path(os.environ["NOODLBOX_DATA_DIR"])
store.mkdir(parents=True, exist_ok=True)
(store / "ran").write_text(" ".join(sys.argv[1:]))
root = store / os.environ["STUB_CACHE_DIR"]
(root / "onnx").mkdir(parents=True, exist_ok=True)
(root / "onnx" / "model.onnx").write_bytes(os.environ["STUB_MODEL"].encode())
(root / "tokenizer.json").write_bytes(b"{}")
print("{}")
"""


class RunArmTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.pkg = self.tmp / "pkg"
        shutil.copytree(
            PKG, self.pkg,
            ignore=shutil.ignore_patterns("runs", "worktrees", ".git", "__pycache__"),
        )
        self.jsonl = self.tmp / "ts40.jsonl"
        self.jsonl.write_bytes(b'{"instance_id": "a"}\n')
        digest = hashlib.sha256(self.jsonl.read_bytes()).hexdigest()
        (self.pkg / "corpora" / "jsonl.SHA256SUMS").write_text(f"{digest}  ts40.jsonl\n")
        self.lock = self.tmp / "model.lock"
        self.lock.write_text(LOCK)
        self.binary = self.tmp / "noodl-eval"
        self.binary.write_text(STUB)
        self.binary.chmod(self.binary.stat().st_mode | stat.S_IXUSR)
        self.store = self.tmp / "stores" / "shipped_explore_ts40"
        self.out = self.tmp / "out" / "shipped_explore_ts40.json"

    def _run(self, model: bytes = MODEL, commit: str = COMMIT) -> subprocess.CompletedProcess[str]:
        env = {
            **os.environ,
            "STUB_CACHE_DIR": CACHE_DIR,
            "STUB_MODEL": model.decode(),
        }
        return subprocess.run(
            [
                "bash", str(self.pkg / "arms" / "run_arm.sh"),
                "--arm", "shipped_explore", "--corpus", "ts40",
                "--binary", str(self.binary), "--corpus-jsonl", str(self.jsonl),
                "--store", str(self.store), "--out", str(self.out),
                "--build-commit", commit, "--model-lock", str(self.lock),
            ],
            capture_output=True, text=True, env=env, check=False,
        )

    def _manifest(self) -> str:
        return self.out.with_suffix(".manifest.txt").read_text()

    def test_a_clean_cell_runs_and_stamps_its_provenance(self) -> None:
        run = self._run()
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("--intent explore", (self.store / "ran").read_text())
        manifest = self._manifest()
        self.assertIn(f"build_commit: {COMMIT}", manifest)
        self.assertIn("(pinned)", manifest)
        self.assertIn("store_mode:   fresh (verified)", manifest)
        self.assertIn('"analysis_languages"', manifest)
        self.assertIn("reranker_rev: rev1", manifest)
        self.assertEqual(json.loads(self.out.read_text()), {})

    def test_a_populated_fresh_store_is_refused_before_the_engine_runs(self) -> None:
        self.store.mkdir(parents=True)
        (self.store / "catalog.db").write_bytes(b"stale")
        run = self._run()
        self.assertNotEqual(run.returncode, 0)
        self.assertFalse((self.store / "ran").exists(), "the engine must not run")

    def test_an_unpinned_corpus_is_refused_before_the_engine_runs(self) -> None:
        self.jsonl.write_bytes(b'{"instance_id": "b"}\n')
        run = self._run()
        self.assertNotEqual(run.returncode, 0)
        self.assertFalse((self.store / "ran").exists(), "the engine must not run")

    def test_a_short_build_commit_is_refused(self) -> None:
        run = self._run(commit="abc1234")
        self.assertNotEqual(run.returncode, 0)
        self.assertFalse((self.store / "ran").exists(), "the engine must not run")

    def test_a_reranker_other_than_the_locked_one_fails_the_cell(self) -> None:
        run = self._run(model=b"a-different-model")
        self.assertNotEqual(run.returncode, 0)
        self.assertTrue((self.store / "ran").exists(), "the engine ran; the stamp refused")
        self.assertNotIn("reranker_rev:", self._manifest())


if __name__ == "__main__":
    unittest.main()
