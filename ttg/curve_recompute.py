"""Recompute the TtG wire curve OFFLINE, from primitives (gate G2).

Without this module a third party can only re-aggregate the engine's own
pre-baked 3-point grid — they must TRUST the per-instance curve. Removing
that trust is exactly what G2 is for.

From `(gold_symbols, retrieved_symbols, retrieved_wire_positions)` alone,
for ARBITRARY budget `B` and threshold `c%`:

    Gold@B_wire     = |{g : g claimed at rank r, wire_pos[r] <= B}| / |gold|
    TokensToGold@c% = min{ wire_pos[r] : coverage-through-r >= c% }, else None

`retrieved_wire_positions[r]` is the engine's OWN cumulative wire through
ranks `0..=r` under its section-aware `price_wire` rule (a section's cost is
relocated, so wire is charged per SECTION, not per symbol). We never
re-implement that pricing — we consume the number the engine already emitted
and prove fidelity by parity against its in-binary `token_coverage_wire`.

SEMANTIC LOCK: the binary is the oracle. If a systematic offset ever appears
(an off-by-one in "paid at rank r vs r+1", a section-boundary attribution),
it is corrected HERE once to reproduce the binary, then locked.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from ttg.matcher import match_gold

PARITY_TOL = 1e-9


class CurveInputError(ValueError):
    """The report lacks the enrichment this module requires."""


@dataclass(frozen=True)
class WireCurve:
    """One instance's offline-recomputed wire curve."""

    gold_count: int
    delivered_tokens: int
    by_budget: dict[int, float]
    tokens_to_coverage: dict[int, int | None]


def recompute_wire_curve(
    gold_symbols: Sequence[str],
    retrieved_symbols: Sequence[str],
    retrieved_wire_positions: Sequence[int],
    budgets: Sequence[int],
    thresholds: Sequence[int],
) -> WireCurve:
    """The whole wire TtG curve for one instance, from primitives."""
    if len(retrieved_wire_positions) != len(retrieved_symbols):
        raise CurveInputError(
            f"retrieved_wire_positions has {len(retrieved_wire_positions)} entries "
            f"but retrieved_symbols has {len(retrieved_symbols)} — the alignment "
            "guarantee is broken, so no rank can be priced"
        )
    gold_count = len(gold_symbols)
    delivered = retrieved_wire_positions[-1] if retrieved_wire_positions else 0

    result = match_gold(gold_symbols, retrieved_symbols)
    # Wire position at which each claimed gold was paid for, in rank order.
    paid_at = [retrieved_wire_positions[rank - 1] for rank in result.match_ranks]

    by_budget = {
        budget: (sum(1 for w in paid_at if w <= budget) / gold_count if gold_count else 0.0)
        for budget in budgets
    }

    tokens_to_coverage: dict[int, int | None] = {}
    for threshold in thresholds:
        if not gold_count:
            tokens_to_coverage[threshold] = None
            continue
        needed = math.ceil(threshold * gold_count / 100)
        # `paid_at` is non-decreasing (match_ranks is), so the k-th entry is
        # the first wire position at which coverage reaches k.
        tokens_to_coverage[threshold] = (
            paid_at[needed - 1] if 0 < needed <= len(paid_at) else None
        )

    return WireCurve(
        gold_count=gold_count,
        delivered_tokens=delivered,
        by_budget=by_budget,
        tokens_to_coverage=tokens_to_coverage,
    )


def _require_list(row: Mapping[str, object], key: str) -> list[object]:
    value = row.get(key)
    if not isinstance(value, list):
        raise CurveInputError(
            f"{row.get('instance_id')}: no {key} — report is NOT enriched "
            "(needs an enrichment-#5-class binary); offline curve recompute "
            "is inapplicable"
        )
    return value


def curve_parity_findings(
    report: Mapping[str, object],
    budgets: Sequence[int] = (2_000, 8_000, 32_000),
    thresholds: Sequence[int] = (50, 80, 100),
) -> list[str]:
    """Every instance where the offline curve disagrees with the in-binary one.

    Empty => the offline recompute reproduces the binary => **G2 PASS**.
    """
    findings: list[str] = []
    results = report.get("results")
    if not isinstance(results, list):
        return ["report has no results[]"]
    for row in results:
        if not isinstance(row, Mapping) or "error" in row:
            continue
        gold = row.get("gold_symbols")
        if not isinstance(gold, list) or not gold:
            continue
        iid = row.get("instance_id")
        retrieved = _require_list(row, "retrieved_symbols")
        positions = _require_list(row, "retrieved_wire_positions")
        offline = recompute_wire_curve(
            [str(g) for g in gold],
            [str(r) for r in retrieved],
            [int(p) for p in positions],  # type: ignore[arg-type]
            budgets,
            thresholds,
        )
        in_binary = row.get("token_coverage_wire")
        if not isinstance(in_binary, Mapping):
            findings.append(f"{iid}: no token_coverage_wire to compare against")
            continue

        delivered = in_binary.get("delivered_tokens")
        if isinstance(delivered, (int, float)) and offline.delivered_tokens != int(delivered):
            findings.append(
                f"{iid}: delivered offline={offline.delivered_tokens} "
                f"in-binary={int(delivered)}"
            )
        engine_budget = in_binary.get("by_budget")
        if isinstance(engine_budget, Mapping):
            for budget in budgets:
                engine = engine_budget.get(str(budget))
                if isinstance(engine, (int, float)) and abs(
                    offline.by_budget[budget] - float(engine)
                ) > PARITY_TOL:
                    findings.append(
                        f"{iid}: Gold@{budget} offline={offline.by_budget[budget]:.6f} "
                        f"in-binary={float(engine):.6f}"
                    )
        engine_ttc = in_binary.get("tokens_to_coverage")
        if isinstance(engine_ttc, Mapping):
            for threshold in thresholds:
                engine = engine_ttc.get(str(threshold))
                mine = offline.tokens_to_coverage[threshold]
                engine_value = int(engine) if isinstance(engine, (int, float)) else None
                if mine != engine_value:
                    findings.append(
                        f"{iid}: TtG@{threshold}% offline={mine} in-binary={engine_value}"
                    )
    return findings
