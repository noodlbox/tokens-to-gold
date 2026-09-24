"""Cell provenance stamps (lane 4F): every refusal is exercised next to its
accepting counterpart, so no refusal is vacuous, and each test asserts WHICH
guarantee refused (the message), not merely that something did."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import unittest
from unittest import mock
from dataclasses import asdict, replace
from pathlib import Path

from arms.arm_matrix import ARMS
from ttg.cell_stamps import (
    COMPLETION_MARKER,
    BuildReceipt,
    CompletionMarker,
    StampError,
    cell_preflight,
    check_store,
    consumed_marker,
    cpu_model_from_brand_string,
    cpu_model_from_cpuinfo,
    format_host_cpu,
    load_receipt_verdict,
    measure_engine_tree,
    verify_live_capabilities,
    verify_receipt,
    load_build_receipt,
    parse_model_lock,
    pinned_sha256,
    tree_digest,
    tree_entries_from_disk,
    tree_entries_from_git,
    validated_commit,
    verify_binary_against_receipt,
    verify_corpus,
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
        schema=2, commit=commit, tree_digest="a" * 64, binary_sha256=binary_sha,
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

    def test_the_synced_tree_measures_as_the_commit(self) -> None:
        self.assertEqual(
            tree_digest(tree_entries_from_disk(self.synced)), self.expected
        )
        self.assertEqual(measure_engine_tree(self.synced), self.expected)

    def test_a_one_byte_source_drift_changes_the_identity(self) -> None:
        source = self.synced / "src" / "lib.rs"
        source.write_bytes(source.read_bytes().replace(b"f()", b"g()"))
        self.assertNotEqual(measure_engine_tree(self.synced), self.expected)

    def test_an_untracked_file_changes_the_identity(self) -> None:
        (self.synced / "src" / "extra.rs").write_text("")
        self.assertNotEqual(measure_engine_tree(self.synced), self.expected)

    def test_a_missing_file_changes_the_identity(self) -> None:
        (self.synced / "Cargo.toml").unlink()
        self.assertNotEqual(measure_engine_tree(self.synced), self.expected)

    def test_sync_excluded_paths_are_outside_the_identity(self) -> None:
        (self.synced / "target" / "release").mkdir(parents=True)
        (self.synced / "target" / "release" / "noodl-eval").write_bytes(b"bin")
        self.assertEqual(measure_engine_tree(self.synced), self.expected)


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

    def _write(self) -> tuple[Path, BuildReceipt]:
        out = self.synced.parent / "build-receipt.json"
        receipt = write_build_receipt(
            src=self.synced, commit=self.commit,
            pre_build_tree_digest=measure_engine_tree(self.synced), binary=self.binary,
            profile="release", features="default", out=out,
        )
        return out, receipt

    def test_the_receipt_records_tree_binary_toolchain_and_lock(self) -> None:
        if shutil.which("rustc") is None:
            self.skipTest("rustc is not on PATH")
        out, receipt = self._write()
        self.assertEqual(load_build_receipt(out), receipt)
        self.assertEqual(receipt.tree_digest, self.expected)
        self.assertEqual(receipt.binary_sha256, _sha(self.binary.read_bytes()))
        self.assertEqual(receipt.analysis_languages, ("go", "python"))
        self.assertIn("stable", receipt.rust_toolchain_toml)
        self.assertTrue(receipt.rustc_version.startswith("rustc "))
        self.assertEqual(parse_model_lock(receipt.model_lock_text).revision,
                         "b8c14f4e723d9e0aab4732a7b7b93741eeeb77c2")

    def test_build_engine_hands_the_commit_to_the_build(self) -> None:
        """The engine's build script bakes `NOODLBOX_GIT_SHA` into the binary
        (noodlbox-app #1414), and a lease tree has no `.git` to resolve it from:
        `build_engine.sh` must pass exactly its `--commit`. A stub `cargo` records
        the value and stands the fixture binary in as the build output."""
        if shutil.which("rustc") is None:
            self.skipTest("rustc is not on PATH")
        tools = self.synced.parent / "tools"
        tools.mkdir()
        seen = self.synced.parent / "seen-sha"
        target = self.synced.parent / "cargo-target"
        cargo = tools / "cargo"
        cargo.write_text(
            "#!/bin/sh\n"
            f'printf %s "${{NOODLBOX_GIT_SHA-UNSET}}" > "{seen}"\n'
            f'mkdir -p "{target}/release" && cp "{self.binary}" "{target}/release/noodl-eval"\n'
        )
        cargo.chmod(0o755)
        out_dir = self.synced.parent / "engine"
        env = {
            **os.environ,
            "PATH": f"{tools}{os.pathsep}{os.environ['PATH']}",
            "CARGO_TARGET_DIR": str(target),
        }
        env.pop("NOODLBOX_GIT_SHA", None)
        subprocess.run(
            ["bash", str(Path(__file__).resolve().parents[1] / "arms" / "build_engine.sh"),
             "--src", str(self.synced), "--commit", self.commit, "--out-dir", str(out_dir)],
            check=True, capture_output=True, env=env,
        )
        self.assertEqual(seen.read_text(), self.commit)
        self.assertEqual(load_build_receipt(out_dir / "build-receipt.json").commit, self.commit)

    def test_a_build_that_touches_its_sources_gets_no_receipt(self) -> None:
        out = self.synced.parent / "build-receipt.json"
        before = measure_engine_tree(self.synced)
        (self.synced / "src" / "generated.rs").write_text("// written by build.rs\n")
        with self.assertRaisesRegex(StampError, "changed during the build"):
            write_build_receipt(
                src=self.synced, commit=self.commit, pre_build_tree_digest=before,
                binary=self.binary, profile="release", features="default", out=out,
            )
        self.assertFalse(out.exists())

    def test_the_verdict_is_derived_from_git_and_binds_the_receipt(self) -> None:
        if shutil.which("rustc") is None:
            self.skipTest("rustc is not on PATH")
        out, receipt = self._write()
        verdict_path = self.synced.parent / "receipt-verdict.json"
        verdict = verify_receipt(engine_repo=self.repo, receipt_path=out, out=verdict_path)
        self.assertEqual(verdict.tree_digest, self.expected)
        self.assertEqual(load_receipt_verdict(verdict_path, out, receipt), verdict)
        # The verdict is bound to the receipt's bytes: any other receipt is refused.
        out.write_text(out.read_text() + " ")
        with self.assertRaisesRegex(StampError, "was not issued for"):
            load_receipt_verdict(verdict_path, out, load_build_receipt(out))

    def test_a_drifted_build_host_tree_gets_no_verdict(self) -> None:
        if shutil.which("rustc") is None:
            self.skipTest("rustc is not on PATH")
        source = self.synced / "src" / "lib.rs"
        source.write_bytes(source.read_bytes().replace(b"f()", b"g()"))
        out, _ = self._write()
        verdict_path = self.synced.parent / "receipt-verdict.json"
        with self.assertRaisesRegex(StampError, "drifted from the commit"):
            verify_receipt(engine_repo=self.repo, receipt_path=out, out=verdict_path)
        self.assertFalse(verdict_path.exists())

    def test_a_receipt_with_another_lock_or_toolchain_gets_no_verdict(self) -> None:
        if shutil.which("rustc") is None:
            self.skipTest("rustc is not on PATH")
        out, receipt = self._write()
        verdict_path = self.synced.parent / "receipt-verdict.json"
        for field, value in (("model_lock_text", receipt.model_lock_text + "# edit\n"),
                             ("rust_toolchain_toml", '[toolchain]\nchannel = "nightly"\n')):
            with self.subTest(field=field):
                forged = replace(receipt, **{field: value})
                if field == "model_lock_text":
                    forged = replace(forged, model_lock_sha256=_sha(value.encode()))
                out.write_text(json.dumps(asdict(forged)))
                with self.assertRaisesRegex(StampError, "is not commit"):
                    verify_receipt(engine_repo=self.repo, receipt_path=out, out=verdict_path)


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
        check_store(self.store, arm, "ts40", self.receipt, "e" * 64)
        self.store.mkdir()
        check_store(self.store, arm, "ts40", self.receipt, "e" * 64)
        (self.store / "catalog.db").write_bytes(b"x")
        with self.assertRaisesRegex(StampError, "given a populated store"):
            check_store(self.store, arm, "ts40", self.receipt, "e" * 64)

    def test_reuse_requires_the_source_cells_matching_completion_marker(self) -> None:
        arm = ARMS["levers_off_ablation"]
        self.store.mkdir()
        (self.store / ".partial-leftover").mkdir()
        with self.assertRaisesRegex(StampError, "has no completion marker"):
            check_store(self.store, arm, "ts40", self.receipt, "e" * 64)
        marker = CompletionMarker(
            arm="shipped_treatment", corpus="ts40", commit=COMMIT,
            binary_sha256="b" * 64, corpus_sha256="e" * 64, reranker="rev",
        )
        (self.store / COMPLETION_MARKER).write_text(json.dumps(asdict(marker)))
        check_store(self.store, arm, "ts40", self.receipt, "e" * 64)
        other_build = _receipt("f" * 64)
        with self.assertRaisesRegex(StampError, "was completed by"):
            check_store(self.store, arm, "ts40", other_build, "e" * 64)


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


class LiveCapabilitiesTest(unittest.TestCase):
    def test_the_receipts_languages_must_equal_the_binarys_live_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            binary = Path(tmp) / "noodl-eval"
            binary.write_text(
                "#!/bin/sh\necho '{\"analysis_languages\": [\"python\", \"go\"]}'\n"
            )
            binary.chmod(0o755)
            receipt = replace(_receipt("b" * 64), analysis_languages=("go", "python"))
            self.assertEqual(verify_live_capabilities(binary, receipt), ("go", "python"))
            forged = replace(receipt, analysis_languages=("go",))
            with self.assertRaisesRegex(StampError, r"reports capabilities \['go', 'python'\]"):
                verify_live_capabilities(binary, forged)


class HostCpuTest(unittest.TestCase):
    CPUINFO = (
        "processor\t: 0\nvendor_id\t: GenuineIntel\n"
        "model name\t: Intel(R) Xeon(R) CPU @ 2.80GHz\nflags\t\t: fpu\n"
    )

    def test_linux_cpuinfo_parses_to_the_model(self) -> None:
        self.assertEqual(
            format_host_cpu(cpu_model_from_cpuinfo(self.CPUINFO), 32),
            "Intel(R) Xeon(R) CPU @ 2.80GHz x32",
        )

    def test_a_cpuinfo_without_a_model_refuses(self) -> None:
        for text in ("processor\t: 0\n", "model name\t:   \n", ""):
            with self.subTest(text=text), self.assertRaisesRegex(StampError, "no CPU model"):
                cpu_model_from_cpuinfo(text)

    def test_the_macos_brand_string_parses_to_the_model(self) -> None:
        self.assertEqual(
            format_host_cpu(cpu_model_from_brand_string("Apple M4 Pro\n"), 12),
            "Apple M4 Pro x12",
        )

    def test_an_empty_brand_string_refuses(self) -> None:
        with self.assertRaisesRegex(StampError, "brand_string is empty"):
            cpu_model_from_brand_string(" \n")

    def test_an_undeterminable_cpu_count_refuses(self) -> None:
        for count in (None, 0):
            with self.subTest(count=count), self.assertRaisesRegex(StampError, "CPUs"):
                format_host_cpu("Apple M4 Pro", count)


class ReuseMarkerOrderTest(unittest.TestCase):
    """The REUSE preflight takes the source marker only as its LAST step: a
    refusal anywhere before it — including the host check — leaves the marker."""

    def test_a_late_refusal_leaves_the_source_marker_in_place(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            binary = root / "noodl-eval"
            binary.write_text(
                "#!/bin/sh\necho '{\"analysis_languages\": [\"go\", \"python\", "
                "\"typescript\"]}'\n"
            )
            binary.chmod(0o755)
            receipt = _receipt(_sha(binary.read_bytes()))
            receipt_path = root / "build-receipt.json"
            receipt_path.write_text(json.dumps(asdict(receipt)))
            verdict_path = root / "receipt-verdict.json"
            verdict_path.write_text(json.dumps({
                "schema": 2, "receipt_sha256": _sha(receipt_path.read_bytes()),
                "commit": receipt.commit, "tree_digest": receipt.tree_digest,
                "model_lock_sha256": receipt.model_lock_sha256,
                "rust_toolchain_sha256": _sha(receipt.rust_toolchain_toml.encode()),
                "checked": "test",
            }))
            jsonl = root / "ts40.jsonl"
            jsonl.write_bytes(b"{}\n")
            pins = root / "jsonl.SHA256SUMS"
            pins.write_text(f"{_sha(jsonl.read_bytes())}  ts40.jsonl\n")
            store = root / "shipped_treatment_ts40"
            store.mkdir()
            marker = CompletionMarker(
                arm="shipped_treatment", corpus="ts40", commit=COMMIT,
                binary_sha256=receipt.binary_sha256, corpus_sha256=_sha(jsonl.read_bytes()),
                reranker="rev",
            )
            (store / COMPLETION_MARKER).write_text(json.dumps(asdict(marker)))
            kwargs = {
                "arm": ARMS["levers_off_ablation"], "corpus": "ts40", "corpus_jsonl": jsonl,
                "store": store, "binary": binary, "receipt_path": receipt_path,
                "verdict_path": verdict_path, "requested_commit": COMMIT, "pins": pins,
            }
            with mock.patch("ttg.cell_stamps.host_cpu", side_effect=StampError("no cpu")):
                with self.assertRaisesRegex(StampError, "no cpu"):
                    cell_preflight(**kwargs)
            self.assertTrue((store / COMPLETION_MARKER).is_file(), "marker must survive")
            lines = cell_preflight(**kwargs)
            self.assertFalse((store / COMPLETION_MARKER).exists(), "now held by this run")
            self.assertTrue(consumed_marker(store, ARMS["levers_off_ablation"]).is_file())
            self.assertIn("host_cpu:", lines[-1])


class ReuseMarkerTest(unittest.TestCase):
    def test_the_consumed_marker_name_is_per_arm_and_off_the_live_name(self) -> None:
        store = Path("/s")
        held = consumed_marker(store, ARMS["levers_off_ablation"])
        self.assertEqual(held.parent, store)
        self.assertNotEqual(held.name, COMPLETION_MARKER)
        self.assertIn("levers_off_ablation", held.name)


if __name__ == "__main__":
    unittest.main()
