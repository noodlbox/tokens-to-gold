"""`arms/run_arm.sh` and `arms/run_matrix.sh` end to end with a stub `noodl-eval`
(lane 4F).

The stub stands in for the engine: `capabilities` prints a language list, and
`swe-bench` records that it ran and — unless told not to — installs the reranker
files named by the test into its `NOODLBOX_DATA_DIR`, as a cold-cache engine run
does. The package is copied into a temp dir so its corpus pins can name the test
corpus without any test-only switch in the runner; the build receipt is written
for the stub's own bytes.
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
from dataclasses import asdict
from pathlib import Path

from ttg.cell_stamps import BuildReceipt, ReceiptVerdict

PKG = Path(__file__).resolve().parent.parent
COMMIT = "c" * 40
MODEL = b"onnx-bytes"
CACHE_DIR = "models/reranker/jina/rev1"
LOCK = f"""\
hf_repo = "jinaai/jina-reranker-v1-turbo-en"
revision = "rev1"
cache_dir = "{CACHE_DIR}"

[[files]]
path = "onnx/model.onnx"
sha256 = "{hashlib.sha256(MODEL).hexdigest()}"

[[files]]
path = "tokenizer.json"
sha256 = "{hashlib.sha256(b"{}").hexdigest()}"
"""

STUB = """#!/usr/bin/env python3
import os, sys, pathlib
if sys.argv[1] == "capabilities":
    print('{"analysis_languages": ["python", "typescript", "go", "rust"]}')
    sys.exit(0)
store = pathlib.Path(os.environ["NOODLBOX_DATA_DIR"])
store.mkdir(parents=True, exist_ok=True)
(store / "ran").write_text(" ".join(sys.argv[1:]))
if os.environ.get("STUB_INSTALL", "1") == "1":
    root = store / os.environ["STUB_CACHE_DIR"]
    (root / "onnx").mkdir(parents=True, exist_ok=True)
    (root / "onnx" / "model.onnx").write_bytes(os.environ["STUB_MODEL"].encode())
    (root / "tokenizer.json").write_bytes(b"{}")
print("{}")
sys.exit(int(os.environ.get("STUB_EXIT", "0")))
"""


class _Harness(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.tmp = Path(tmp.name)
        self.pkg = self.tmp / "pkg"
        shutil.copytree(
            PKG, self.pkg,
            ignore=shutil.ignore_patterns("runs", "worktrees", ".git", "__pycache__"),
        )
        self.corpus_dir = self.tmp / "corpora"
        self.corpus_dir.mkdir()
        self.jsonl = self.corpus_dir / "ts40.jsonl"
        self.jsonl.write_bytes(b'{"instance_id": "a"}\n')
        digest = hashlib.sha256(self.jsonl.read_bytes()).hexdigest()
        (self.pkg / "corpora" / "jsonl.SHA256SUMS").write_text(f"{digest}  ts40.jsonl\n")
        self.binary = self.tmp / "noodl-eval"
        self.binary.write_text(STUB)
        self.binary.chmod(self.binary.stat().st_mode | stat.S_IXUSR)
        self.receipt = self.tmp / "build-receipt.json"
        self.write_receipt(("go", "python", "rust", "typescript"))
        self.out = self.tmp / "out"

    def write_receipt(self, languages: tuple[str, ...], lock: str = LOCK) -> None:
        """A receipt for the stub's bytes and the verdict `verify-receipt` would
        issue for it (the git side is covered by test_cell_stamps)."""
        self.receipt.write_text(json.dumps(asdict(BuildReceipt(
            schema=2, commit=COMMIT, tree_digest="a" * 64,
            binary_sha256=hashlib.sha256(self.binary.read_bytes()).hexdigest(),
            cargo_profile="release", cargo_features="default",
            rust_toolchain_toml="[toolchain]\n", rustc_version="rustc 1.95.0",
            analysis_languages=languages,
            model_lock_text=lock,
            model_lock_sha256=hashlib.sha256(lock.encode()).hexdigest(),
        ))))
        self.verdict = self.tmp / "receipt-verdict.json"
        self.verdict.write_text(json.dumps(asdict(ReceiptVerdict(
            schema=2, receipt_sha256=hashlib.sha256(self.receipt.read_bytes()).hexdigest(),
            commit=COMMIT, tree_digest="a" * 64,
            model_lock_sha256=hashlib.sha256(lock.encode()).hexdigest(),
            rust_toolchain_sha256=hashlib.sha256(b"[toolchain]\n").hexdigest(),
            checked="test",
        ))))

    def _env(self, install: bool = True, model: bytes = MODEL,
             exit_code: int = 0) -> dict[str, str]:
        return {
            **os.environ, "STUB_CACHE_DIR": CACHE_DIR, "STUB_MODEL": model.decode(),
            "STUB_INSTALL": "1" if install else "0", "STUB_EXIT": str(exit_code),
        }

    def run_arm(self, arm: str, store: Path, *, commit: str = COMMIT, install: bool = True,
                model: bytes = MODEL, exit_code: int = 0) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                "bash", str(self.pkg / "arms" / "run_arm.sh"),
                "--arm", arm, "--corpus", "ts40", "--binary", str(self.binary),
                "--corpus-jsonl", str(self.jsonl), "--store", str(store),
                "--out", str(self.out / f"{arm}_ts40.json"),
                "--build-receipt", str(self.receipt), "--receipt-verdict", str(self.verdict),
                "--build-commit", commit,
            ],
            capture_output=True, text=True, env=self._env(install, model, exit_code),
            check=False,
        )


class RunArmTest(_Harness):
    def test_a_clean_cell_publishes_its_report_with_every_stamp(self) -> None:
        store = self.tmp / "stores" / "shipped_explore_ts40"
        run = self.run_arm("shipped_explore", store)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("--intent explore", (store / "ran").read_text())
        report = self.out / "shipped_explore_ts40.json"
        self.assertEqual(json.loads(report.read_text()), {})
        self.assertFalse(report.with_name(report.name + ".partial").exists())
        manifest = (self.out / "shipped_explore_ts40.manifest.txt").read_text()
        for stamp in (f"build_commit: {COMMIT} (receipt; verified against git history",
                      "(pinned)", "store:        fresh (verified absent or empty)",
                      "capabilities: go,python,rust,typescript (live; equals the receipt",
                      "model_lock:   jinaai/", "reranker_rev: rev1"):
            self.assertIn(stamp, manifest)
        self.assertRegex(manifest, r"host_cpu:     \S.* x[1-9]\d*\n")
        self.assertTrue((self.out / "shipped_explore_ts40.receipt-verdict.json").is_file())
        self.assertTrue((self.out / "shipped_explore_ts40.build-receipt.json").is_file())
        self.assertTrue((store / ".ttg-cell-complete.json").is_file())

    def test_a_populated_fresh_store_is_refused_before_the_engine_runs(self) -> None:
        store = self.tmp / "stores" / "shipped_explore_ts40"
        store.mkdir(parents=True)
        (store / "catalog.db").write_bytes(b"stale")
        run = self.run_arm("shipped_explore", store)
        self.assertEqual(run.returncode, 2)
        self.assertIn("given a populated store", run.stderr)
        self.assertFalse((store / "ran").exists(), "the engine must not run")

    def test_an_unpinned_corpus_is_refused_before_the_engine_runs(self) -> None:
        store = self.tmp / "stores" / "shipped_explore_ts40"
        self.jsonl.write_bytes(b'{"instance_id": "b"}\n')
        run = self.run_arm("shipped_explore", store)
        self.assertEqual(run.returncode, 2)
        self.assertIn("pinned", run.stderr)
        self.assertFalse(store.exists(), "the engine must not run")

    def test_a_binary_other_than_the_receipts_is_refused_before_the_engine_runs(self) -> None:
        store = self.tmp / "stores" / "shipped_explore_ts40"
        self.binary.write_text(STUB + "# rebuilt from another tree\n")
        run = self.run_arm("shipped_explore", store)
        self.assertEqual(run.returncode, 2)
        self.assertIn("not the binary that commit built", run.stderr)
        self.assertFalse(store.exists(), "the engine must not run")

    def test_a_commit_other_than_the_receipts_is_refused(self) -> None:
        store = self.tmp / "stores" / "shipped_explore_ts40"
        run = self.run_arm("shipped_explore", store, commit="d" * 40)
        self.assertEqual(run.returncode, 2)
        self.assertIn("receipt is for commit", run.stderr)

    def test_a_receipt_without_its_verdict_is_refused_before_the_engine_runs(self) -> None:
        store = self.tmp / "stores" / "shipped_explore_ts40"
        self.receipt.write_text(self.receipt.read_text() + " ")
        run = self.run_arm("shipped_explore", store)
        self.assertEqual(run.returncode, 2)
        self.assertIn("was not issued for", run.stderr)
        self.assertFalse(store.exists(), "the engine must not run")

    def test_a_verdict_vouching_for_another_commit_or_tree_is_refused(self) -> None:
        """The reviewer's forge: a verdict bound to this receipt's bytes but whose
        own commit/tree/lock fields differ must not pass (and must never be the
        source of a stamp)."""
        store = self.tmp / "stores" / "shipped_explore_ts40"
        doc = json.loads(self.verdict.read_text())
        for field, value in (("commit", "d" * 40), ("tree_digest", "0" * 64),
                             ("model_lock_sha256", "1" * 64),
                             ("rust_toolchain_sha256", "2" * 64)):
            with self.subTest(field=field):
                self.verdict.write_text(json.dumps({**doc, field: value}))
                run = self.run_arm("shipped_explore", store)
                self.assertEqual(run.returncode, 2)
                self.assertIn("vouches for", run.stderr)
                self.assertFalse(store.exists(), "the engine must not run")

    def test_a_receipt_claiming_other_capabilities_is_refused(self) -> None:
        store = self.tmp / "stores" / "shipped_explore_ts40"
        self.write_receipt(("go",))
        run = self.run_arm("shipped_explore", store)
        self.assertEqual(run.returncode, 2)
        self.assertIn("reports capabilities", run.stderr)
        self.assertFalse(store.exists(), "the engine must not run")

    def test_a_receipt_with_an_unparsable_lock_is_refused_before_the_engine_runs(self) -> None:
        store = self.tmp / "stores" / "shipped_explore_ts40"
        self.write_receipt(("go", "python", "rust", "typescript"), lock="not = [toml")
        run = self.run_arm("shipped_explore", store)
        self.assertEqual(run.returncode, 2)
        self.assertIn("model.lock is not valid TOML", run.stderr)
        self.assertFalse(store.exists(), "the engine must not run")

    def test_a_failed_engine_run_publishes_nothing_and_marks_nothing(self) -> None:
        store = self.tmp / "stores" / "shipped_explore_ts40"
        run = self.run_arm("shipped_explore", store, exit_code=3)
        self.assertEqual(run.returncode, 3)
        self.assertFalse((self.out / "shipped_explore_ts40.json").exists())
        self.assertFalse((store / ".ttg-cell-complete.json").exists())

    def test_a_reranker_other_than_the_locked_one_fails_the_cell_and_publishes_nothing(
        self,
    ) -> None:
        store = self.tmp / "stores" / "shipped_explore_ts40"
        run = self.run_arm("shipped_explore", store, model=b"a-different-model")
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("locked", run.stderr)
        self.assertTrue((store / "ran").exists(), "the engine ran; the stamp refused")
        self.assertFalse((self.out / "shipped_explore_ts40.json").exists())
        self.assertFalse((store / ".ttg-cell-complete.json").exists())

    def test_the_non_ranking_arm_passes_without_an_install_and_fails_with_one(self) -> None:
        store = self.tmp / "stores" / "native_floor_ts40"
        run = self.run_arm("native_floor", store, install=False)
        self.assertEqual(run.returncode, 0, run.stderr)
        self.assertIn("reranker_rev: none", run.stdout)
        other = self.tmp / "stores2" / "native_floor_ts40"
        run = self.run_arm("native_floor", other, install=True)
        self.assertNotEqual(run.returncode, 0)
        self.assertIn("declaration is wrong", run.stderr)


class RunMatrixTest(_Harness):
    def _matrix(self, arms: str, *, model: bytes = MODEL,
                **overrides: str) -> subprocess.CompletedProcess[str]:
        args = {
            "--arms": arms, "--corpora": "ts40", "--binary": str(self.binary),
            "--corpus-dir": str(self.corpus_dir), "--store": str(self.tmp / "root"),
            "--outdir": str(self.out), "--build-receipt": str(self.receipt),
            "--receipt-verdict": str(self.verdict), "--build-commit": COMMIT, **overrides,
        }
        argv = [part for pair in args.items() for part in pair if pair[1] != ""]
        return subprocess.run(
            ["bash", str(self.pkg / "arms" / "run_matrix.sh"), *argv],
            capture_output=True, text=True, env=self._env(model=model), check=False,
        )

    def test_each_fresh_cell_runs_in_its_own_store(self) -> None:
        run = self._matrix("shipped_treatment,shipped_explore")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        root = self.tmp / "root"
        self.assertIn("--intent implement",
                      (root / "shipped_treatment_ts40" / "ran").read_text())
        self.assertIn("--intent explore", (root / "shipped_explore_ts40" / "ran").read_text())

    def test_an_empty_store_root_is_refused(self) -> None:
        run = self._matrix("shipped_explore", **{"--store": ""})
        self.assertEqual(run.returncode, 2)
        self.assertIn("--store is required", run.stderr)

    def test_the_reuse_arm_needs_its_source_cell_to_have_completed(self) -> None:
        # No source cell at all: the REUSE preflight refuses before the engine.
        alone = self._matrix("levers_off_ablation")
        self.assertNotEqual(alone.returncode, 0)
        self.assertIn("has no completion marker", alone.stderr)
        # A source cell that ran but failed its stamp leaves no marker: refused.
        failed = self._matrix("shipped_treatment,levers_off_ablation", model=b"other")
        self.assertNotEqual(failed.returncode, 0)
        self.assertIn("has no completion marker", failed.stderr)

    def test_a_completed_source_cell_is_reused_and_its_marker_given_back(self) -> None:
        run = self._matrix("shipped_treatment,levers_off_ablation")
        self.assertEqual(run.returncode, 0, run.stdout + run.stderr)
        manifest = (self.out / "levers_off_ablation_ts40.manifest.txt").read_text()
        self.assertIn("reuse of shipped_treatment_ts40 (verified completion marker", manifest)
        store = self.tmp / "root" / "shipped_treatment_ts40"
        self.assertTrue((store / ".ttg-cell-complete.json").is_file())
        self.assertEqual(list(store.glob(".ttg-cell-complete.json.in-use.*")), [])

    def test_a_reuse_run_that_dies_leaves_its_store_unmarked(self) -> None:
        source = self._matrix("shipped_treatment")
        self.assertEqual(source.returncode, 0, source.stdout + source.stderr)
        store = self.tmp / "root" / "shipped_treatment_ts40"
        died = self.run_arm("levers_off_ablation", store, exit_code=3)
        self.assertEqual(died.returncode, 3)
        self.assertFalse((store / ".ttg-cell-complete.json").exists())
        again = self.run_arm("levers_off_ablation", store)
        self.assertEqual(again.returncode, 2)
        self.assertIn("has no completion marker", again.stderr)


if __name__ == "__main__":
    unittest.main()
