"""R12 regression verdicts: per-metric HELD / IMPROVED / REGRESSED.

The re-certification's comparable quantity is the new binary's arms scored
against the EXISTING frozen gold. This module turns two such reports into the
verdict table the regression report publishes.

WHY THE FLOOR ALONE IS NOT THE VERDICT

The pre-registered `NOISE_FLOOR_PP` (2.75 pp) is a *practical* threshold: a
move smaller than it is not worth calling. It says nothing about whether the
move is distinguishable from zero at all. So every verdict here is decided by
the paired bootstrap 95% CI *relative to the floor band*, and carries the exact
paired sign test alongside:

    CI entirely inside [-floor, +floor]  -> HELD          (bounded, not merely small)
    CI lower bound     >  +floor         -> IMPROVED
    CI upper bound     <  -floor         -> REGRESSED
    otherwise                            -> INDETERMINATE (straddles a boundary)

A point estimate never decides on its own: a mean delta of +4 pp whose CI runs
from -1 pp to +9 pp is INDETERMINATE, not IMPROVED.

Pairing is by `instance_id` over instances present in BOTH reports, because the
bootstrap resamples instances — the pairing unit — not arms.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from ttg.paired_stats import BootstrapCI, SignTest, bootstrap_mean_ci, sign_test
from ttg.report_io import result_rows

NOISE_FLOOR_PP = 2.75
"""Pre-registered regression floor, in percentage points."""


class Verdict(str, Enum):
    HELD = "HELD"
    IMPROVED = "IMPROVED"
    REGRESSED = "REGRESSED"
    INDETERMINATE = "INDETERMINATE"


@dataclass(frozen=True)
class MetricVerdict:
    metric: str
    n: int
    mean_delta_pp: float
    ci: BootstrapCI | None
    sign: SignTest
    verdict: Verdict
    floor_pp: float


RowValue = Callable[[Mapping[str, object]], float | None]


def _wire(row: Mapping[str, object]) -> Mapping[str, object]:
    wire = row.get("token_coverage_wire")
    return wire if isinstance(wire, Mapping) else {}


def gold_at_budget(budget: int) -> tuple[str, RowValue]:
    """Per-instance `Gold@B_wire` as a fraction."""

    def value(row: Mapping[str, object]) -> float | None:
        by_budget = _wire(row).get("by_budget")
        if not isinstance(by_budget, Mapping):
            return None
        raw = by_budget.get(str(budget))
        return float(raw) if isinstance(raw, (int, float)) else None

    return (f"Gold@{budget}_wire", value)


def reach_at_coverage(coverage: int) -> tuple[str, RowValue]:
    """Per-instance reach at a coverage level: 1.0 reached, 0.0 not."""

    def value(row: Mapping[str, object]) -> float | None:
        ttc = _wire(row).get("tokens_to_coverage")
        if not isinstance(ttc, Mapping):
            return 0.0
        return 1.0 if isinstance(ttc.get(str(coverage)), (int, float)) else 0.0

    return (f"reach@{coverage}", value)


def paired_deltas_pp(
    baseline: Mapping[str, object],
    current: Mapping[str, object],
    value: RowValue,
    instance_ids: Sequence[str] | None = None,
) -> list[float]:
    """Per-instance (current - baseline) in percentage points.

    Restricted to instances present in both reports — and, when given, to the
    frozen-gold instance set, which is the binding denominator."""
    base_rows = {r.get("instance_id"): r for r in result_rows(baseline)}
    cur_rows = {r.get("instance_id"): r for r in result_rows(current)}
    keys = instance_ids if instance_ids is not None else sorted(
        k for k in base_rows.keys() & cur_rows.keys() if isinstance(k, str)
    )
    deltas: list[float] = []
    for key in keys:
        base, cur = base_rows.get(key), cur_rows.get(key)
        if base is None or cur is None:
            continue
        b, c = value(base), value(cur)
        if b is None or c is None:
            continue
        deltas.append((c - b) * 100.0)
    return deltas


def verdict_for(
    metric: str, deltas_pp: Sequence[float], floor_pp: float = NOISE_FLOOR_PP
) -> MetricVerdict:
    deltas = list(deltas_pp)
    ci = bootstrap_mean_ci(deltas)
    sign = sign_test(deltas)
    mean_delta = ci.mean_delta if ci is not None else 0.0

    if ci is None:
        verdict = Verdict.INDETERMINATE
    elif -floor_pp <= ci.lower and ci.upper <= floor_pp:
        verdict = Verdict.HELD
    elif ci.lower > floor_pp:
        verdict = Verdict.IMPROVED
    elif ci.upper < -floor_pp:
        verdict = Verdict.REGRESSED
    else:
        verdict = Verdict.INDETERMINATE

    return MetricVerdict(
        metric=metric, n=len(deltas), mean_delta_pp=mean_delta, ci=ci,
        sign=sign, verdict=verdict, floor_pp=floor_pp,
    )


def compare_reports(
    baseline: Mapping[str, object],
    current: Mapping[str, object],
    metrics: Sequence[tuple[str, RowValue]],
    instance_ids: Sequence[str] | None = None,
    floor_pp: float = NOISE_FLOOR_PP,
) -> list[MetricVerdict]:
    return [
        verdict_for(
            name, paired_deltas_pp(baseline, current, value, instance_ids), floor_pp
        )
        for name, value in metrics
    ]


DEFAULT_METRICS: tuple[tuple[str, RowValue], ...] = (
    gold_at_budget(8000),
    gold_at_budget(32000),
    reach_at_coverage(80),
)


def render_table(verdicts: Sequence[MetricVerdict]) -> str:
    """The published verdict table: every row carries its CI and sign test, so
    the floor is never read as an uncertainty statement."""
    head = (
        "| Metric | n | Δ pp | 95% CI (pp) | sign test (up/down/ties, p) | Verdict |\n"
        "|---|---|---|---|---|---|\n"
    )
    lines = []
    for v in verdicts:
        ci = f"[{v.ci.lower:+.2f}, {v.ci.upper:+.2f}]" if v.ci else "n/a"
        s = f"{v.sign.up}/{v.sign.down}/{v.sign.ties}, p={v.sign.p_value:.4f}"
        lines.append(
            f"| {v.metric} | {v.n} | {v.mean_delta_pp:+.2f} | {ci} | {s} | "
            f"**{v.verdict.value}** |"
        )
    return head + "\n".join(lines) + (
        f"\n\nFloor: ±{verdicts[0].floor_pp:.2f} pp (pre-registered). A verdict "
        "is decided by the CI relative to the floor band, never by the point "
        "estimate alone." if verdicts else ""
    )
