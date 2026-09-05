"""Derive-stage guards: the zero-gold NO-GO alarm and the drift sidecar.

Two things must be true before a freshly derived tier can carry a number, and
neither is allowed to resolve itself silently.

1. ZERO-GOLD ALARM (pre-registered). An instance whose reference patch touches
   no resolvable symbol has no gold. A few are normal; a lot means the language
   is not really being analyzed (the exact failure mode a rust-OFF binary
   produces: an all-empty gold that reads as a valid 0-coverage result). Above
   `ZERO_GOLD_ALARM_RATE` the tier is NO-GO until ruled — whitelist vs
   version-bump vs language-scope — never a quiet publish.

2. DERIVATION DRIFT (U2/R-B4). The regression axis holds gold FIXED. A fresh
   re-derivation is a sidecar: per-instance SET-MATCH against the frozen gold,
   reported as a finding. There is deliberately NO write path in this module —
   drift can be reported, never re-frozen.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

ZERO_GOLD_ALARM_RATE = 0.10
"""Pre-registered NO-GO threshold for a tier's zero-gold fraction."""


@dataclass(frozen=True)
class ZeroGoldCheck:
    corpus: str
    total_instances: int
    with_gold: int
    zero_gold: int
    rate: float
    alarm: bool

    def summary(self) -> str:
        verdict = "ALARM — tier is NO-GO until ruled" if self.alarm else "within budget"
        return (
            f"{self.corpus}: {self.zero_gold}/{self.total_instances} zero-gold "
            f"({self.rate:.1%}; threshold {ZERO_GOLD_ALARM_RATE:.0%}) — {verdict}"
        )


def zero_gold_check(
    corpus: str, gold: Mapping[str, Sequence[str]], total_instances: int
) -> ZeroGoldCheck:
    """Zero-gold rate over the WHOLE corpus.

    An instance missing from `gold` counts as zero-gold exactly like one mapped
    to an empty list — otherwise a derivation that dropped instances entirely
    would look cleaner than one that recorded them empty."""
    if total_instances <= 0:
        raise ValueError("total_instances must be positive")
    with_gold = sum(1 for iid in gold if gold[iid])
    zero = total_instances - with_gold
    rate = zero / total_instances
    return ZeroGoldCheck(
        corpus=corpus, total_instances=total_instances, with_gold=with_gold,
        zero_gold=zero, rate=rate, alarm=rate > ZERO_GOLD_ALARM_RATE,
    )


@dataclass(frozen=True)
class InstanceDrift:
    instance_id: str
    added: tuple[str, ...]
    removed: tuple[str, ...]


@dataclass(frozen=True)
class DriftReport:
    corpus: str
    compared: int
    identical: int
    drifted: tuple[InstanceDrift, ...]
    only_frozen: tuple[str, ...]
    only_rederived: tuple[str, ...]

    @property
    def clean(self) -> bool:
        return not (self.drifted or self.only_frozen or self.only_rederived)


def drift_report(
    corpus: str,
    frozen: Mapping[str, Sequence[str]],
    rederived: Mapping[str, Sequence[str]],
) -> DriftReport:
    """Per-instance SET-MATCH of a re-derivation against the frozen anchor.

    Pure: it reports, it never re-freezes. Symbol ORDER is ignored (the freeze
    preserves report order, but a set difference is the meaningful comparison);
    duplicates collapse, because gold is claimed at most once per symbol."""
    shared = sorted(set(frozen) & set(rederived))
    drifted: list[InstanceDrift] = []
    identical = 0
    for iid in shared:
        before, after = set(frozen[iid]), set(rederived[iid])
        if before == after:
            identical += 1
            continue
        drifted.append(InstanceDrift(
            instance_id=iid,
            added=tuple(sorted(after - before)),
            removed=tuple(sorted(before - after)),
        ))
    return DriftReport(
        corpus=corpus, compared=len(shared), identical=identical,
        drifted=tuple(drifted),
        only_frozen=tuple(sorted(set(frozen) - set(rederived))),
        only_rederived=tuple(sorted(set(rederived) - set(frozen))),
    )


def render_drift(report: DriftReport) -> str:
    if report.clean:
        return (
            f"{report.corpus}: derivation SET-MATCHES the frozen gold on all "
            f"{report.compared} instances — no drift."
        )
    lines = [
        f"{report.corpus}: derivation drift — {report.identical}/{report.compared} "
        f"identical, {len(report.drifted)} drifted "
        f"(frozen gold remains the anchor; nothing re-frozen)."
    ]
    for d in report.drifted:
        lines.append(f"  {d.instance_id}: +{len(d.added)} -{len(d.removed)}")
        for s in d.added:
            lines.append(f"    + {s}")
        for s in d.removed:
            lines.append(f"    - {s}")
    if report.only_frozen:
        lines.append(f"  only in frozen: {', '.join(report.only_frozen)}")
    if report.only_rederived:
        lines.append(f"  only in re-derived: {', '.join(report.only_rederived)}")
    return "\n".join(lines)
