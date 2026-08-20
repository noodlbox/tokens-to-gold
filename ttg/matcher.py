"""Port of the engine's gold-vs-retrieved match loop.

SOURCE OF TRUTH: `crates/noodlbox-eval/src/context/evaluator.rs`, the
`gold_paths` / `matched_gold_indices` loop.

DESIGN-NOTE CORRECTION (rel2-t2g-code, 2026-08-20): the B3 note said "port
`ComparablePath`". Porting the path TYPE is necessary but not sufficient —
the engine's match is a two-arm, first-match-wins walk over ranked retrieved
items, and the harness needs its `match_ranks` for BOTH the recall basis and
the TtG curve. So the faithful unit of reuse is this matcher, not the path
type alone. `offline_scorer` and `curve_recompute` both consume it, which is
also what stops the two from drifting into two different notions of "hit".

The rule, exactly:

1. **Arm 1 — exact.** A raw `(name, file_path)` tuple equality. Note this is
   a BYTE compare, so it can match a gold whose path is not even
   repo-relative (an absolute gold path matches an identical absolute
   retrieved path) — which the spelling arm alone could never do.
2. **Arm 2 — spelling-tolerant.** Same `name` (exactly; names are never
   normalized) AND `ComparablePath.compare(...) is EQUAL`.
3. **First-match-wins.** Each gold symbol is claimed at most once, at the
   FIRST rank that matches it. Each retrieved item claims at most one gold
   (`break`).
4. **Ranks are 1-indexed** and recorded in retrieved-rank order, so
   `match_ranks` is non-decreasing.

The previously shipped harness used a set intersection
(`gold & set(retrieved)`), which is arm 1 only and has no rank semantics. It
therefore UNDER-counts by exactly the arm-2 hits and cannot price a curve.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from ttg.comparable_path import ComparablePath, PathComparison


def split_identity(key: str) -> tuple[str, str]:
    """Split an emitted `"file:name"` identity into `(file_path, name)`.

    Splits on the FIRST colon, not the last. A symbol name may legitimately
    contain `::` (the engine emits hook-return identities such as
    `useAuth::login`); a repo-relative file path may not contain a colon at
    all. Splitting on the last colon would silently reattribute
    `app.ts:useAuth::login` to file `app.ts:useAuth`.
    """
    file_path, _, name = key.partition(":")
    return file_path, name


@dataclass(frozen=True)
class MatchResult:
    """The outcome of walking retrieved items against a gold set."""

    gold_count: int
    match_ranks: list[int] = field(default_factory=list)
    """1-indexed retrieved ranks at which a gold symbol was first claimed."""
    matched_gold_indices: list[int] = field(default_factory=list)
    """Indices into the gold sequence, parallel to `match_ranks`."""
    uncomparable_gold: int = 0
    """Gold paths that are not repo-relative — a path-DOMAIN mismatch, not a
    retrieval miss. Reported separately so a run of them cannot read as
    "retrieval found nothing"."""

    @property
    def covered(self) -> int:
        return len(self.match_ranks)

    @property
    def recall(self) -> float:
        return self.covered / self.gold_count if self.gold_count else 0.0

    def recall_at(self, k: int) -> float:
        """Recall using only the first `k` retrieved items."""
        if not self.gold_count:
            return 0.0
        return sum(1 for r in self.match_ranks if r <= k) / self.gold_count


def match_gold(
    gold_keys: Sequence[str], retrieved_keys: Sequence[str]
) -> MatchResult:
    """Walk ranked `retrieved_keys` against `gold_keys`, engine-faithfully."""
    gold = [split_identity(g) for g in gold_keys]
    gold_paths = [ComparablePath.gold(path) for path, _ in gold]
    uncomparable = sum(1 for p in gold_paths if not p.is_comparable)
    exact: set[tuple[str, str]] = set(gold)

    claimed: set[int] = set()
    ranks: list[int] = []
    indices: list[int] = []

    for rank0, key in enumerate(retrieved_keys):
        r_path_raw, r_name = split_identity(key)
        # Arm 1 — exact raw tuple equality.
        if (r_path_raw, r_name) in exact:
            for idx, (g_path_raw, g_name) in enumerate(gold):
                if idx not in claimed and g_name == r_name and g_path_raw == r_path_raw:
                    claimed.add(idx)
                    ranks.append(rank0 + 1)
                    indices.append(idx)
                    break
            continue
        # Arm 2 — same name, path differing only in spelling.
        r_path = ComparablePath.retrieved(r_path_raw)
        for idx, (_, g_name) in enumerate(gold):
            if (
                idx not in claimed
                and g_name == r_name
                and gold_paths[idx].compare(r_path) is PathComparison.EQUAL
            ):
                claimed.add(idx)
                ranks.append(rank0 + 1)
                indices.append(idx)
                break

    return MatchResult(
        gold_count=len(gold),
        match_ranks=ranks,
        matched_gold_indices=indices,
        uncomparable_gold=uncomparable,
    )
