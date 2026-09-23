"""Per-cell provenance the eval report does not carry, verified at run time.

A `noodl-eval swe-bench` report names neither the engine it was built from nor
the reranker model it ranked with, and nothing checks the corpus bytes or the
store it ran in. Each of those has moved a TtG number before (engine drift, R22;
a reused store inflating a cell by +19.23 pp; a disk collapse deleting catalog
rows from a reused store). `run_arm.sh` therefore refuses a cell unless:

1. the build commit is a full 40-hex sha (the binary sha is not a reproduction
   target — `OUT_DIR` bakes the build path into it);
2. the corpus JSONL is byte-identical to its pin in `corpora/jsonl.SHA256SUMS`;
3. a FRESH-store arm starts in an absent or empty store, and a REUSE arm in a
   populated one;
4. after the run, the reranker installed under the store is exactly the
   revision and file digests the engine's `model.lock` pins (a cold cache
   resolves the model from its Hugging Face revision, so the lock alone does not
   prove what ran) — or, for an arm declared not to rank, that no model was
   installed at all.

The binary's compiled analysis languages (`noodl-eval capabilities`) are the
feature stamp: they come from the binary itself, not from an operator's claim.
"""

from __future__ import annotations

import hashlib
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path

from arms.arm_matrix import StoreMode

_BUILD_COMMIT = re.compile(r"\A[0-9a-f]{40}\Z")
_HASH_CHUNK = 1 << 20


class StampError(ValueError):
    """A cell's provenance cannot be established; the cell must not count."""


@dataclass(frozen=True)
class LockedFile:
    path: str
    sha256: str


@dataclass(frozen=True)
class ModelLock:
    """The reranker distribution identity a `model.lock` pins."""

    revision: str
    cache_dir: str
    files: tuple[LockedFile, ...]


def validated_build_commit(commit: str) -> str:
    if not _BUILD_COMMIT.fullmatch(commit):
        raise StampError(
            f"build commit must be a full 40-hex sha, got {commit!r} (the binary "
            "sha is not a reproduction target; the commit + features are)"
        )
    return commit


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(_HASH_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pinned_sha256(sums: Path, name: str) -> str:
    """The pinned digest for `name` in a `sha256sum`-format file; refuses when
    the name is absent — an unpinned corpus is unverifiable, not trusted."""
    pins = {
        entry_name: sha
        for sha, entry_name in (
            line.split(maxsplit=1) for line in sums.read_text().splitlines() if line.strip()
        )
    }
    try:
        return pins[name]
    except KeyError:
        raise StampError(f"{name!r} has no pin in {sums}") from None


def verify_corpus(jsonl: Path, corpus: str, sums: Path) -> str:
    """Return the JSONL's sha256 after checking it against its pin."""
    got = file_sha256(jsonl)
    want = pinned_sha256(sums, f"{corpus}.jsonl")
    if got != want:
        raise StampError(
            f"corpus {corpus!r}: {jsonl} has sha256 {got}, pinned {want}"
        )
    return got


def assert_store_mode(store: Path, mode: StoreMode) -> None:
    populated = store.is_dir() and any(store.iterdir())
    if mode is StoreMode.FRESH and populated:
        raise StampError(
            f"FRESH-store arm given a populated store {store}: every FRESH cell "
            "needs its own absent or empty store (a reused store can carry partial "
            "gold and stale catalog rows into the cell)"
        )
    if mode is StoreMode.FRESH and store.exists() and not store.is_dir():
        raise StampError(f"store {store} exists and is not a directory")
    if mode is StoreMode.REUSE and not populated:
        raise StampError(
            f"REUSE-store arm given an absent or empty store {store}: it must reuse "
            "the store its protocol names"
        )


def parse_model_lock(text: str) -> ModelLock:
    doc = tomllib.loads(text)
    try:
        return ModelLock(
            revision=doc["revision"],
            cache_dir=doc["cache_dir"],
            files=tuple(LockedFile(entry["path"], entry["sha256"]) for entry in doc["files"]),
        )
    except (KeyError, TypeError) as exc:
        raise StampError(f"model.lock is missing a required field: {exc}") from None


def verify_reranker_absent(store: Path, lock: ModelLock) -> None:
    """For an arm declared not to rank: the engine must not have installed the
    model into its store — an install means the declaration is wrong."""
    root = store / lock.cache_dir
    if root.exists():
        raise StampError(
            f"arm declared not to use the reranker, but {root} was installed: the "
            "arm's `ranks_with_reranker` declaration is wrong"
        )


def verify_reranker_install(store: Path, lock: ModelLock) -> str:
    """Return the locked revision after proving every locked file is installed
    under the store with its pinned digest."""
    if not lock.files:
        raise StampError("model.lock pins no files")
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
