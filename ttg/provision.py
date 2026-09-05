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
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path


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
    dest.mkdir(parents=True, exist_ok=True)
    url = repo if repo.startswith(("http://", "https://", "git@")) \
        else f"https://github.com/{repo}.git"
    _git(dest, "init", "-q")
    _git(dest, "remote", "add", "origin", url)
    _git(dest, "fetch", "-q", "--depth", "1", "origin", base_commit)
    _git(dest, "checkout", "-q", "FETCH_HEAD")
    return inspect_checkout(dest)


def build_manifest(jsonl: Path, checkouts_dir: Path) -> list[ManifestRow]:
    rows: list[ManifestRow] = []
    for line in jsonl.read_text().splitlines():
        if not line.strip():
            continue
        inst = json.loads(line)
        facts = provision_instance(
            inst["repo"], inst["base_commit"],
            checkouts_dir / inst["instance_id"],
        )
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
