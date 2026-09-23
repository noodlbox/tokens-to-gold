"""Cell provenance stamps (lane 4F): every refusal is exercised next to its
accepting counterpart, so no refusal is vacuous, and each test asserts WHICH
guarantee refused (the message), not merely that something did."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import tempfile
import unittest
from dataclasses import asdict, replace
from pathlib import Path

from arms.arm_matrix import ARMS
from ttg.cell_stamps import (
    COMPLETION_MARKER,
    BuildReceipt,
    CompletionMarker,
    StampError,
    host_cpu,
    assert_store_ready,
    load_build_receipt,
    parse_model_lock,
    pinned_sha256,
    tree_digest,
    tree_entries_from_disk,
    tree_entries_from_git,
    validated_commit,
    verify_binary_against_receipt,
    verify_corpus,
    verify_engine_tree,
    verify_no_reranker_install,
    verify_reranker_install,
    write_build_receipt,
)

PKG = Path(__file__).resolve().parent.parent
COMMIT = "c" * 40
LOCK = """\
hf_repo = "jinaai/jina-reranker-v1-turbo-en"
revision = "b8c14f4e723d9e0aab4732a7b7b93741eeeb77c2"
cache_dir = "models/reranker/jina/b8c14f4e723d9e0aab4732a7b7b93741eeeb77c2"

[[files]]
role = "graph"
path = "onnx/model.onnx"
sha256 = "{graph}"

[[files]]
role = "tokenizer"
path = "tokenizer.json"
sha256 = "{tokenizer}"
"""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _receipt(binary_sha: str, commit: str = COMMIT) -> BuildReceipt:
    lock = LOCK.format(graph=_sha(b"model"), tokenizer=_sha(b"{}"))
    return BuildReceipt(
        schema=1, commit=commit, tree_digest="a" * 64, binary_sha256=binary_sha,
        cargo_profile="release", cargo_features="default",
        rust_toolchain_toml='[toolchain]\nchannel = "1.95"\n', rustc_version="rustc 1.95.0",
        analysis_languages=("go", "python", "typescript"), model_lock_text=lock,
        model_lock_sha256=_sha(lock.encode()),
    )


class CommitTest(unittest.TestCase):
    def test_only_a_full_lowercase_sha_is_a_commit(self) -> None:
        self.assertEqual(validated_commit("a" * 40), "a" * 40)
        for bad in ("abc1234", "A" * 40, "g" * 40, "", "a" * 41):
            with self.subTest(commit=bad), self.assertRaisesRegex(StampError, "40-hex"):
                validated_commit(bad)


class EngineTreeTest(unittest.TestCase):
    """The build receipt's first link: the synced tree IS the commit's tree."""

    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.repo = Path(tmp.name) / "engine"
        (self.repo / "src").mkdir(parents=True)
        (self.repo / "src" / "lib.rs").write_text("pub fn f() {}\n")
        (self.repo / "Cargo.toml").write_text("[package]\nname = \"e\"\n")
        (self.repo / "link").symlink_to("src/lib.rs")

        def git(*args: str) -> None:
            subprocess.run(
                ["git", "-C", str(self.repo), *args], check=True, capture_output=True
            )

        git("init", "-q")
        git("add", "-A")
        git("-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "c")
        self.commit = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        self.expected = tree_digest(tree_entries_from_git(self.repo, self.commit))
        self.synced = Path(tmp.name) / "synced"
        shutil.copytree(self.repo, self.synced, symlinks=True,
                        ignore=shutil.ignore_patterns(".git"))

    def test_the_synced_tree_matches_the_commit(self) -> None:
        self.assertEqual(
            tree_digest(tree_entries_from_disk(self.synced)), self.expected
        )
        verify_engine_tree(self.synced, self.expected)

    def test_a_one_byte_source_drift_refuses(self) -> None:
        source = self.synced / "src" / "lib.rs"
        source.write_bytes(source.read_bytes().replace(b"f()", b"g()"))
        with self.assertRaisesRegex(StampError, "drifted, was added, or is missing"):
            verify_engine_tree(self.synced, self.expected)

    def test_an_untracked_file_refuses(self) -> None:
        (self.synced / "src" / "extra.rs").write_text("")
        with self.assertRaisesRegex(StampError, "drifted, was added, or is missing"):
            verify_engine_tree(self.synced, self.expected)

    def test_a_missing_file_refuses(self) -> None:
        (self.synced / "Cargo.toml").unlink()
        with self.assertRaisesRegex(StampError, "drifted, was added, or is missing"):
            verify_engine_tree(self.synced, self.expected)

    def test_sync_excluded_paths_are_outside_the_identity(self) -> None:
        (self.synced / "target" / "release").mkdir(parents=True)
        (self.synced / "target" / "release" / "noodl-eval").write_bytes(b"bin")
        verify_engine_tree(self.synced, self.expected)


class WriteBuildReceiptTest(EngineTreeTest):
    """The build step's receipt: written only for a verified tree, and it records
    what the ruling requires (profile, features, toolchain, lock, capabilities)."""

    def setUp(self) -> None:
        super().setUp()
        for root in (self.repo, self.synced):
            (root / "assets" / "models" / "reranker").mkdir(parents=True)
            (root / "assets" / "models" / "reranker" / "model.lock").write_text(
                LOCK.format(graph="1" * 64, tokenizer="2" * 64)
            )
            (root / "rust-toolchain.toml").write_text('[toolchain]\nchannel = "stable"\n')
        subprocess.run(["git", "-C", str(self.repo), "add", "-A"], check=True)
        subprocess.run(["git", "-C", str(self.repo), "-c", "user.email=t@t", "-c",
                        "user.name=t", "commit", "-qm", "assets"], check=True)
        self.commit = subprocess.run(
            ["git", "-C", str(self.repo), "rev-parse", "HEAD"], check=True,
            capture_output=True, text=True,
        ).stdout.strip()
        self.expected = tree_digest(tree_entries_from_git(self.repo, self.commit))
        self.binary = self.synced.parent / "noodl-eval"
        self.binary.write_text(
            "#!/bin/sh\necho '{\"analysis_languages\": [\"go\", \"python\"]}'\n"
        )
        self.binary.chmod(0o755)

    def test_the_receipt_binds_commit_tree_binary_toolchain_and_lock(self) -> None:
        if shutil.which("rustc") is None:
            self.skipTest("rustc is not on PATH")
        out = self.synced.parent / "build-receipt.json"
        receipt = write_build_receipt(
            src=self.synced, commit=self.commit, expected_tree_digest=self.expected,
            binary=self.binary, profile="release", features="default", out=out,
        )
        self.assertEqual(load_build_receipt(out), receipt)
        self.assertEqual(receipt.tree_digest, self.expected)
        self.assertEqual(receipt.binary_sha256, _sha(self.binary.read_bytes()))
        self.assertEqual(receipt.analysis_languages, ("go", "python"))
        self.assertIn("stable", receipt.rust_toolchain_toml)
        self.assertTrue(receipt.rustc_version.startswith("rustc "))
        self.assertEqual(parse_model_lock(receipt.model_lock_text).revision,
                         "b8c14f4e723d9e0aab4732a7b7b93741eeeb77c2")

    def test_no_receipt_is_written_for_a_drifted_tree(self) -> None:
        (self.synced / "src" / "lib.rs").write_text("pub fn g() {}\n")
        out = self.synced.parent / "build-receipt.json"
        with self.assertRaisesRegex(StampError, "drifted, was added, or is missing"):
            write_build_receipt(
                src=self.synced, commit=self.commit, expected_tree_digest=self.expected,
                binary=self.binary, profile="release", features="default", out=out,
            )
        self.assertFalse(out.exists())


class BuildReceiptTest(unittest.TestCase):
    def test_the_binary_must_hash_to_the_receipt_and_name_the_requested_commit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "noodl-eval"
            binary.write_bytes(b"engine")
            receipt = _receipt(_sha(b"engine"))
            verify_binary_against_receipt(binary, receipt, COMMIT)
            with self.assertRaisesRegex(StampError, "receipt is for commit"):
                verify_binary_against_receipt(binary, receipt, "d" * 40)
            binary.write_bytes(b"another engine")
            with self.assertRaisesRegex(StampError, "not the binary that commit built"):
                verify_binary_against_receipt(binary, receipt, COMMIT)

    def test_a_receipt_round_trips_and_a_tampered_lock_refuses(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "build-receipt.json"
            receipt = _receipt("b" * 64)
            path.write_text(json.dumps(asdict(receipt)))
            self.assertEqual(load_build_receipt(path), receipt)
            tampered = replace(receipt, model_lock_text=receipt.model_lock_text + "#")
            path.write_text(json.dumps(asdict(tampered)))
            with self.assertRaisesRegex(StampError, "does not match its digest"):
                load_build_receipt(path)
            path.write_text("{not json")
            with self.assertRaisesRegex(StampError, "malformed"):
                load_build_receipt(path)


class CorpusPinTest(unittest.TestCase):
    def test_pinned_bytes_pass_and_any_other_bytes_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jsonl = Path(tmp) / "ts40.jsonl"
            jsonl.write_bytes(b'{"instance_id": "x"}\n')
            sums = Path(tmp) / "jsonl.SHA256SUMS"
            sums.write_text(f"{_sha(jsonl.read_bytes())}  ts40.jsonl\n")
            self.assertEqual(verify_corpus(jsonl, "ts40", sums), _sha(jsonl.read_bytes()))
            jsonl.write_bytes(b'{"instance_id": "y"}\n')
            with self.assertRaisesRegex(StampError, "pinned"):
                verify_corpus(jsonl, "ts40", sums)

    def test_an_unpinned_corpus_and_a_malformed_pin_line_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            sums = Path(tmp) / "jsonl.SHA256SUMS"
            sums.write_text(f"{'a' * 64}  ts40.jsonl\n")
            with self.assertRaisesRegex(StampError, "has no pin"):
                pinned_sha256(sums, "go34.jsonl")
            sums.write_text("just-one-token\n")
            with self.assertRaisesRegex(StampError, "is not a"):
                pinned_sha256(sums, "ts40.jsonl")

    def test_every_public_corpus_is_pinned(self) -> None:
        sums = (PKG / "corpora" / "jsonl.SHA256SUMS").read_text().split()
        self.assertEqual(
            set(sums[1::2]),
            {"ts40.jsonl", "py_nosphinx.jsonl", "go34.jsonl", "rust43.jsonl"},
        )


class StorePolicyTest(unittest.TestCase):
    def setUp(self) -> None:
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.store = Path(tmp.name) / "shipped_treatment_ts40"
        self.receipt = _receipt("b" * 64)

    def test_fresh_accepts_absent_or_empty_and_refuses_populated(self) -> None:
        arm = ARMS["shipped_treatment"]
        assert_store_ready(self.store, arm, "ts40", self.receipt, "e" * 64)
        self.store.mkdir()
        assert_store_ready(self.store, arm, "ts40", self.receipt, "e" * 64)
        (self.store / "catalog.db").write_bytes(b"x")
        with self.assertRaisesRegex(StampError, "given a populated store"):
            assert_store_ready(self.store, arm, "ts40", self.receipt, "e" * 64)

    def test_reuse_requires_the_source_cells_matching_completion_marker(self) -> None:
        arm = ARMS["levers_off_ablation"]
        self.store.mkdir()
        (self.store / ".partial-leftover").mkdir()
        with self.assertRaisesRegex(StampError, "has no completion marker"):
            assert_store_ready(self.store, arm, "ts40", self.receipt, "e" * 64)
        marker = CompletionMarker(
            arm="shipped_treatment", corpus="ts40", commit=COMMIT,
            binary_sha256="b" * 64, corpus_sha256="e" * 64, reranker="rev",
        )
        (self.store / COMPLETION_MARKER).write_text(json.dumps(asdict(marker)))
        assert_store_ready(self.store, arm, "ts40", self.receipt, "e" * 64)
        other_build = _receipt("f" * 64)
        with self.assertRaisesRegex(StampError, "was completed by"):
            assert_store_ready(self.store, arm, "ts40", other_build, "e" * 64)


class RerankerTest(unittest.TestCase):
    def _store(self, tmp: str, model: bytes) -> tuple[Path, str]:
        lock_text = LOCK.format(graph=_sha(b"model"), tokenizer=_sha(b"{}"))
        root = Path(tmp) / "store" / parse_model_lock(lock_text).cache_dir
        (root / "onnx").mkdir(parents=True)
        (root / "onnx" / "model.onnx").write_bytes(model)
        (root / "tokenizer.json").write_bytes(b"{}")
        return Path(tmp) / "store", lock_text

    def test_the_locked_install_passes_and_another_model_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, lock_text = self._store(tmp, b"model")
            self.assertEqual(
                verify_reranker_install(store, parse_model_lock(lock_text)),
                "b8c14f4e723d9e0aab4732a7b7b93741eeeb77c2",
            )
        with tempfile.TemporaryDirectory() as tmp:
            store, lock_text = self._store(tmp, b"other")
            with self.assertRaisesRegex(StampError, "locked"):
                verify_reranker_install(store, parse_model_lock(lock_text))

    def test_a_non_ranking_arm_must_leave_no_install_of_any_revision(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock = parse_model_lock(LOCK.format(graph=_sha(b"m"), tokenizer=_sha(b"t")))
            verify_no_reranker_install(Path(tmp) / "store", lock)
            for leftover in ("0" * 40 + "/onnx", "b8c14f4e.partial", ".rev.install.lock"):
                with self.subTest(leftover=leftover):
                    target = Path(tmp) / "store" / "models" / "reranker" / "jina" / leftover
                    target.mkdir(parents=True)
                    with self.assertRaisesRegex(StampError, "declaration is wrong"):
                        verify_no_reranker_install(Path(tmp) / "store", lock)
                    shutil.rmtree(Path(tmp) / "store")

    def test_a_malformed_lock_is_a_stamp_error_not_a_traceback(self) -> None:
        for bad in ("not = [toml", 'revision = "r"\ncache_dir = "a/b/c"\n', LOCK.replace(
                'hf_repo = "jinaai/jina-reranker-v1-turbo-en"', "hf_repo = 3")):
            with self.subTest(lock=bad[:20]), self.assertRaises(StampError):
                parse_model_lock(bad.format(graph="1" * 64, tokenizer="2" * 64))


class HostTest(unittest.TestCase):
    def test_the_host_cpu_names_a_model_and_a_count(self) -> None:
        cpu = host_cpu()
        self.assertRegex(cpu, r".+ x\d+$")


if __name__ == "__main__":
    unittest.main()
