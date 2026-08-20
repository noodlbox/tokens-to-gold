"""Aggregate per-instance coverage into headline numbers — over BOTH bases.

THE G1-SEMANTICS CLAUSE. This module is the reason B3 exists.

There are three candidate denominators per corpus and all three sound
defensible:

    corpus instances  >  non-error results  >  gold-bearing results
    ts40:        40   >        38           >        37
    py_nosphinx: 40   >        40           >        39

**BINDING: the denominator is the gold-bearing count.** A zero-gold instance
is one whose reference patch touched no resolvable symbol; scoring it as 0.0
measures the CORPUS, not the engine.

The trap is not in the offline scorer — that one is right by construction,
because the frozen gold file contains only gold-bearing instances. The trap
is that **the engine's own `token_coverage_wire` rollup averages over every
non-error row**, so anyone who reads the headline off the report header lands
on the wrong number. Measured, on the official merged-main run:

    ts40  Gold@8k : engine 0.768 x 38 = 29.18 | binding 0.7891 x 37 = 29.20
    ts40  reach@80: engine 0.763 x 38 = 28.99 | binding 0.7838 x 37 = 29.00
    py    Gold@8k : engine 0.813 x 40 = 32.52 | binding 0.8333 x 39 = 32.50
    py    reach@80: engine 0.875 x 40 = 35.00 | binding 0.8974 x 39 = 35.00

The NUMERATORS are identical on both corpora and both quantities. The entire
difference is the denominator. That is why this module always emits both and
labels them: a reader who sees only one number cannot tell which they have,
and a reader who sees a difference must be able to recognise it as the
expected consequence of a named choice rather than a discrepancy.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final

from ttg.report_io import gold_bearing_rows, result_rows

DEFAULT_BUDGETS: Final[tuple[int, ...]] = (2_000, 8_000, 32_000)
DEFAULT_COVERAGES: Final[tuple[int, ...]] = (50, 80, 100)


class Basis(Enum):
    """Which instances form the denominator."""

    FROZEN_GOLD = "frozen-gold"
    """BINDING and AUTHORITATIVE: the instance set of the pinned FROZEN gold.

    This is the only basis that survives a REUSE run. A warm-store arm
    re-derives its own gold: on the py ablation the report embedded gold for
    just 26 of 39 instances, so a report-derived basis silently shrinks the
    denominator and inflates every wire metric (measured: +19.23pp on
    Gold@8k). That is MUST-NOT #1 in disguise."""
    GOLD_BEARING = "report-gold-bearing"
    """NON-AUTHORITATIVE fallback used when no frozen gold is supplied.
    Coincides with the frozen basis on a fresh --reindex run; diverges on
    reuse."""
    ALL_ROWS = "all-non-error"
    """The engine's own rollup basis. Reported for comparison, NOT binding."""

    @property
    def is_binding(self) -> bool:
        """Only the FROZEN gold basis is authoritative. The report-derived
        fallback is explicitly NOT binding — it drifts on a reuse run."""
        return self is Basis.FROZEN_GOLD


@dataclass(frozen=True)
class BasisRollup:
    """Headline numbers under one basis."""

    basis: Basis
    n: int
    gold_at_budget: dict[int, float]
    """Mean per-instance wire coverage at each budget (`Gold@B_wire`)."""
    reach_at_coverage: dict[int, float]
    """Fraction of instances that reach each coverage level within delivered wire."""
    median_ttg_at_coverage: dict[int, int | None]
    """Median wire tokens to reach each coverage level, over reachers only."""


def _median(values: Sequence[int]) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) // 2


def _rollup_rows(
    rows: Sequence[Mapping[str, object]],
    basis: Basis,
    budgets: Sequence[int],
    coverages: Sequence[int],
    denominator: int | None = None,
) -> BasisRollup:
    """`denominator` overrides `len(rows)` so an instance present in the
    frozen gold but absent from the report counts as a ZERO rather than
    vanishing from the denominator."""
    n = denominator if denominator is not None else len(rows)
    covers: list[Mapping[str, object]] = []
    for row in rows:
        wire = row.get("token_coverage_wire")
        covers.append(wire if isinstance(wire, Mapping) else {})

    gold_at: dict[int, float] = {}
    for budget in budgets:
        by_budget = [c.get("by_budget") or {} for c in covers]
        total = sum(
            float(b.get(str(budget), 0.0) or 0.0)
            for b in by_budget
            if isinstance(b, Mapping)
        )
        gold_at[budget] = total / n if n else 0.0

    reach_at: dict[int, float] = {}
    median_at: dict[int, int | None] = {}
    for coverage in coverages:
        reached: list[int] = []
        for cover in covers:
            ttc = cover.get("tokens_to_coverage")
            if not isinstance(ttc, Mapping):
                continue
            value = ttc.get(str(coverage))
            if isinstance(value, (int, float)):
                reached.append(int(value))
        reach_at[coverage] = len(reached) / n if n else 0.0
        median_at[coverage] = _median(reached)

    return BasisRollup(
        basis=basis,
        n=n,
        gold_at_budget=gold_at,
        reach_at_coverage=reach_at,
        median_ttg_at_coverage=median_at,
    )


@dataclass(frozen=True)
class Rollup:
    """Both bases, side by side. `binding` is the one to cite."""

    binding: BasisRollup
    engine_basis: BasisRollup

    def render(self, corpus: str) -> str:
        """A block that makes the basis impossible to misread."""
        lines = [
            f"corpus: {corpus}",
            f"  BINDING basis     : {self.binding.basis.value} (n={self.binding.n})",
            f"  comparison basis  : {self.engine_basis.basis.value} "
            f"(n={self.engine_basis.n})  <- the engine's own rollup; NOT binding",
        ]
        for budget in sorted(self.binding.gold_at_budget):
            lines.append(
                f"  Gold@{budget // 1000}k_wire     : "
                f"{self.binding.gold_at_budget[budget]:.4f}  BINDING   "
                f"(engine basis: {self.engine_basis.gold_at_budget[budget]:.4f})"
            )
        for coverage in sorted(self.binding.reach_at_coverage):
            lines.append(
                f"  reach@{coverage:<3d}         : "
                f"{self.binding.reach_at_coverage[coverage]:.4f}  BINDING   "
                f"(engine basis: {self.engine_basis.reach_at_coverage[coverage]:.4f})"
            )
        lines.append(
            "  NOTE: identical numerators, different denominators. A difference "
            "between the two columns is EXPECTED, not a discrepancy."
        )
        return "\n".join(lines)


def rollup(
    report: Mapping[str, object],
    budgets: Sequence[int] = DEFAULT_BUDGETS,
    coverages: Sequence[int] = DEFAULT_COVERAGES,
    frozen_instance_ids: Sequence[str] | None = None,
) -> Rollup:
    """Roll a report up under both bases.

    Pass `frozen_instance_ids` (the pinned frozen gold's instance set) for the
    AUTHORITATIVE binding basis. Without it the binding column falls back to
    the report's own embedded gold, which is correct ONLY for a fresh
    `--reindex` run -- see `Basis.FROZEN_GOLD`.
    """
    if frozen_instance_ids is not None:
        wanted = list(dict.fromkeys(frozen_instance_ids))
        by_id = {r.get("instance_id"): r for r in result_rows(report)}
        binding = _rollup_rows(
            [by_id[iid] for iid in wanted if iid in by_id],
            Basis.FROZEN_GOLD, budgets, coverages, denominator=len(wanted),
        )
    else:
        binding = _rollup_rows(
            list(gold_bearing_rows(report)), Basis.GOLD_BEARING, budgets, coverages
        )
    return Rollup(
        binding=binding,
        engine_basis=_rollup_rows(
            result_rows(report), Basis.ALL_ROWS, budgets, coverages
        ),
    )
