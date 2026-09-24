"""Recompute the TtG wire curve OFFLINE, from primitives (gate G2).

Without this module a third party can only re-aggregate the producer's own
pre-baked 3-point grid.  This module instead reconstructs every selected row
from the frozen-gold identities and the retained ranked retrieval primitives,
then requires full parity with the stored curve before aggregation.

From `(gold_symbols, retrieved_symbols, retrieved_wire_positions)` alone,
for ARBITRARY budget `B` and threshold `c%`:

    Gold@B_wire     = |{g : g claimed at rank r, wire_pos[r] <= B}| / |gold|
    TokensToGold@c% = min{ wire_pos[r] : coverage-through-r >= c% }, else None

`retrieved_wire_positions[r]` is the producer's cumulative wire through
ranks `0..=r` under its section-aware `price_wire` rule (a section's cost is
relocated, so wire is charged per SECTION, not per symbol). We never
re-implement that pricing — we consume the number the engine already emitted
and independently reconstruct match/reach semantics from the frozen identities.
The stored curve is a parity target, never the reconstruction oracle: any
disagreement fails the audit.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

from ttg.matcher import match_gold, match_gold_spans, parse_span, split_identity
from ttg.report_io import wire_curve

PARITY_TOL = 1e-9


class CurveInputError(ValueError):
    """The report lacks the enrichment this module requires."""


@dataclass(frozen=True)
class WireCurve:
    """One instance's offline-recomputed wire curve."""

    gold_count: int
    whole: float
    delivered_tokens: int
    by_budget: dict[int, float]
    tokens_to_coverage: dict[int, int | None]

    def as_report_curve(self) -> dict[str, object]:
        """Serialize the reconstructed curve in the retained report shape."""
        return {
            "whole": self.whole,
            "delivered_tokens": self.delivered_tokens,
            "by_budget": {
                str(budget): value for budget, value in self.by_budget.items()
            },
            "tokens_to_coverage": {
                str(threshold): value
                for threshold, value in self.tokens_to_coverage.items()
            },
        }


def recompute_wire_curve(
    gold_symbols: Sequence[str],
    retrieved_symbols: Sequence[str],
    retrieved_wire_positions: Sequence[int],
    budgets: Sequence[int],
    thresholds: Sequence[int],
    *,
    identity_kind: Literal["symbol", "span"] = "symbol",
    gold_ranges: Sequence[Sequence[int]] | None = None,
) -> WireCurve:
    """The whole wire TtG curve for one instance, from primitives."""
    if len(retrieved_wire_positions) != len(retrieved_symbols):
        raise CurveInputError(
            f"retrieved_wire_positions has {len(retrieved_wire_positions)} entries "
            f"but retrieved_symbols has {len(retrieved_symbols)} — the alignment "
            "guarantee is broken, so no rank can be priced"
        )
    if any(type(position) is not int or position < 0 for position in retrieved_wire_positions):
        raise CurveInputError("retrieved wire positions must be non-negative integers")
    if any(
        later < earlier
        for earlier, later in zip(
            retrieved_wire_positions,
            retrieved_wire_positions[1:],
            strict=False,
        )
    ):
        raise CurveInputError("retrieved wire positions must be non-decreasing")
    gold_count = len(gold_symbols)
    delivered = retrieved_wire_positions[-1] if retrieved_wire_positions else 0

    if identity_kind == "span":
        if gold_ranges is None:
            raise CurveInputError("span reconstruction requires frozen-gold ranges")
        result = match_gold_spans(gold_symbols, gold_ranges, retrieved_symbols)
    elif identity_kind == "symbol":
        if gold_ranges is not None:
            raise CurveInputError("symbol reconstruction must not receive span ranges")
        result = match_gold(gold_symbols, retrieved_symbols)
    else:
        raise CurveInputError(f"unsupported retrieval identity kind: {identity_kind}")
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
        whole=result.recall,
        delivered_tokens=delivered,
        by_budget=by_budget,
        tokens_to_coverage=tokens_to_coverage,
    )


_NO_RANGE = (-1, -2)


def _ranges_for_frozen_gold(
    row: Mapping[str, object], frozen_symbols: Sequence[str]
) -> list[Sequence[int]]:
    """Resolve retained ranges by frozen identity, preserving frozen order."""
    row_symbols = _require_list(row, "gold_symbols")
    row_ranges = _require_list(row, "gold_symbol_ranges")
    if len(row_symbols) != len(row_ranges):
        raise CurveInputError(
            f"{row.get('instance_id')}: gold symbols/ranges are not aligned"
        )
    ranges_by_symbol: dict[str, Sequence[int]] = {}
    for symbol, raw_range in zip(row_symbols, row_ranges, strict=True):
        if not isinstance(symbol, str) or symbol in ranges_by_symbol:
            raise CurveInputError(
                f"{row.get('instance_id')}: invalid or duplicate retained gold identity"
            )
        if (
            not isinstance(raw_range, list)
            or len(raw_range) != 2
            or any(type(value) is not int for value in raw_range)
        ):
            raise CurveInputError(
                f"{row.get('instance_id')}: invalid retained range for {symbol}"
            )
        ranges_by_symbol[symbol] = raw_range
    return [ranges_by_symbol.get(symbol, _NO_RANGE) for symbol in frozen_symbols]


def _strict_stored_number(value: object, context: str) -> float:
    """Return a stored numeric curve value, excluding booleans."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise CurveInputError(f"{context}: stored curve value is not numeric")
    return float(value)


def validate_stored_curve_parity(
    instance_id: str,
    offline: WireCurve,
    stored: Mapping[str, object],
    budgets: Sequence[int],
    thresholds: Sequence[int],
) -> None:
    """Require a retained curve to equal its primitive reconstruction."""
    expected_fields = {
        "whole",
        "delivered_tokens",
        "by_budget",
        "tokens_to_coverage",
    }
    if set(stored) != expected_fields:
        raise CurveInputError(
            f"{instance_id}: stored curve fields differ from the retained contract"
        )
    whole = _strict_stored_number(stored.get("whole"), f"{instance_id} whole")
    delivered = stored.get("delivered_tokens")
    if type(delivered) is not int:
        raise CurveInputError(f"{instance_id}: stored delivered_tokens is not an integer")
    if abs(offline.whole - whole) > PARITY_TOL or offline.delivered_tokens != delivered:
        raise CurveInputError(f"{instance_id}: stored whole/delivered curve drift")

    stored_budgets = stored.get("by_budget")
    if not isinstance(stored_budgets, Mapping):
        raise CurveInputError(f"{instance_id}: stored curve lacks by_budget")
    if set(stored_budgets) != {str(budget) for budget in budgets}:
        raise CurveInputError(f"{instance_id}: stored budget grid changed")
    for budget in budgets:
        value = _strict_stored_number(
            stored_budgets.get(str(budget)), f"{instance_id} Gold@{budget}"
        )
        if abs(offline.by_budget[budget] - value) > PARITY_TOL:
            raise CurveInputError(f"{instance_id}: stored Gold@{budget} curve drift")

    stored_thresholds = stored.get("tokens_to_coverage")
    if not isinstance(stored_thresholds, Mapping):
        raise CurveInputError(f"{instance_id}: stored curve lacks tokens_to_coverage")
    if set(stored_thresholds) != {str(threshold) for threshold in thresholds}:
        raise CurveInputError(f"{instance_id}: stored threshold grid changed")
    for threshold in thresholds:
        value = stored_thresholds.get(str(threshold))
        if value is not None and type(value) is not int:
            raise CurveInputError(
                f"{instance_id}: stored TtG@{threshold} is not an integer or null"
            )
        if offline.tokens_to_coverage[threshold] != value:
            raise CurveInputError(f"{instance_id}: stored TtG@{threshold} curve drift")


def reconstruct_selected_curves(
    report: Mapping[str, object],
    frozen_gold: Mapping[str, Sequence[str]],
    selected_instance_ids: Sequence[str],
    identity_kind: Literal["symbol", "span"],
    budgets: Sequence[int] = (2_000, 8_000, 32_000),
    thresholds: Sequence[int] = (50, 80, 100),
) -> dict[str, WireCurve]:
    """Reconstruct and parity-check every selected frozen-gold instance."""
    raw_results = report.get("results")
    if not isinstance(raw_results, list):
        raise CurveInputError("report has no results[]")
    selected = set(selected_instance_ids)
    rows: dict[str, Mapping[str, object]] = {}
    for row in raw_results:
        if not isinstance(row, Mapping):
            continue
        instance_id = row.get("instance_id")
        if not isinstance(instance_id, str) or instance_id not in selected:
            continue
        if instance_id in rows:
            raise CurveInputError(f"{instance_id}: duplicate selected report row")
        rows[instance_id] = row

    curves: dict[str, WireCurve] = {}
    for instance_id in selected_instance_ids:
        row = rows.get(instance_id)
        if row is None or "error" in row:
            raise CurveInputError(f"{instance_id}: selected report row is absent or failed")
        frozen_symbols = frozen_gold.get(instance_id)
        if frozen_symbols is None:
            raise CurveInputError(f"{instance_id}: absent from frozen gold")
        retrieved, positions = _retrieval_primitives(row)
        if any(not isinstance(value, str) for value in retrieved):
            raise CurveInputError(f"{instance_id}: retrieved identity is not a string")
        if any(type(value) is not int for value in positions):
            raise CurveInputError(f"{instance_id}: retrieved wire position is not an integer")
        ranges = (
            _ranges_for_frozen_gold(row, frozen_symbols)
            if identity_kind == "span"
            else None
        )
        offline = recompute_wire_curve(
            [str(symbol) for symbol in frozen_symbols],
            [str(symbol) for symbol in retrieved],
            [int(value) for value in positions],
            budgets,
            thresholds,
            identity_kind=identity_kind,
            gold_ranges=ranges,
        )
        validate_stored_curve_parity(
            instance_id,
            offline,
            wire_curve(row),
            budgets,
            thresholds,
        )
        curves[instance_id] = offline
    return curves


def _require_list(row: Mapping[str, object], key: str) -> list[object]:
    value = row.get(key)
    if not isinstance(value, list):
        raise CurveInputError(
            f"{row.get('instance_id')}: no {key} — report is NOT enriched "
            "(needs an enrichment-#5-class binary); offline curve recompute "
            "is inapplicable"
        )
    return value


def _retrieval_primitives(
    row: Mapping[str, object],
) -> tuple[list[object], list[object]]:
    """Return aligned retained vectors, including the serialized-empty case.

    The frozen producer schema gives both vectors ``serde(default,
    skip_serializing_if = "Vec::is_empty")``.  Therefore *joint absence* is the
    byte-level representation of an empty ranked list.  One-sided absence,
    explicit nulls, and non-list values remain invalid.  Full stored-curve
    parity subsequently proves that a jointly absent pair really is the
    zero-delivery/zero-recall case; a nonzero stored curve cannot pass.
    """
    symbols_present = "retrieved_symbols" in row
    positions_present = "retrieved_wire_positions" in row
    if not symbols_present and not positions_present:
        return [], []
    if symbols_present != positions_present:
        raise CurveInputError(
            f"{row.get('instance_id')}: retrieval primitives are one-sided — "
            "retrieved_symbols and retrieved_wire_positions must both be present"
        )
    return (
        _require_list(row, "retrieved_symbols"),
        _require_list(row, "retrieved_wire_positions"),
    )


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
        retrieved, positions = _retrieval_primitives(row)
        identity_kind: Literal["symbol", "span"] = (
            "span"
            if any(
                parse_span(split_identity(str(identity))[1]) is not None
                for identity in retrieved
            )
            else "symbol"
        )
        offline = recompute_wire_curve(
            [str(g) for g in gold],
            [str(r) for r in retrieved],
            [int(p) for p in positions],  # type: ignore[arg-type]
            budgets,
            thresholds,
            identity_kind=identity_kind,
            gold_ranges=(
                _ranges_for_frozen_gold(row, [str(g) for g in gold])
                if identity_kind == "span"
                else None
            ),
        )
        in_binary = row.get("token_coverage_wire")
        if not isinstance(in_binary, Mapping):
            in_binary = wire_curve(row)
        try:
            validate_stored_curve_parity(
                str(iid), offline, in_binary, budgets, thresholds
            )
        except CurveInputError as exc:
            findings.append(str(exc))
    return findings
