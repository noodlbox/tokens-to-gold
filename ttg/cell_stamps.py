"""Every provenance stamp a TtG cell carries, collected AND verified in one place.

A `noodl-eval swe-bench` report names neither the engine it was built from nor
the reranker it ranked with, and nothing checks the corpus bytes or the store it
ran in. Each of those has moved a TtG number before (engine drift, R22; a reused
store inflating a cell by +19.23 pp; a disk collapse deleting catalog rows from
a reused store). This module owns every stamp; the shell runners only call it.

THE ENGINE BUILD RECEIPT (lane 4F, ruling C-F1 (A))
---------------------------------------------------
`noodl-eval` embeds no commit (only `nbx` bakes `NOODLBOX_GIT_SHA`), so the
commit cannot be read back from the binary. It is proven instead by a receipt
written by the SAME step that builds (`arms/build_engine.sh`):

1. the synced engine source tree is re-identified on the build host — the git
   blob id of every file, as a sorted (kind, blob, path) list digest — and must
   equal the digest of `git ls-tree -r <commit>` computed where the history is
   (any drifted, extra or missing file refuses; the sync-excluded paths are
   excluded on both sides);
2. the engine is built from that tree and the tree is re-identified after the
   build (a build that writes into its own sources refuses);
3. the receipt records {commit, tree digest, binary sha256, cargo profile and
   features, the toolchain file and `rustc -V`, the binary's own
   `capabilities`, and the engine's `model.lock` text + sha256}.

A cell then refuses unless the binary it is about to run hashes to the
receipt's `binary_sha256` and the receipt's commit is the requested one. The
reranker lock comes from the receipt — i.e. from the verified engine tree — so
it is bound to the commit by construction, never supplied by an operator.

CELL STAMPS
-----------
Before the engine runs (`cell_preflight`): the receipt/binary binding; the
corpus JSONL against `corpora/jsonl.SHA256SUMS`; the corpus language against
the binary's capabilities; the store policy — a FRESH cell's own absent-or-empty
store, or a REUSE cell's source store carrying a completion marker from the SAME
build and corpus. After it (`cell_postrun`): a ranking arm must have installed
exactly the locked reranker; a non-ranking arm must have installed no reranker
of ANY revision. Only then is the report moved from its `.partial` name into
place and the store's completion marker written.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

from arms.arm_matrix import Arm, FreshStore
from ttg.preflight import analysis_languages, require_corpus_support

RECEIPT_SCHEMA: Final = 1
MODEL_LOCK_PATH: Final = "assets/models/reranker/model.lock"
TOOLCHAIN_PATH: Final = "rust-toolchain.toml"
COMPLETION_MARKER: Final = ".ttg-cell-complete.json"
PARTIAL_SUFFIX: Final = ".partial"
ENGINE_TREE_EXCLUDES: Final = frozenset(
    {"target", ".git", ".workspace-state", ".p93-evidence", ".nbx", "node_modules"}
)
"""Path components never part of the engine tree identity. Mirrors the
noodlbox-app `.crabbox.yaml` `sync.exclude` list (rsync semantics: the name
matches at any depth), so the git side and the synced side leave out the same
paths."""

_SHA256: Final = re.compile(r"\A[0-9a-f]{64}\Z")
_COMMIT: Final = re.compile(r"\A[0-9a-f]{40}\Z")
_HASH_CHUNK: Final = 1 << 20
_GIT_SYMLINK_MODE: Final = "120000"


class StampError(ValueError):
    """A cell's provenance cannot be established; the cell must not count."""


# --- primitives -------------------------------------------------------------


def validated_commit(commit: str) -> str:
    if not _COMMIT.fullmatch(commit):
        raise StampError(f"a commit must be a full 40-hex sha, got {commit!r}")
    return commit


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
                digest.update(chunk)
    except OSError as exc:
        raise StampError(f"cannot read {path}: {exc}") from None
    return digest.hexdigest()


def _git_blob_id(data: bytes) -> str:
    return hashlib.sha1(b"blob %d\0" % len(data) + data, usedforsecurity=False).hexdigest()


def _read_text(path: Path, what: str) -> str:
    try:
        return path.read_text()
    except OSError as exc:
        raise StampError(f"cannot read the {what} {path}: {exc}") from None


# --- engine tree identity ---------------------------------------------------


@dataclass(frozen=True, order=True)
class TreeEntry:
    path: str
    kind: str
    """`f` for a regular file, `l` for a symlink (git mode 120000)."""
    blob: str


def _excluded(path: str) -> bool:
    return any(part in ENGINE_TREE_EXCLUDES for part in path.split("/"))


def tree_digest(entries: list[TreeEntry]) -> str:
    digest = hashlib.sha256()
    for entry in sorted(entries):
        digest.update(f"{entry.kind} {entry.blob} {entry.path}\0".encode())
    return digest.hexdigest()


def tree_entries_from_git(repo: Path, commit: str) -> list[TreeEntry]:
    """The engine tree as git records it at `commit`, minus excluded paths."""
    proc = subprocess.run(
        ["git", "-C", str(repo), "ls-tree", "-r", "-z", "--full-tree",
         validated_commit(commit)],
        capture_output=True, check=False,
    )
    if proc.returncode != 0:
        raise StampError(f"git ls-tree {commit} failed: {proc.stderr.decode().strip()}")
    entries = []
    for record in filter(None, proc.stdout.split(b"\0")):
        meta, path = record.decode().split("\t", 1)
        mode, kind, blob = meta.split()
        if kind != "blob":
            raise StampError(f"engine tree entry {path!r} is a {kind}, not a file")
        if _excluded(path):
            continue
        entries.append(TreeEntry(path, "l" if mode == _GIT_SYMLINK_MODE else "f", blob))
    return entries


def tree_entries_from_disk(root: Path) -> list[TreeEntry]:
    """The synced engine tree as it is on disk, minus excluded paths."""
    entries = []
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        base = Path(dirpath)
        kept = []
        for name in dirnames:
            if name in ENGINE_TREE_EXCLUDES:
                continue
            if (base / name).is_symlink():
                filenames.append(name)
            else:
                kept.append(name)
        dirnames[:] = kept
        for name in filenames:
            path = base / name
            rel = path.relative_to(root).as_posix()
            if _excluded(rel):
                continue
            if path.is_symlink():
                entries.append(TreeEntry(rel, "l", _git_blob_id(os.readlink(path).encode())))
            else:
                entries.append(TreeEntry(rel, "f", _git_blob_id(path.read_bytes())))
    return entries


def verify_engine_tree(root: Path, expected_digest: str) -> str:
    got = tree_digest(tree_entries_from_disk(root))
    if got != expected_digest:
        raise StampError(
            f"engine source tree at {root} has identity {got}, the commit's is "
            f"{expected_digest}: a file drifted, was added, or is missing"
        )
    return got


# --- the build receipt ------------------------------------------------------


@dataclass(frozen=True)
class BuildReceipt:
    schema: int
    commit: str
    tree_digest: str
    binary_sha256: str
    cargo_profile: str
    cargo_features: str
    rust_toolchain_toml: str
    rustc_version: str
    analysis_languages: tuple[str, ...]
    model_lock_text: str
    model_lock_sha256: str


def write_build_receipt(
    *, src: Path, commit: str, expected_tree_digest: str, binary: Path,
    profile: str, features: str, out: Path,
) -> BuildReceipt:
    """Called by the build step, AFTER it built `binary` from `src`: the tree is
    re-identified (a build must not have written into its own sources)."""
    tree = verify_engine_tree(src, expected_tree_digest)
    rustc = subprocess.run(
        ["rustc", "-V"], cwd=src, capture_output=True, text=True, check=False
    )
    if rustc.returncode != 0:
        raise StampError(f"`rustc -V` failed in {src}: {rustc.stderr.strip()}")
    lock_text = _read_text(src / MODEL_LOCK_PATH, "engine model.lock")
    parse_model_lock(lock_text)
    receipt = BuildReceipt(
        schema=RECEIPT_SCHEMA,
        commit=validated_commit(commit),
        tree_digest=tree,
        binary_sha256=file_sha256(binary),
        cargo_profile=profile,
        cargo_features=features,
        rust_toolchain_toml=_read_text(src / TOOLCHAIN_PATH, "toolchain file"),
        rustc_version=rustc.stdout.strip(),
        analysis_languages=tuple(sorted(analysis_languages(str(binary)))),
        model_lock_text=lock_text,
        model_lock_sha256=hashlib.sha256(lock_text.encode()).hexdigest(),
    )
    out.write_text(json.dumps(asdict(receipt), indent=2, sort_keys=True) + "\n")
    return receipt


def load_build_receipt(path: Path) -> BuildReceipt:
    try:
        doc = json.loads(_read_text(path, "build receipt"))
        receipt = BuildReceipt(
            **{**doc, "analysis_languages": tuple(doc["analysis_languages"])}
        )
    except (json.JSONDecodeError, TypeError, KeyError) as exc:
        raise StampError(f"build receipt {path} is malformed: {exc}") from None
    if receipt.schema != RECEIPT_SCHEMA:
        raise StampError(f"build receipt {path} has schema {receipt.schema}")
    for name in ("tree_digest", "binary_sha256", "model_lock_sha256"):
        if not _SHA256.fullmatch(str(getattr(receipt, name))):
            raise StampError(f"build receipt {path}: {name} is not a sha256")
    validated_commit(receipt.commit)
    if hashlib.sha256(receipt.model_lock_text.encode()).hexdigest() != receipt.model_lock_sha256:
        raise StampError(f"build receipt {path}: model.lock text does not match its digest")
    return receipt


def verify_binary_against_receipt(binary: Path, receipt: BuildReceipt, requested_commit: str) -> None:
    if receipt.commit != validated_commit(requested_commit):
        raise StampError(
            f"the build receipt is for commit {receipt.commit}, the cell requested "
            f"{requested_commit}"
        )
    got = file_sha256(binary)
    if got != receipt.binary_sha256:
        raise StampError(
            f"binary {binary} has sha256 {got}, the build receipt's binary is "
            f"{receipt.binary_sha256}: this is not the binary that commit built"
        )


# --- the reranker lock ------------------------------------------------------


@dataclass(frozen=True)
class LockedFile:
    path: str
    sha256: str


@dataclass(frozen=True)
class ModelLock:
    hf_repo: str
    revision: str
    cache_dir: str
    files: tuple[LockedFile, ...]

    @property
    def model_root(self) -> Path:
        """The reranker namespace every revision installs under
        (`models/reranker` for `models/reranker/<key>/<revision>`)."""
        return _model_root(self.cache_dir)


def _model_root(cache_dir: str) -> Path:
    parts = Path(cache_dir).parts
    if len(parts) < 3:
        raise StampError(f"model.lock cache_dir {cache_dir!r} has no model root")
    return Path(*parts[:-2])


def _str_field(table: dict[str, object], name: str) -> str:
    value = table.get(name)
    if not isinstance(value, str) or not value:
        raise StampError(f"model.lock field {name!r} must be a non-empty string")
    return value


def parse_model_lock(text: str) -> ModelLock:
    try:
        doc = tomllib.loads(text)
    except tomllib.TOMLDecodeError as exc:
        raise StampError(f"model.lock is not valid TOML: {exc}") from None
    files = doc.get("files")
    if not isinstance(files, list) or not files:
        raise StampError("model.lock pins no files")
    locked = []
    for entry in files:
        if not isinstance(entry, dict):
            raise StampError("model.lock [[files]] entry is not a table")
        sha = _str_field(entry, "sha256")
        if not _SHA256.fullmatch(sha):
            raise StampError(f"model.lock sha256 {sha!r} is not a sha256")
        locked.append(LockedFile(_str_field(entry, "path"), sha))
    cache_dir = _str_field(doc, "cache_dir")
    _model_root(cache_dir)
    return ModelLock(
        hf_repo=_str_field(doc, "hf_repo"),
        revision=_str_field(doc, "revision"),
        cache_dir=cache_dir,
        files=tuple(locked),
    )


def verify_reranker_install(store: Path, lock: ModelLock) -> str:
    root = store / lock.cache_dir
    for locked in lock.files:
        installed = root / locked.path
        if not installed.is_file():
            raise StampError(f"reranker file {installed} is not installed")
        got = file_sha256(installed)
        if got != locked.sha256:
            raise StampError(
                f"reranker file {installed} has sha256 {got}, locked {locked.sha256}"
            )
    return lock.revision


def verify_no_reranker_install(store: Path, lock: ModelLock) -> None:
    """A non-ranking arm installs nothing under the reranker namespace — no
    revision, no staging `.partial`, no install lock."""
    root = store / lock.model_root
    if root.exists() and any(root.iterdir()):
        raise StampError(
            f"arm declared not to use the reranker, but {root} holds an install: "
            "the arm's `ranks_with_reranker` declaration is wrong"
        )


# --- corpus pins ------------------------------------------------------------


def pinned_sha256(sums: Path, name: str) -> str:
    pins = {}
    for number, line in enumerate(_read_text(sums, "pin file").splitlines(), 1):
        if not line.strip():
            continue
        fields = line.split()
        if len(fields) != 2 or not _SHA256.fullmatch(fields[0]):
            raise StampError(f"{sums}:{number} is not a `<sha256>  <name>` line")
        pins[fields[1]] = fields[0]
    try:
        return pins[name]
    except KeyError:
        raise StampError(f"{name!r} has no pin in {sums}") from None


def verify_corpus(jsonl: Path, corpus: str, sums: Path) -> str:
    got = file_sha256(jsonl)
    want = pinned_sha256(sums, f"{corpus}.jsonl")
    if got != want:
        raise StampError(f"corpus {corpus!r}: {jsonl} has sha256 {got}, pinned {want}")
    return got


# --- store policy -----------------------------------------------------------


@dataclass(frozen=True)
class CompletionMarker:
    """Written into a FRESH cell's store only after the cell fully succeeded."""

    arm: str
    corpus: str
    commit: str
    binary_sha256: str
    corpus_sha256: str
    reranker: str


def _populated(store: Path) -> bool:
    return store.is_dir() and any(store.iterdir())


def assert_store_ready(
    store: Path, arm: Arm, corpus: str, receipt: BuildReceipt, corpus_sha: str
) -> str:
    if isinstance(arm.store, FreshStore):
        if store.exists() and not store.is_dir():
            raise StampError(f"store {store} exists and is not a directory")
        if _populated(store):
            raise StampError(
                f"FRESH-store arm {arm.name!r} given a populated store {store}: "
                "every FRESH cell needs its own absent or empty store"
            )
        return "fresh (verified absent or empty)"
    source = arm.store.of
    marker_path = store / COMPLETION_MARKER
    if not marker_path.is_file():
        raise StampError(
            f"REUSE arm {arm.name!r}: {store} has no completion marker — its source "
            f"cell {source!r} did not finish and stamp"
        )
    try:
        marker = CompletionMarker(**json.loads(marker_path.read_text()))
    except (json.JSONDecodeError, TypeError) as exc:
        raise StampError(f"completion marker {marker_path} is malformed: {exc}") from None
    expected = (source, corpus, receipt.commit, receipt.binary_sha256, corpus_sha)
    got = (marker.arm, marker.corpus, marker.commit, marker.binary_sha256,
           marker.corpus_sha256)
    if got != expected:
        raise StampError(
            f"REUSE arm {arm.name!r}: {store} was completed by {got}, this cell "
            f"needs {expected}"
        )
    return f"reuse of {source}_{corpus} (verified completion marker)"


# --- host ---------------------------------------------------------------------


def host_cpu() -> str:
    """The machine class a cell ran on (model name + logical CPUs). Wall-clock
    numbers are only comparable within one class, so every manifest names it."""
    cpuinfo = Path("/proc/cpuinfo")
    model = ""
    if cpuinfo.is_file():
        model = next(
            (line.split(":", 1)[1].strip() for line in cpuinfo.read_text().splitlines()
             if line.startswith("model name")),
            "",
        )
    else:
        proc = subprocess.run(
            ["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True,
            check=False,
        )
        model = proc.stdout.strip()
    if not model:
        raise StampError("cannot determine the host CPU model")
    return f"{model} x{os.cpu_count()}"


# --- the two cell checkpoints -----------------------------------------------


def cell_preflight(
    *, arm: Arm, corpus: str, corpus_jsonl: Path, store: Path, binary: Path,
    receipt_path: Path, requested_commit: str, pins: Path,
) -> list[str]:
    """Every pre-run refusal; returns the verified manifest lines."""
    receipt = load_build_receipt(receipt_path)
    verify_binary_against_receipt(binary, receipt, requested_commit)
    lock = parse_model_lock(receipt.model_lock_text)
    require_corpus_support(str(binary), corpus)
    corpus_sha = verify_corpus(corpus_jsonl, corpus, pins)
    store_line = assert_store_ready(store, arm, corpus, receipt, corpus_sha)
    return [
        f"build_commit: {receipt.commit} (build receipt; binary sha256 verified)",
        f"engine_tree:  {receipt.tree_digest} (recomputed at build)",
        f"binary_sha256:{receipt.binary_sha256} (verified)",
        f"cargo:        profile={receipt.cargo_profile} features={receipt.cargo_features}",
        f"rustc:        {receipt.rustc_version}",
        f"capabilities: {','.join(receipt.analysis_languages)} (corpus language verified)",
        f"model_lock:   {lock.hf_repo}@{lock.revision} sha256={receipt.model_lock_sha256}",
        f"corpus_sha256:{corpus_sha} (pinned)",
        f"store:        {store_line}",
        f"intent:       {arm.intent.value} (declared)",
        f"host_cpu:     {host_cpu()}",
    ]


def cell_postrun(
    *, arm: Arm, corpus: str, corpus_jsonl: Path, store: Path, receipt_path: Path,
    report: Path, pins: Path,
) -> list[str]:
    """After a successful engine run: prove the reranker, then publish the report
    and (FRESH) mark the store complete. Nothing is published on a refusal."""
    receipt = load_build_receipt(receipt_path)
    lock = parse_model_lock(receipt.model_lock_text)
    if arm.ranks_with_reranker:
        reranker = verify_reranker_install(store, lock)
        line = f"reranker_rev: {reranker} (installed files match the engine's model.lock)"
    else:
        verify_no_reranker_install(store, lock)
        reranker = "none"
        line = "reranker_rev: none (non-ranking arm; no reranker of any revision installed)"
    partial = report.with_name(report.name + PARTIAL_SUFFIX)
    if not partial.is_file():
        raise StampError(f"engine report {partial} is missing")
    if isinstance(arm.store, FreshStore):
        marker = CompletionMarker(
            arm=arm.name, corpus=corpus, commit=receipt.commit,
            binary_sha256=receipt.binary_sha256,
            corpus_sha256=verify_corpus(corpus_jsonl, corpus, pins), reranker=reranker,
        )
        (store / COMPLETION_MARKER).write_text(json.dumps(asdict(marker), sort_keys=True))
    partial.replace(report)
    return [line, f"report:       {report} (published after every stamp passed)"]
