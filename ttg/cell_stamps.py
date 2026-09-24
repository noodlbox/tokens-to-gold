"""Every provenance stamp a TtG cell carries, collected AND verified in one place.

A `noodl-eval swe-bench` report names neither the engine it was built from nor
the reranker it ranked with, and nothing checks the corpus bytes or the store it
ran in. Each of those has moved a TtG number before (engine drift, R22; a reused
store inflating a cell by +19.23 pp; a disk collapse deleting catalog rows from
a reused store). This module owns every stamp; the shell runners only call it.

THE ENGINE BUILD RECEIPT AND ITS VERDICT (lane 4F, ruling C-F1 (A) + round 2)
-----------------------------------------------------------------------------
`noodl-eval` embeds no commit (only `nbx` bakes `NOODLBOX_GIT_SHA`), so the
commit cannot be read back from the binary. It is proven in two halves:

1. THE BUILD (`arms/build_engine.sh`, on the build host, which has no `.git`)
   MEASURES the synced tree's identity — the git blob id of every file, as a
   sorted (kind, blob, path) digest — builds the engine from it, re-measures
   (a build that wrote into its own sources refuses), and writes a receipt:
   {commit, the measured tree digest, binary sha256, cargo profile + features,
   `rust-toolchain.toml` text, `rustc -V`, the binary's capabilities, and the
   engine's `model.lock` text + sha256}. It compares the tree to nothing —
   there is no expected digest to pass in, so none can be copied from a
   refusal and passed back.
2. THE VERDICT (`verify_receipt`, run where the engine's git history is) DERIVES
   what the commit's tree is: the receipt's tree digest must equal
   `git ls-tree -r <commit>`'s, and its `model.lock` and toolchain text must
   equal `git show <commit>:<path>`. It writes a verdict bound to the receipt's
   bytes (sha256).

A cell then refuses unless the verdict matches its receipt, the binary it is
about to run hashes to the receipt's `binary_sha256`, the receipt's commit is
the requested one, and the binary's LIVE capabilities equal the receipt's. The
reranker lock is the receipt's — the verified engine tree's — so it is bound to
the commit, never supplied by an operator. What remains trusted is only the
tree -> binary link inside the build step, which the ruling accepts.

CELL STAMPS
-----------
Before the engine runs (`cell_preflight`): the verdict/receipt/binary binding;
live capabilities; the corpus JSONL against `corpora/jsonl.SHA256SUMS`; the
store policy — a FRESH cell's own absent-or-empty store, or a REUSE cell's
source store carrying a completion marker from the SAME build and corpus, which
the REUSE preflight CONSUMES (renames) so a REUSE run that dies can never leave
a damaged store marked complete. After it (`cell_postrun`): a ranking arm must
have installed exactly the locked reranker, a non-ranking arm no reranker of
ANY revision; only then is the report moved from `.partial` into place, and
then the store marked complete (FRESH) or its marker restored (REUSE).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Final

from arms.arm_matrix import Arm, FreshStore
from ttg.preflight import analysis_languages, require_corpus_support

RECEIPT_SCHEMA: Final = 2
VERDICT_SCHEMA: Final = 2
MODEL_LOCK_PATH: Final = "assets/models/reranker/model.lock"
TOOLCHAIN_PATH: Final = "rust-toolchain.toml"
COMPLETION_MARKER: Final = ".ttg-cell-complete.json"
CONSUMED_MARKER_SUFFIX: Final = ".in-use"
PARTIAL_SUFFIX: Final = ".partial"
ENGINE_TREE_EXCLUDES: Final = frozenset(
    {
        "target",
        ".git",
        ".workspace-state",
        ".p93-evidence",
        ".nbx",
        "node_modules",
        ".crabbox",
    }
)
"""Path components never part of the engine tree identity (the name matches
at any depth). Two sources:

- the noodlbox-app `.crabbox.yaml` `sync.exclude` list (rsync semantics), so
  the git side and the synced side leave out the same paths;
- `.crabbox`, the lease-side run-state directory crabbox itself writes into
  the synced root (run history, logs). It is never synced from the Mac and no
  engine commit tracks a `.crabbox` path, so it is bookkeeping, not source.
  Without it every build on a used lease measured a drifted tree.

Any other file that is on disk but not in the commit still changes the
identity."""

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


def _read_bytes(path: Path) -> bytes:
    try:
        return path.read_bytes()
    except OSError as exc:
        raise StampError(f"cannot read {path}: {exc}") from None


def _read_text(path: Path, what: str) -> str:
    try:
        return path.read_text()
    except (OSError, UnicodeDecodeError) as exc:
        raise StampError(f"cannot read the {what} {path}: {exc}") from None


def _run(argv: list[str], what: str, cwd: Path | None = None) -> bytes:
    try:
        proc = subprocess.run(argv, cwd=cwd, capture_output=True, check=False)
    except OSError as exc:
        raise StampError(f"cannot run {what} ({argv[0]}): {exc}") from None
    if proc.returncode != 0:
        raise StampError(f"{what} failed: {proc.stderr.decode(errors='replace').strip()}")
    return proc.stdout


def _text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def _decode(data: bytes, what: str) -> str:
    try:
        return data.decode()
    except UnicodeDecodeError as exc:
        raise StampError(f"{what} is not UTF-8: {exc}") from None


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
    out = _run(
        ["git", "-C", str(repo), "ls-tree", "-r", "-z", "--full-tree",
         validated_commit(commit)],
        f"git ls-tree {commit}",
    )
    entries = []
    for record in filter(None, out.split(b"\0")):
        meta, path = _decode(record, "a git ls-tree record").split("\t", 1)
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
                entries.append(TreeEntry(rel, "f", _git_blob_id(_read_bytes(path))))
    return entries


def measure_engine_tree(root: Path) -> str:
    return tree_digest(tree_entries_from_disk(root))


def git_show(repo: Path, commit: str, path: str) -> str:
    return _decode(
        _run(["git", "-C", str(repo), "show", f"{validated_commit(commit)}:{path}"],
             f"git show {commit}:{path}"),
        f"{commit}:{path}",
    )


# --- the build receipt ------------------------------------------------------


@dataclass(frozen=True)
class BuildReceipt:
    schema: int
    commit: str
    tree_digest: str
    """MEASURED on the build host; `verify_receipt` compares it to git."""
    binary_sha256: str
    cargo_profile: str
    cargo_features: str
    rust_toolchain_toml: str
    rustc_version: str
    analysis_languages: tuple[str, ...]
    model_lock_text: str
    model_lock_sha256: str


def write_build_receipt(
    *, src: Path, commit: str, pre_build_tree_digest: str, binary: Path,
    profile: str, features: str, out: Path,
) -> BuildReceipt:
    """Called by the build step AFTER it built `binary` from `src`. The tree is
    re-measured and must equal what it measured before the build."""
    tree = measure_engine_tree(src)
    if tree != pre_build_tree_digest:
        raise StampError(
            f"the engine tree at {src} changed during the build: the build wrote into "
            "its own sources"
        )
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
        rustc_version=_decode(_run(["rustc", "-V"], "rustc -V", cwd=src), "rustc -V").strip(),
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


# --- the receipt verdict (git side) -----------------------------------------


@dataclass(frozen=True)
class ReceiptVerdict:
    """Written only by `verify_receipt`: the receipt's claims checked against
    the engine's git history, bound to the exact receipt bytes."""

    schema: int
    receipt_sha256: str
    commit: str
    tree_digest: str
    model_lock_sha256: str
    rust_toolchain_sha256: str
    checked: str


def verify_receipt(*, engine_repo: Path, receipt_path: Path, out: Path) -> ReceiptVerdict:
    """The commit's tree identity, lock and toolchain are DERIVED from git
    history here — never an input — and must equal the receipt's."""
    receipt = load_build_receipt(receipt_path)
    derived = tree_digest(tree_entries_from_git(engine_repo, receipt.commit))
    if receipt.tree_digest != derived:
        raise StampError(
            f"the receipt's tree is not commit {receipt.commit}'s tree: the build host's "
            "sources drifted from the commit"
        )
    if receipt.model_lock_text != git_show(engine_repo, receipt.commit, MODEL_LOCK_PATH):
        raise StampError(f"the receipt's model.lock is not commit {receipt.commit}'s")
    if receipt.rust_toolchain_toml != git_show(engine_repo, receipt.commit, TOOLCHAIN_PATH):
        raise StampError(f"the receipt's rust-toolchain.toml is not commit {receipt.commit}'s")
    verdict = ReceiptVerdict(
        schema=VERDICT_SCHEMA,
        receipt_sha256=file_sha256(receipt_path),
        commit=receipt.commit,
        tree_digest=derived,
        model_lock_sha256=receipt.model_lock_sha256,
        rust_toolchain_sha256=_text_sha256(receipt.rust_toolchain_toml),
        checked="tree digest vs git ls-tree -r; model.lock + rust-toolchain.toml vs git show",
    )
    out.write_text(json.dumps(asdict(verdict), indent=2, sort_keys=True) + "\n")
    return verdict


def load_receipt_verdict(path: Path, receipt_path: Path, receipt: BuildReceipt) -> ReceiptVerdict:
    """The verdict must have been issued for exactly this receipt: its bytes,
    and every identity it vouches for. Stamps print the RECEIPT's values; the
    verdict only contributes the fact that they were checked against git."""
    try:
        verdict = ReceiptVerdict(**json.loads(_read_text(path, "receipt verdict")))
    except (json.JSONDecodeError, TypeError) as exc:
        raise StampError(f"receipt verdict {path} is malformed: {exc}") from None
    if verdict.schema != VERDICT_SCHEMA:
        raise StampError(f"receipt verdict {path} has schema {verdict.schema}")
    if verdict.receipt_sha256 != file_sha256(receipt_path):
        raise StampError(
            f"receipt verdict {path} was not issued for {receipt_path}: run "
            "`ttg.cli verify-receipt` against the engine's git history"
        )
    vouched = (verdict.commit, verdict.tree_digest, verdict.model_lock_sha256,
               verdict.rust_toolchain_sha256)
    claimed = (receipt.commit, receipt.tree_digest, receipt.model_lock_sha256,
               _text_sha256(receipt.rust_toolchain_toml))
    if vouched != claimed:
        raise StampError(
            f"receipt verdict {path} vouches for {vouched}, the receipt claims {claimed}"
        )
    return verdict


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


def verify_live_capabilities(binary: Path, receipt: BuildReceipt) -> tuple[str, ...]:
    live = tuple(sorted(analysis_languages(str(binary))))
    if live != receipt.analysis_languages:
        raise StampError(
            f"binary {binary} reports capabilities {list(live)}, the build receipt "
            f"claims {list(receipt.analysis_languages)}"
        )
    return live


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


def consumed_marker(store: Path, arm: Arm) -> Path:
    """Where a REUSE cell holds its source store's marker while it runs."""
    return store / f"{COMPLETION_MARKER}{CONSUMED_MARKER_SUFFIX}.{arm.name}"


def check_store(
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
            f"cell {source!r} did not finish and stamp, or an earlier REUSE run on it "
            "did not complete"
        )
    try:
        marker = CompletionMarker(**json.loads(_read_text(marker_path, "completion marker")))
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
    return f"reuse of {source}_{corpus} (verified completion marker, now held by this run)"


# --- host -------------------------------------------------------------------


def cpu_model_from_cpuinfo(text: str) -> str:
    """The `model name` of a Linux `/proc/cpuinfo`; refuses when there is none."""
    for line in text.splitlines():
        key, sep, value = line.partition(":")
        if sep and key.strip() == "model name" and value.strip():
            return value.strip()
    raise StampError("/proc/cpuinfo names no CPU model")


def cpu_model_from_brand_string(text: str) -> str:
    """The macOS `machdep.cpu.brand_string`; refuses when it is empty."""
    model = text.strip()
    if not model:
        raise StampError("machdep.cpu.brand_string is empty")
    return model


def format_host_cpu(model: str, usable_cpus: int | None) -> str:
    if usable_cpus is None or usable_cpus < 1:
        raise StampError(f"cannot determine the CPUs this process may use ({usable_cpus!r})")
    return f"{model} x{usable_cpus}"


def usable_cpu_count() -> int | None:
    """The CPUs this process may run on — its affinity mask where the platform
    has one (`os.process_cpu_count` semantics), else the host count."""
    if sys.platform == "linux":
        return len(os.sched_getaffinity(0))
    return os.cpu_count()


def host_cpu() -> str:
    """The machine class a cell ran on. Wall-clock numbers are only comparable
    within one class, so every manifest names it — or the cell refuses."""
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.is_file():
        model = cpu_model_from_cpuinfo(_read_text(cpuinfo, "cpuinfo"))
    else:
        model = cpu_model_from_brand_string(_decode(
            _run(["sysctl", "-n", "machdep.cpu.brand_string"], "sysctl brand string"),
            "sysctl output",
        ))
    return format_host_cpu(model, usable_cpu_count())


# --- the two cell checkpoints -----------------------------------------------


def cell_preflight(
    *, arm: Arm, corpus: str, corpus_jsonl: Path, store: Path, binary: Path,
    receipt_path: Path, verdict_path: Path, requested_commit: str, pins: Path,
) -> list[str]:
    """Every pre-run refusal; returns the verified manifest lines. The one side
    effect — a REUSE cell taking its source store's completion marker — happens
    only after every check passed."""
    receipt = load_build_receipt(receipt_path)
    load_receipt_verdict(verdict_path, receipt_path, receipt)
    verify_binary_against_receipt(binary, receipt, requested_commit)
    live = verify_live_capabilities(binary, receipt)
    lock = parse_model_lock(receipt.model_lock_text)
    require_corpus_support(str(binary), corpus)
    corpus_sha = verify_corpus(corpus_jsonl, corpus, pins)
    store_line = check_store(store, arm, corpus, receipt, corpus_sha)
    lines = [
        f"build_commit: {receipt.commit} (receipt; verified against git history by "
        f"verdict {file_sha256(verdict_path)}; binary sha256 verified)",
        f"engine_tree:  {receipt.tree_digest} (receipt; = git ls-tree -r per the verdict)",
        f"binary_sha256:{receipt.binary_sha256} (verified)",
        f"cargo:        profile={receipt.cargo_profile} features={receipt.cargo_features}",
        f"rustc:        {receipt.rustc_version}",
        f"capabilities: {','.join(live)} (live; equals the receipt; corpus language verified)",
        f"model_lock:   {lock.hf_repo}@{lock.revision} sha256={receipt.model_lock_sha256} "
        "(receipt; = git show per the verdict)",
        f"corpus_sha256:{corpus_sha} (pinned)",
        f"store:        {store_line}",
        f"intent:       {arm.intent.value} (declared)",
        f"host_cpu:     {host_cpu()}",
    ]
    # The ONLY side effect, and the last step: every check above has passed.
    if not isinstance(arm.store, FreshStore):
        (store / COMPLETION_MARKER).replace(consumed_marker(store, arm))
    return lines


def cell_postrun(
    *, arm: Arm, corpus: str, corpus_jsonl: Path, store: Path, binary: Path,
    receipt_path: Path, verdict_path: Path, report: Path, pins: Path,
) -> list[str]:
    """After a successful engine run: re-check the cell's pre-run receipt copy
    (against its verdict and the binary), prove the reranker, publish the
    report, then (FRESH) mark the store complete or (REUSE) give its marker
    back. Nothing is published or marked on a refusal."""
    receipt = load_build_receipt(receipt_path)
    load_receipt_verdict(verdict_path, receipt_path, receipt)
    verify_binary_against_receipt(binary, receipt, receipt.commit)
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
    partial.replace(report)
    if isinstance(arm.store, FreshStore):
        marker = CompletionMarker(
            arm=arm.name, corpus=corpus, commit=receipt.commit,
            binary_sha256=receipt.binary_sha256,
            corpus_sha256=verify_corpus(corpus_jsonl, corpus, pins), reranker=reranker,
        )
        (store / COMPLETION_MARKER).write_text(json.dumps(asdict(marker), sort_keys=True))
    else:
        consumed_marker(store, arm).replace(store / COMPLETION_MARKER)
    return [line, f"report:       {report} (published after every stamp passed)"]
