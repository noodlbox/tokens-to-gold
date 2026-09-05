"""Provision corpus repo checkouts + emit a reproducible manifest.

A corpus JSONL lists (repo, base_commit) per instance; a third party must be
able to reconstruct the exact checkout SET, not just the instance list. This
clones each repo at its base_commit and records, per instance:

    instance_id, repo, base_commit, tree_sha, rs_file_count

- `tree_sha` (git `HEAD^{tree}` at base_commit) pins the checkout content, so a
  reprovision is verifiable against the manifest rather than trusting the ref.
- `rs_file_count` is the R-B2 comparability decider: the count of `.rs` files on
  disk in the checkout, excluding nothing (vendored `.rs` counts — file
  discovery does not know a file is vendored). If every ts40 + py_nosphinx
  checkout is 0, the rust-ON certification binary is discovery-equivalent to a
  rust-OFF build for those corpora, and one binary certifies the regression.

The clone (network, disk) is a lease step; `inspect_checkout` and the manifest
assembly are pure and unit-tested off-lease.
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path

# This script runs on a third party's own corpus JSONL (the "run on your own
# repo" path), so every field is untrusted input flowing into git args and
# filesystem paths. Validate at the boundary, fail closed.
_INSTANCE_ID = re.compile(r"\A[A-Za-z0-9._-]+\Z")   # one path segment, no '..'
_COMMIT = re.compile(r"\A[0-9a-f]{7,40}\Z")          # hex — cannot be a git flag
_REPO_SLUG = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]*/[A-Za-z0-9][A-Za-z0-9._-]*\Z")


class UnsafeCorpusInputError(ValueError):
    """A corpus field would inject a git argument or escape the checkout root."""


def _validated_commit(base_commit: str) -> str:
    if not _COMMIT.fullmatch(base_commit):
        raise UnsafeCorpusInputError(f"base_commit not a hex sha: {base_commit!r}")
    return base_commit


def _validated_url(repo: str) -> str:
    if repo.startswith("-"):
        raise UnsafeCorpusInputError(f"repo starts with '-': {repo!r}")
    if repo.startswith(("https://", "git@")):
        return repo
    if not _REPO_SLUG.fullmatch(repo):
        raise UnsafeCorpusInputError(f"repo not an owner/name slug or URL: {repo!r}")
    return f"https://github.com/{repo}.git"


def _validated_dest(checkouts_dir: Path, instance_id: str) -> Path:
    if not _INSTANCE_ID.fullmatch(instance_id) or instance_id in {".", ".."}:
        raise UnsafeCorpusInputError(f"unsafe instance_id: {instance_id!r}")
    root = checkouts_dir.resolve()
    dest = (root / instance_id).resolve()
    if dest != root / instance_id or root not in dest.parents:
        raise UnsafeCorpusInputError(
            f"instance_id escapes the checkout root: {instance_id!r}")
    return dest


@dataclass(frozen=True)
class CheckoutFacts:
    tree_sha: str
    rs_file_count: int


@dataclass(frozen=True)
class ManifestRow:
    instance_id: str
    repo: str
    base_commit: str
    tree_sha: str
    rs_file_count: int


def _git(checkout: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(checkout), *args],
        capture_output=True, text=True, check=True,
    ).stdout.strip()


def inspect_checkout(checkout: Path) -> CheckoutFacts:
    """Pin the checkout content (tree sha) and count `.rs` files on disk.

    Counts every `.rs` under the working tree except inside `.git/`, matching
    what analysis file-discovery walks — vendored/third-party `.rs` included."""
    tree_sha = _git(checkout, "rev-parse", "HEAD^{tree}")
    rs = sum(
        1 for p in checkout.rglob("*.rs")
        if ".git" not in p.relative_to(checkout).parts
    )
    return CheckoutFacts(tree_sha=tree_sha, rs_file_count=rs)


def provision_instance(repo: str, base_commit: str, dest: Path) -> CheckoutFacts:
    """Clone `repo` and check out `base_commit` into `dest`; return its facts.

    Fetches the single commit to keep provisioning cheap; fails closed if the
    commit is unreachable rather than silently landing on a default branch."""
    url = _validated_url(repo)
    commit = _validated_commit(base_commit)
    dest.mkdir(parents=True, exist_ok=True)
    _git(dest, "init", "-q")
    _git(dest, "remote", "add", "origin", url)
    # commit is validated hex and url is validated scheme/slug, so neither can
    # be read as a git flag (git fetch takes no `--` refspec separator).
    _git(dest, "fetch", "-q", "--depth", "1", "origin", commit)
    _git(dest, "checkout", "-q", "FETCH_HEAD")
    return inspect_checkout(dest)


def build_manifest(jsonl: Path, checkouts_dir: Path) -> list[ManifestRow]:
    rows: list[ManifestRow] = []
    for line in jsonl.read_text().splitlines():
        if not line.strip():
            continue
        inst = json.loads(line)
        dest = _validated_dest(checkouts_dir, inst["instance_id"])
        facts = provision_instance(inst["repo"], inst["base_commit"], dest)
        rows.append(ManifestRow(
            instance_id=inst["instance_id"], repo=inst["repo"],
            base_commit=inst["base_commit"],
            tree_sha=facts.tree_sha, rs_file_count=facts.rs_file_count,
        ))
    return rows


def write_manifest(rows: list[ManifestRow], out: Path) -> None:
    out.write_text("".join(json.dumps(asdict(r)) + "\n" for r in rows))


def ts_py_discovery_equivalent(rows: list[ManifestRow]) -> bool:
    """R-B2: rust ON/OFF is discovery-equivalent for these corpora iff no
    checkout carries a `.rs` file."""
    return all(r.rs_file_count == 0 for r in rows)
