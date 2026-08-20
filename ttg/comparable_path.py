"""Port of the engine's `ComparablePath` path-join rule.

SOURCE OF TRUTH: `crates/noodlbox-eval/src/context/graph_gold.rs`
(`ComparablePath`, `compare_paths`, `paths_equal`) over
`crates/noodlbox-entities/src/repo_path.rs` (`RepoRelativePath::parse`).

This module exists because the harness previously normalized with
`strip()` + a leading-`./` trim, which is NOT the rule. That light normalize
happens to agree with the engine on the ts40 corpus (measured contribution to
the headline gap: 0.0000) and is a latent wrong-number generator everywhere
else. Reproduce the rule, do not approximate it.

Three properties the light normalize does not have:

1. **Three-valued.** `NotComparable` is deliberately distinct from
   `Different`. Collapsing them reports a path-DOMAIN mismatch (an absolute
   `file_path` column: a pre-V9 box, a `NonGitDirectory`, a dependency store)
   as "retrieval found nothing" — i.e. a catastrophic-looking regression that
   is really a harness that cannot compare. Callers COUNT the third verdict.
2. **Asymmetric.** Gold gets a one-leading-`/` spelling allowance because
   gold is authored by hand and `/src/auth.py` means repo-root-relative.
   Retrieved gets NO such allowance: persisted paths are already
   repo-relative, so an absolute value there is a domain mismatch, and
   stripping its root would yield the plausible-looking
   `Users/me/repo/src/auth.py` and silently erase the signal.
3. **Rejecting, not trimming.** `..` is rejected outright; `.` and `//` are
   collapsed; a trailing `/` is dropped; empty is rejected. The old
   fixed-order double-trim let `.//x` keep a leading slash.
"""

from __future__ import annotations

import posixpath
from dataclasses import dataclass
from enum import Enum


class PathComparison(Enum):
    """The outcome of joining two paths."""

    EQUAL = "equal"
    """Both sides normalized, and they name the same file."""
    DIFFERENT = "different"
    """Both sides normalized, and they name different files."""
    NOT_COMPARABLE = "not_comparable"
    """At least one side is not a repo-relative path, so no verdict exists."""


def parse_repo_relative(raw: str) -> str | None:
    """Port of `RepoRelativePath::parse`. `None` == the `Err` arm.

    Rejects: empty, absolute (leading `/`), and any `..` component.
    Collapses: `.` components, repeated `/`, trailing `/`.
    """
    if not raw:
        return None
    if raw.startswith("/"):
        return None
    segments: list[str] = []
    for segment in raw.split("/"):
        if segment == "" or segment == posixpath.curdir:
            # `components()` drops empty (`//`, trailing `/`) and `.` alike.
            continue
        if segment == posixpath.pardir:
            return None
        segments.append(segment)
    if not segments:
        return None
    return "/".join(segments)


@dataclass(frozen=True)
class ComparablePath:
    """One side of the path join, normalized ONCE."""

    normalized: str | None

    @classmethod
    def gold(cls, raw: str) -> ComparablePath:
        """Normalize an AUTHORED gold path (one leading `/` allowed)."""
        return cls(parse_repo_relative(raw[1:] if raw.startswith("/") else raw))

    @classmethod
    def retrieved(cls, raw: str) -> ComparablePath:
        """Normalize a RETRIEVED path from the graph (no `/` allowance)."""
        return cls(parse_repo_relative(raw))

    @property
    def is_comparable(self) -> bool:
        """Whether this value names a file at all in the persisted domain."""
        return self.normalized is not None

    def compare(self, other: ComparablePath) -> PathComparison:
        """Join against another pre-normalized path."""
        if self.normalized is None or other.normalized is None:
            return PathComparison.NOT_COMPARABLE
        if self.normalized == other.normalized:
            return PathComparison.EQUAL
        return PathComparison.DIFFERENT


def compare_paths(gold: str, retrieved: str) -> PathComparison:
    """Join two raw paths, distinguishing "different file" from "not a path"."""
    return ComparablePath.gold(gold).compare(ComparablePath.retrieved(retrieved))


def paths_equal(gold: str, retrieved: str) -> bool:
    """Exact equality over the shared repo-relative domain.

    A value that is not a valid repo-relative path matches nothing — including
    another invalid value, since two things that cannot name a file cannot
    name the SAME file.
    """
    return compare_paths(gold, retrieved) is PathComparison.EQUAL
