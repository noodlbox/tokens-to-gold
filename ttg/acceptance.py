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

from ttg.matcher import match_gold
from ttg.report_io import load_report, result_rows
from ttg.rollup import rollup

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
    "reach_at_80",
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


def load_fixture() -> Mapping[str, object]:
    """Load the reference fixture, verifying its pinned digest."""
    if not FIXTURE_PATH.exists():
        raise AcceptanceError(f"acceptance fixture missing: {FIXTURE_PATH}")
    raw = FIXTURE_PATH.read_bytes()
    sums = (FIXTURE_PATH.parent / "SHA256SUMS").read_text().split()
    pinned = dict(zip(sums[1::2], sums[0::2])).get(FIXTURE_PATH.name)
    got = hashlib.sha256(raw).hexdigest()
    if pinned and got != pinned:
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
    """The six locked metrics for one (arm, corpus) cell."""

    n: int
    head_only_at_10: float
    head_only_at_25: float
    gold_at_8k_wire: float
    gold_at_32k_wire: float
    reach_at_80: float
    whole_list_INTERNAL: float

    def as_dict(self) -> dict[str, float]:
        return {name: float(getattr(self, name)) for name in LOCKED_METRICS}


def score_arm(report: Mapping[str, object], corpus: str) -> ArmMetrics:
    """Score one arm's report against the PINNED frozen gold.

    Recall metrics come from offline set-match (frozen denominators,
    first-occurrence-per-gold-identity). Wire metrics are rolled up from the
    report's own `token_coverage_wire` over the gold-bearing basis.
    """
    gold = load_frozen_gold(corpus)
    rows = {r.get("instance_id"): r for r in result_rows(report)}
    matches = [
        match_gold(symbols, [str(s) for s in (rows.get(iid, {}).get("retrieved_symbols") or [])])
        for iid, symbols in gold.items()
    ]
    n = len(matches)
    if not n:
        raise AcceptanceError(f"{corpus}: frozen gold is empty")
    roll = rollup(report, frozen_instance_ids=list(gold))
    return ArmMetrics(
        n=n,
        head_only_at_10=sum(m.recall_at(10) for m in matches) / n,
        head_only_at_25=sum(m.recall_at(25) for m in matches) / n,
        gold_at_8k_wire=roll.binding.gold_at_budget[8_000],
        gold_at_32k_wire=roll.binding.gold_at_budget[32_000],
        # FROZEN-DECIDABLE reach: the fraction of frozen-gold instances whose
        # OFFLINE whole recall clears the bar. NOT the report's own
        # `tokens_to_coverage`, which a reuse arm computes against its own
        # drifted gold -- on the py ablation the two differ by exactly one
        # instance (2.56pp). Verified equal on all four reference cells.
        reach_at_80=sum(1 for m in matches if m.recall >= REACH_COVERAGE) / n,
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
