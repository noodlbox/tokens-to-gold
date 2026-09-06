"""The B3 acceptance gate: land EXACTLY on the measurer's V1 reference numbers.

`acceptance/MEASURER_V1_REFERENCE_NUMBERS_2026-08-20.json` is the
machine-checkable authoritative record (rel2-measurer, 2026-08-20): two arms
x two corpora x six locked metrics, at six decimals, with full provenance
(main `3a3f01fd`, binary `c5dbaf91`, shipped config
`Waterfill{char_budget: 65536}`, frozen-gold digests + counts).

TOLERANCE, and why it is this strict:

* **Replay must be EXACT to 4 decimals.** Scoring is deterministic offline
  set-match against a frozen denominator, so a harness re-scoring these
  reports has no source of noise. Any drift is a real semantic change.
* **Only a FRESH `--rederive-gold` run may move**, and then only within the
  pre-registered `NOISE_FLOOR = 2.75pp`. That floor is deliberately below one
  instance (1 instance = 2.70pp on ts40, 2.56pp on py), so a single-instance
  move is VISIBLE rather than hidden in rounding.

The five MUST-NOTs from the fixture are each a failure this campaign actually
hit. They are enforced structurally, not by convention:

| # | Must not | Where it is made unrepresentable |
|---|---|---|
| 1 | re-derive gold on the default path | `score_arm` takes the FROZEN gold; there is no report-gold path |
| 2 | full corpus on a REUSE run | `arm_matrix.assert_corpus_matches_protocol` |
| 3 | whole-file `cmp` a frozen gold | `ttg.tier1.compare_frozen_gold` (payload + 5 header fields) |
| 4 | double-credit a gold | `matcher.match_gold` claims each gold once, at its first rank |
| 5 | claim superiority at py @10 | `SUPERIORITY_CLAIMABLE`; the reporter annotates instead |
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ttg.matcher import (
    MatchResult,
    match_gold,
    match_gold_spans,
    parse_span,
    split_identity,
)
from ttg.report_io import load_report, result_rows, wire_curve
from ttg.rollup import rollup

# A gold key present in the frozen basis but absent from a report row carries no
# range; this sentinel range overlaps no span, so the key is scored as a miss on
# the authoritative frozen denominator rather than crashing the span matcher.
_NO_RANGE: Final[tuple[int, int]] = (-1, -2)

PKG = Path(__file__).resolve().parent.parent
FIXTURE_PATH: Final = PKG / "acceptance" / "MEASURER_V1_REFERENCE_NUMBERS_2026-08-20.json"

REPLAY_DECIMALS: Final = 4
REPLAY_TOL: Final = 0.5 * 10 ** (-REPLAY_DECIMALS)
REACH_COVERAGE: Final = 0.80
NOISE_FLOOR_PP: Final = 2.75
"""Pre-registered cross-run floor (criteria.py:49). Applies ONLY to a fresh
re-derivation, never to a replay."""

LOCKED_METRICS: Final[tuple[str, ...]] = (
    "head_only_at_10",
    "head_only_at_25",
    "gold_at_8k_wire",
    "gold_at_32k_wire",
    "reach_at_80_whole_list",
    "reach_at_80_within_32k",
    "whole_list_INTERNAL",
)

# MUST-NOT #5: py @10 is p=0.125 with a CI spanning 0. Superiority is
# claimable at @25 (p=0.0078) only.
SUPERIORITY_CLAIMABLE: Final[dict[tuple[str, str], bool]] = {
    ("py_nosphinx", "head_only_at_10"): False,
    ("py_nosphinx", "head_only_at_25"): True,
}


class AcceptanceError(ValueError):
    """The fixture is missing, corrupt, or misused."""


def _pinned_digest(sums_text: str, name: str) -> str:
    """The pinned sha256 for `name` from a SHA256SUMS body ('<digest>  <name>'
    lines). An ABSENT pin RAISES.

    This closes the B fail-open: `load_fixture` used `if pinned and got != pinned`,
    so a fixture whose name was missing from SHA256SUMS skipped the digest check
    ENTIRELY and returned unverified bytes. The fixture is the authoritative
    record every replay lands on; an unpinned one is not trusted, it is refused."""
    fields = sums_text.split()
    pinned = dict(zip(fields[1::2], fields[0::2])).get(name)
    if pinned is None:
        raise AcceptanceError(
            f"{name} has no pinned digest in SHA256SUMS; an unpinned fixture "
            "cannot be trusted -- pin it deliberately"
        )
    return pinned


def load_fixture(
    fixture_path: Path = FIXTURE_PATH, sums_path: Path | None = None
) -> Mapping[str, object]:
    """Load the reference fixture, verifying its pinned digest. An absent pin is
    a HARD error, never a skipped check (the B finding)."""
    if not fixture_path.exists():
        raise AcceptanceError(f"acceptance fixture missing: {fixture_path}")
    sums_path = sums_path if sums_path is not None else fixture_path.parent / "SHA256SUMS"
    if not sums_path.exists():
        raise AcceptanceError(f"acceptance SHA256SUMS missing: {sums_path}")
    raw = fixture_path.read_bytes()
    pinned = _pinned_digest(sums_path.read_text(), fixture_path.name)
    got = hashlib.sha256(raw).hexdigest()
    if got != pinned:
        raise AcceptanceError(
            f"acceptance fixture digest mismatch: {got} != {pinned}. The "
            "authoritative record changed; re-pin it deliberately"
        )
    return json.loads(raw)


def load_frozen_gold(corpus: str) -> dict[str, list[str]]:
    """The pinned frozen gold for a corpus. MUST-NOT #1: this is the ONLY
    gold source used for scoring — there is no report-embedded-gold path."""
    path = PKG / "gold" / f"frozen_gold_{corpus}.json"
    doc = json.loads(path.read_text())
    gold = doc.get("gold", doc)
    if not isinstance(gold, dict):
        raise AcceptanceError(f"{path}: no gold payload")
    return {str(k): [str(s) for s in v] for k, v in gold.items()}


@dataclass(frozen=True)
class ArmMetrics:
    """The locked metrics for one (arm, corpus) cell.

    reach@80 is TWO qualified fields, never one bare number, because the two are
    the same only for a CAPPED arm:
    * `reach_at_80_whole_list` — fraction of instances whose offline WHOLE-LIST
      recall (uncapped) clears 0.8. The Waterfill delivery cap is a curation
      lever, so shipped_treatment's whole list never exceeds 32k and this equals
      its within-cap reach; the levers-off ablation is UNCAPPED, so its whole
      list can reach gold beyond 32k and the two diverge (that divergence is the
      point of the split, not a discrepancy).
    * `reach_at_80_within_32k` — fraction of instances whose binding wire curve
      covers ≥ 0.8 of gold WITHIN the 32k budget (`by_budget["32000"] >= 0.8`).
    """

    n: int
    head_only_at_10: float
    head_only_at_25: float
    gold_at_8k_wire: float
    gold_at_32k_wire: float
    reach_at_80_whole_list: float
    reach_at_80_within_32k: float
    whole_list_INTERNAL: float

    def as_dict(self) -> dict[str, float]:
        return {name: float(getattr(self, name)) for name in LOCKED_METRICS}


def _report_is_span_form(rows: Mapping[object, Mapping[str, object]]) -> bool:
    """True iff the arm delivers spans (`file:span:a-b`) rather than named
    symbols (`file:name`). The native_floor (rg) comparator is the only span-
    form arm; shipped/levers emit `file:name` identities whose names never parse
    as `span:a-b` (a symbol name colon is always `::`)."""
    for row in rows.values():
        for key in row.get("retrieved_symbols") or []:
            if parse_span(split_identity(str(key))[1]) is not None:
                return True
    return False


def _instance_matches(
    report: Mapping[str, object], corpus: str
) -> list[MatchResult]:
    """One MatchResult per FROZEN-gold instance, in frozen order.

    Span-form arms (native_floor) are matched by RANGE OVERLAP against the
    row's `gold_symbol_ranges` (index-aligned to its `gold_symbols`), looked up
    per frozen-gold key; name-form arms use the two-arm `match_gold`. Both keep
    the frozen gold as the authoritative denominator (MUST-NOT #1)."""
    gold = load_frozen_gold(corpus)
    rows = {r.get("instance_id"): r for r in result_rows(report)}
    span_form = _report_is_span_form(rows)
    matches: list[MatchResult] = []
    for iid, symbols in gold.items():
        row = rows.get(iid, {})
        retrieved = [str(s) for s in (row.get("retrieved_symbols") or [])]
        if span_form:
            row_gold = [str(s) for s in (row.get("gold_symbols") or [])]
            row_ranges = row.get("gold_symbol_ranges") or []
            by_symbol = {
                sym: row_ranges[i]
                for i, sym in enumerate(row_gold)
                if i < len(row_ranges)
            }
            ranges = [by_symbol.get(key, _NO_RANGE) for key in symbols]
            matches.append(match_gold_spans(symbols, ranges, retrieved))
        else:
            matches.append(match_gold(symbols, retrieved))
    return matches


def within_budget_reach(
    rows_by_id: Mapping[object, Mapping[str, object]],
    gold_ids: Sequence[str],
    budget: str = "32000",
    coverage: float = REACH_COVERAGE,
) -> float:
    """Fraction of frozen-gold instances whose BINDING wire curve covers
    ≥ `coverage` of gold within `budget` (`by_budget[budget] >= coverage`).

    Uses `wire_curve`, so the floor's `token_coverage` counts as its wire curve.
    Distinct from whole-list reach: a row whose whole list recalls the gold but
    delivers < `coverage` inside the budget (e.g. `by_budget["32000"] = 0.79`)
    counts for whole_list yet NOT here — the divergence the reach split exposes."""
    n = len(gold_ids)
    if not n:
        return 0.0
    hit = sum(
        1
        for iid in gold_ids
        if float(
            (wire_curve(rows_by_id.get(iid, {})).get("by_budget") or {}).get(
                budget, 0.0
            )
            or 0.0
        )
        >= coverage
    )
    return hit / n


def score_arm(report: Mapping[str, object], corpus: str) -> ArmMetrics:
    """Score one arm's report against the PINNED frozen gold.

    Recall metrics come from offline set-match (frozen denominators,
    first-occurrence-per-gold-identity) — name-based for symbol-delivering arms,
    range-overlap for the span-delivering native_floor comparator. Wire metrics
    are rolled up from the report's own delivered-wire curve over the gold-
    bearing basis.
    """
    gold = load_frozen_gold(corpus)
    matches = _instance_matches(report, corpus)
    n = len(matches)
    if not n:
        raise AcceptanceError(f"{corpus}: frozen gold is empty")
    roll = rollup(report, frozen_instance_ids=list(gold))
    rows = {r.get("instance_id"): r for r in result_rows(report)}
    within = within_budget_reach(rows, list(gold))
    return ArmMetrics(
        n=n,
        head_only_at_10=sum(m.recall_at(10) for m in matches) / n,
        head_only_at_25=sum(m.recall_at(25) for m in matches) / n,
        gold_at_8k_wire=roll.binding.gold_at_budget[8_000],
        gold_at_32k_wire=roll.binding.gold_at_budget[32_000],
        # FROZEN-DECIDABLE whole-list reach: the fraction of frozen-gold instances
        # whose OFFLINE whole recall clears the bar. NOT the report's own
        # `tokens_to_coverage`, which a reuse arm computes against its own drifted
        # gold. This is the UNCAPPED reach; the ablation's whole list exceeds 32k.
        reach_at_80_whole_list=sum(1 for m in matches if m.recall >= REACH_COVERAGE) / n,
        # WITHIN-CAP reach: gold covered ≥ 0.8 inside the 32k wire budget. Equals
        # whole_list for the capped shipped arm; strictly ≤ it for the uncapped
        # ablation.
        reach_at_80_within_32k=within,
        whole_list_INTERNAL=sum(m.recall for m in matches) / n,
    )


@dataclass(frozen=True)
class MetricCheck:
    metric: str
    got: float
    expected: float
    ok: bool
    note: str = ""

    @property
    def delta_pp(self) -> float:
        return (self.got - self.expected) * 100.0


def check_arm(
    report: Mapping[str, object], corpus: str, arm: str, *, replay: bool = True
) -> list[MetricCheck]:
    """Compare one cell against the fixture.

    `replay=True` (the default) demands EXACT-to-4-decimals. `replay=False`
    is the fresh-`--rederive-gold` path and allows movement within
    `NOISE_FLOOR_PP`.
    """
    fixture = load_fixture()
    arms = fixture.get("arms")
    if not isinstance(arms, Mapping):
        raise AcceptanceError("fixture has no arms{}")
    corpus_arms = arms.get(corpus)
    if not isinstance(corpus_arms, Mapping):
        raise AcceptanceError(f"fixture has no arms for corpus {corpus!r}")
    expected = corpus_arms.get(arm)
    if not isinstance(expected, Mapping):
        raise AcceptanceError(
            f"fixture has no arm {arm!r} for {corpus!r}; known: "
            f"{', '.join(sorted(k for k in corpus_arms))}"
        )

    return compare_metrics(
        score_arm(report, corpus), expected, corpus=corpus, replay=replay
    )


def compare_metrics(
    got: ArmMetrics,
    expected: Mapping[str, object],
    *,
    corpus: str,
    replay: bool = True,
) -> list[MetricCheck]:
    """The ONE comparison predicate + renderer input for a cell's metrics.

    `replay=True` demands EXACT-to-4dp via `abs(mine - want) < REPLAY_TOL` (the
    same tolerance `accept` uses -- never a second round()-equality that could
    disagree at a rounding boundary). `replay=False` is the fresh-rederive path
    (movement within NOISE_FLOOR_PP). `expected` is a metric->value mapping,
    from the pinned fixture (check_arm) or a baseline report's own ArmMetrics
    (check_against_baseline)."""
    checks: list[MetricCheck] = []
    expected_n = expected.get("n")
    if isinstance(expected_n, int):
        checks.append(
            MetricCheck("n", float(got.n), float(expected_n), got.n == expected_n)
        )
    for metric in LOCKED_METRICS:
        want = expected.get(metric)
        if not isinstance(want, (int, float)):
            continue
        mine = float(getattr(got, metric))
        if replay:
            ok = abs(mine - float(want)) < REPLAY_TOL
            note = ""
        else:
            ok = abs(mine - float(want)) * 100.0 <= NOISE_FLOOR_PP
            note = f"fresh run; floor {NOISE_FLOOR_PP}pp"
        if SUPERIORITY_CLAIMABLE.get((corpus, metric)) is False:
            note = (note + "; " if note else "") + "NOT superiority-claimable (p=0.125)"
        checks.append(MetricCheck(metric, mine, float(want), ok, note))
    return checks


def check_against_baseline(
    report: Mapping[str, object],
    baseline: Mapping[str, object],
    corpus: str,
) -> list[MetricCheck]:
    """Witness a re-run `report` reproduces a certified `baseline` report's
    metrics EXACTLY to 4dp, using the same predicate/renderer as `accept`. The
    baseline's own scored ArmMetrics (plus its n) is the expected set."""
    base = score_arm(baseline, corpus)
    expected = {**base.as_dict(), "n": base.n}
    return compare_metrics(score_arm(report, corpus), expected, corpus=corpus, replay=True)


def render_checks(corpus: str, arm: str, checks: Sequence[MetricCheck]) -> str:
    lines = [f"  acceptance: {arm} x {corpus}"]
    for check in checks:
        status = "MATCH" if check.ok else "MISMATCH"
        suffix = f"  [{check.note}]" if check.note else ""
        lines.append(
            f"    {check.metric:22s} harness={check.got:.6f} "
            f"reference={check.expected:.6f}  {status}"
            f"{'' if check.ok else f' (delta {check.delta_pp:+.2f}pp)'}{suffix}"
        )
    return "\n".join(lines)


def check_report_file(
    path: str | Path, corpus: str, arm: str, *, replay: bool = True
) -> list[MetricCheck]:
    return check_arm(load_report(path), corpus, arm, replay=replay)
