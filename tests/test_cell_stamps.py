"""Per-cell provenance stamps (lane 4F): each refusal is exercised, and the
accepting path is exercised with the same inputs so a refusal is never vacuous."""

from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path

from arms.arm_matrix import StoreMode
from ttg.cell_stamps import (
    StampError,
    assert_store_mode,
    parse_model_lock,
    validated_build_commit,
    verify_corpus,
    verify_reranker_absent,
    verify_reranker_install,
)
from ttg.cli import main

PKG = Path(__file__).resolve().parent.parent

LOCK = """\
hf_repo = "jinaai/jina-reranker-v1-turbo-en"
revision = "b8c14f4e723d9e0aab4732a7b7b93741eeeb77c2"
cache_dir = "models/reranker/jina/b8c14f4e723d9e0aab4732a7b7b93741eeeb77c2"

[[files]]
role = "graph"
path = "onnx/model.onnx"
sha256 = "{graph}"
size = 5

[[files]]
role = "tokenizer"
path = "tokenizer.json"
sha256 = "{tokenizer}"
size = 2
"""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class BuildCommitTest(unittest.TestCase):
    def test_a_full_sha_is_accepted(self) -> None:
        commit = "a" * 40
        self.assertEqual(validated_build_commit(commit), commit)

    def test_a_short_or_non_hex_commit_is_refused(self) -> None:
        for bad in ("abc1234", "A" * 40, "g" * 40, "", "a" * 41):
            with self.subTest(commit=bad), self.assertRaises(StampError):
                validated_build_commit(bad)


class CorpusPinTest(unittest.TestCase):
    def test_pinned_bytes_pass_and_any_other_bytes_are_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jsonl = Path(tmp) / "ts40.jsonl"
            jsonl.write_bytes(b'{"instance_id": "x"}\n')
            sums = Path(tmp) / "jsonl.SHA256SUMS"
            sums.write_text(f"{_sha(jsonl.read_bytes())}  ts40.jsonl\n")
            self.assertEqual(verify_corpus(jsonl, "ts40", sums), _sha(jsonl.read_bytes()))
            jsonl.write_bytes(b'{"instance_id": "y"}\n')
            with self.assertRaises(StampError):
                verify_corpus(jsonl, "ts40", sums)

    def test_an_unpinned_corpus_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            jsonl = Path(tmp) / "go34.jsonl"
            jsonl.write_bytes(b"{}\n")
            sums = Path(tmp) / "jsonl.SHA256SUMS"
            sums.write_text(f"{_sha(b'{}\n')}  ts40.jsonl\n")
            with self.assertRaises(StampError):
                verify_corpus(jsonl, "go34", sums)

    def test_every_public_corpus_is_pinned(self) -> None:
        sums = (PKG / "corpora" / "jsonl.SHA256SUMS").read_text().split()
        names = set(sums[1::2])
        self.assertEqual(
            names, {"ts40.jsonl", "py_nosphinx.jsonl", "go34.jsonl", "rust43.jsonl"}
        )


class StoreModeTest(unittest.TestCase):
    def test_fresh_accepts_absent_or_empty_and_refuses_populated(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "shipped_treatment_ts40"
            assert_store_mode(store, StoreMode.FRESH)
            store.mkdir()
            assert_store_mode(store, StoreMode.FRESH)
            (store / "catalog.db").write_bytes(b"x")
            with self.assertRaises(StampError):
                assert_store_mode(store, StoreMode.FRESH)

    def test_reuse_requires_a_populated_store(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "shipped_treatment_ts40"
            with self.assertRaises(StampError):
                assert_store_mode(store, StoreMode.REUSE)
            store.mkdir()
            with self.assertRaises(StampError):
                assert_store_mode(store, StoreMode.REUSE)
            (store / "catalog.db").write_bytes(b"x")
            assert_store_mode(store, StoreMode.REUSE)


class RerankerInstallTest(unittest.TestCase):
    def _store_with(self, tmp: str, graph: bytes, tokenizer: bytes) -> tuple[Path, str]:
        lock_text = LOCK.format(graph=_sha(b"model"), tokenizer=_sha(b"{}"))
        lock = parse_model_lock(lock_text)
        store = Path(tmp) / "store"
        root = store / lock.cache_dir
        (root / "onnx").mkdir(parents=True)
        (root / "onnx" / "model.onnx").write_bytes(graph)
        (root / "tokenizer.json").write_bytes(tokenizer)
        return store, lock_text

    def test_the_locked_install_is_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, lock_text = self._store_with(tmp, b"model", b"{}")
            revision = verify_reranker_install(store, parse_model_lock(lock_text))
            self.assertEqual(revision, "b8c14f4e723d9e0aab4732a7b7b93741eeeb77c2")

    def test_a_different_model_file_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store, lock_text = self._store_with(tmp, b"other", b"{}")
            with self.assertRaises(StampError):
                verify_reranker_install(store, parse_model_lock(lock_text))

    def test_a_missing_install_is_refused(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock = parse_model_lock(LOCK.format(graph=_sha(b"m"), tokenizer=_sha(b"t")))
            with self.assertRaises(StampError):
                verify_reranker_install(Path(tmp) / "store", lock)

    def test_a_non_ranking_arm_must_leave_no_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            lock = parse_model_lock(LOCK.format(graph=_sha(b"m"), tokenizer=_sha(b"t")))
            verify_reranker_absent(Path(tmp) / "store", lock)
            store, lock_text = self._store_with(tmp, b"model", b"{}")
            with self.assertRaises(StampError):
                verify_reranker_absent(store, parse_model_lock(lock_text))

    def test_the_engine_lock_format_parses(self) -> None:
        lock = parse_model_lock(LOCK.format(graph="1" * 64, tokenizer="2" * 64))
        self.assertEqual([f.path for f in lock.files], ["onnx/model.onnx", "tokenizer.json"])


class CellPreflightCliTest(unittest.TestCase):
    """The CLI path run_arm.sh uses: a refusal is exit 2, never a traceback."""

    def test_a_populated_fresh_store_is_refused_through_the_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            store = Path(tmp) / "s"
            store.mkdir()
            (store / "x").write_bytes(b"x")
            jsonl = Path(tmp) / "ts40.jsonl"
            jsonl.write_bytes(b"not the pinned corpus\n")
            rc = main([
                "cell-preflight", "--arm", "shipped_explore", "--corpus", "ts40",
                "--corpus-jsonl", str(jsonl), "--store", str(store),
                "--build-commit", "a" * 40,
            ])
            self.assertEqual(rc, 2)


if __name__ == "__main__":
    unittest.main()
