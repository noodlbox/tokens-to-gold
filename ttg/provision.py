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
    new_file_fraction: float


@dataclass(frozen=True)
class ProvisionError:
    """An instance whose checkout could not be provisioned (unreachable commit,
    network failure). Recorded by instance id and carried forward as an
    `errored` exclusion — never silently dropped from the corpus."""

    instance_id: str
    repo: str
    base_commit: str
    reason: str


@dataclass(frozen=True)
class ProvisionResult:
    rows: list[ManifestRow]
    errors: list[ProvisionError]


_DIFF_HEADER = re.compile(r"^diff --git a/\S+ b/(\S+)", re.M)
_NEW_FILE = re.compile(r"^new file mode ", re.M)


def new_file_fraction(patch: str) -> float:
    """Files the reference patch CREATES divided by files it touches.

    The mechanical explanation for a zero-gold instance: gold resolves the
    patch's changed lines to symbol definitions in the PRE-change checkout, so a
    file the patch creates has no pre-existing definitions to score. A high
    fraction predicts zero gold (measured on go34: 0.79 mean among zero-gold
    instances vs 0.32 among those with gold). Computed from the patch text, so
    it discloses nothing the public manifest does not already imply.
    """
    touched = len(_DIFF_HEADER.findall(patch))
    if touched == 0:
        return 0.0
    return round(len(_NEW_FILE.findall(patch)) / touched, 4)


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
    # Idempotent: a resumed run on a kept lease already has the checkout, and
    # re-cloning 157 repos to regenerate a manifest column would be absurd. If
    # the checkout is already at the right commit, inspect it and return.
    if (dest / ".git").is_dir():
        try:
            head_tree = _git(dest, "rev-parse", "HEAD^{tree}")
        except subprocess.CalledProcessError:
            head_tree = ""
        if head_tree:
            return inspect_checkout(dest)

    dest.mkdir(parents=True, exist_ok=True)
    _git(dest, "init", "-q")
    # `remote add` fails if the remote exists; a resumed run must not die on it.
    try:
        _git(dest, "remote", "add", "origin", url)
    except subprocess.CalledProcessError:
        _git(dest, "remote", "set-url", "origin", url)
    # commit is validated hex and url is validated scheme/slug, so neither can
    # be read as a git flag (git fetch takes no `--` refspec separator).
    _git(dest, "fetch", "-q", "--depth", "1", "origin", commit)
    _git(dest, "checkout", "-q", "FETCH_HEAD")
    return inspect_checkout(dest)


def build_manifest(jsonl: Path, checkouts_dir: Path) -> ProvisionResult:
    """Provision every instance and return the manifest plus the errored set.

    A provisioning FAILURE (unreachable commit, network) becomes a recorded
    `ProvisionError`, so the instance is carried as an errored exclusion rather
    than vanishing from the denominator. An UNSAFE corpus field is different:
    it still raises, because that is a malformed corpus, not a flaky checkout."""
    rows: list[ManifestRow] = []
    errors: list[ProvisionError] = []
    for line in jsonl.read_text().splitlines():
        if not line.strip():
            continue
        inst = json.loads(line)
        dest = _validated_dest(checkouts_dir, inst["instance_id"])
        try:
            facts = provision_instance(inst["repo"], inst["base_commit"], dest)
        except subprocess.CalledProcessError as exc:
            errors.append(ProvisionError(
                instance_id=inst["instance_id"], repo=inst["repo"],
                base_commit=inst["base_commit"],
                reason=(exc.stderr or "").strip()[:300] or f"git failed rc={exc.returncode}",
            ))
            continue
        rows.append(ManifestRow(
            instance_id=inst["instance_id"], repo=inst["repo"],
            base_commit=inst["base_commit"],
            tree_sha=facts.tree_sha, rs_file_count=facts.rs_file_count,
            new_file_fraction=new_file_fraction(inst.get("patch", "")),
        ))
    return ProvisionResult(rows=rows, errors=errors)


def write_manifest(rows: list[ManifestRow], out: Path) -> None:
    """The PUBLIC checkout-set proof: ids, repo, base_commit, tree_sha and
    rs_file_count only — never patches or problem statements (U3)."""
    out.write_text("".join(json.dumps(asdict(r)) + "\n" for r in rows))


def write_errors(errors: list[ProvisionError], out: Path) -> None:
    out.write_text("".join(json.dumps(asdict(e)) + "\n" for e in errors))


def ts_py_discovery_equivalent(rows: list[ManifestRow]) -> bool:
    """R-B2: rust ON/OFF is discovery-equivalent for these corpora iff no
    checkout carries a `.rs` file."""
    return all(r.rs_file_count == 0 for r in rows)
