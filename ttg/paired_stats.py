"""Paired statistics for the M23-P4 promote gate — stdlib only.

The three primitives the pre-registration names (`M23_P4_EXECUTION_PLAN_2026-08-13.md`
§ Pre-registration): the exact paired sign test (McNemar's exact form on the
discordant pairs), the percentile bootstrap CI on the mean paired delta, and the
engine's *upper* median.

The sign test and the bootstrap mirror, formula for formula and index for index,
`noodlbox-evals/swebench-evals/harbor/ab_metrics.py` (`_binom_two_sided_p`,
`_bootstrap_mean_ci`) so a number here and a number there mean the same thing.
They are re-stated rather than imported: harbor's are private helpers typed to
SWE-bench *solve-rate trial records* (binary per-instance outcomes), while the
gate's per-instance metric (`Gold@budget_wire`) is continuous in [0, 1]. On
binary input the two agree exactly — McNemar's exact test IS the sign test on
the discordant pairs.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass

# Resamples for the paired bootstrap. 10k gives a stable 95% percentile
# interval at n≈40 (harbor uses the same count for the same reason).
BOOTSTRAP_ITERATIONS = 10_000
# Fixed so a re-run of the same reports reproduces the same CI to the digit.
BOOTSTRAP_SEED = 20260818
# Ties are exact float equality in practice (both arms emit the same rational
# from the same denominator); this only guards accumulated float dust.
TIE_EPS = 1e-12


@dataclass(frozen=True)
class SignTest:
    """Exact two-sided paired sign test over the discordant pairs."""

    up: int  # arm > baseline
    down: int  # arm < baseline
    ties: int
    p_value: float
    method: str


@dataclass(frozen=True)
class BootstrapCI:
    """Percentile bootstrap interval on the mean paired delta."""

    mean_delta: float
    lower: float
    upper: float
    level: float
    iterations: int
    seed: int

    def excludes_zero_positive(self) -> bool:
        """The pre-registered reading: CI excludes 0 *on the positive side*."""
        return self.lower > 0.0


def exact_two_sided_binomial_p(up: int, down: int) -> float:
    """Exact two-sided binomial p for n=up+down discordants at p=0.5."""
    n = up + down
    if n == 0:
        return 1.0
    k = min(up, down)
    cdf = sum(math.comb(n, i) for i in range(k + 1)) / (2.0**n)
    return min(1.0, 2.0 * cdf)


def sign_test(deltas: list[float], eps: float = TIE_EPS) -> SignTest:
    """Paired sign test on per-instance deltas (arm − baseline)."""
    up = sum(1 for d in deltas if d > eps)
    down = sum(1 for d in deltas if d < -eps)
    return SignTest(
        up=up,
        down=down,
        ties=len(deltas) - up - down,
        p_value=exact_two_sided_binomial_p(up, down),
        method="exact-binomial (McNemar exact / sign test)",
    )


def bootstrap_mean_ci(
    deltas: list[float],
    level: float = 0.95,
    iterations: int = BOOTSTRAP_ITERATIONS,
    seed: int = BOOTSTRAP_SEED,
) -> BootstrapCI | None:
    """Percentile bootstrap CI on the mean of the paired deltas.

    Resamples *instances* (the pairing unit) with replacement, so the interval
    carries the pairing — an unpaired two-sample bootstrap would overstate the
    spread on a box-fixed A/B where both arms read the same boxes.
    """
    n = len(deltas)
    if n == 0:
        return None
    rng = random.Random(seed)
    means: list[float] = []
    for _ in range(iterations):
        total = 0.0
        for _ in range(n):
            total += deltas[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    lo_idx = int((1.0 - level) / 2.0 * iterations)
    hi_idx = min(iterations - 1, int((1.0 + level) / 2.0 * iterations))
    return BootstrapCI(
        mean_delta=sum(deltas) / n,
        lower=means[lo_idx],
        upper=means[hi_idx],
        level=level,
        iterations=iterations,
        seed=seed,
    )


def mean(values: list[float]) -> float:
    if not values:
        raise ValueError("mean of an empty sample — the caller must gate on n>0")
    return sum(values) / len(values)


def engine_median(values: list[int]) -> int | None:
    """The engine's median: `reached.sort_unstable(); reached.get(len/2)`.

    Deliberately NOT the average of the two middles for an even count — the
    verdict must read the same number the Rust rollup prints
    (`evaluator.rs::aggregate_token_curves`, branch `feat/m23-p4-m22-sweep`
    @ 488b1387). Empty (nothing reached) is `None`, matching `Option<usize>`.
    """
    if not values:
        return None
    ordered = sorted(values)
    return ordered[len(ordered) // 2]
