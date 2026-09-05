"""Derive-stage guards: the zero-gold NO-GO alarm and the drift sidecar.

Two things must be true before a freshly derived tier can carry a number, and
neither is allowed to resolve itself silently.

1. ZERO-GOLD ALARM (pre-registered). An instance whose reference patch touches
   no resolvable symbol has no gold. A few are normal; a lot means the language
   is not really being analyzed (the exact failure mode a rust-OFF binary
   produces: an all-empty gold that reads as a valid 0-coverage result). Above
   `ZERO_GOLD_ALARM_RATE` the tier is NO-GO until ruled — whitelist vs
   version-bump vs language-scope — never a quiet publish.

   ERRORED is a THIRD class, distinct from zero-gold (rust43 ruling, R-R43):
   an instance the engine could not analyze (an `error` field in the derived
   report) was never scored, so it is neither gold-bearing nor zero-gold. It is
   excluded from the denominator and the rate is computed over (total −
   errored). Counting an error as zero-gold conflates "the engine failed" with
   "the reference patch had nothing to resolve" — a 5-repo indexing bug read as
   a corpus property.

2. DERIVATION DRIFT (U2/R-B4). The regression axis holds gold FIXED. A fresh
   re-derivation is a sidecar: per-instance SET-MATCH against the frozen gold,
   reported as a finding. There is deliberately NO write path in this module —
   drift can be reported, never re-frozen.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

ZERO_GOLD_ALARM_RATE = 0.10
"""Pre-registered NO-GO threshold for a tier's zero-gold fraction."""


@dataclass(frozen=True)
class ZeroGoldCheck:
    corpus: str
    total_instances: int
    errored: int
    scored: int
    with_gold: int
    zero_gold: int
    rate: float
    alarm: bool

    def summary(self) -> str:
        # States the FACT only; the verdict belongs to tier_disposition, which
        # knows whether a ruling exists. Otherwise a ruled tier prints
        # "NO-GO until ruled" next to its own ruling.
        verdict = "ALARM (above threshold)" if self.alarm else "within budget"
        errored = f", {self.errored} errored (excluded)" if self.errored else ""
        return (
            f"{self.corpus}: {self.zero_gold}/{self.scored} zero-gold"
            f"{errored} ({self.rate:.1%}; threshold {ZERO_GOLD_ALARM_RATE:.0%}) "
            f"— {verdict}"
        )


def zero_gold_check(
    corpus: str,
    gold: Mapping[str, Sequence[str]],
    total_instances: int,
    errored_instances: frozenset[str] = frozenset(),
) -> ZeroGoldCheck:
    """Zero-gold rate over the SCORED set (total − errored).

    Three classes, not two (R-R43): gold-bearing, scored-and-empty (zero-gold),
    and errored. An errored instance was never scored, so it is excluded from
    the denominator rather than counted as zero-gold — otherwise an engine
    indexing failure reads as a corpus property. Among the scored, an instance
    missing from `gold` counts as zero-gold exactly like one mapped to an empty
    list, so a derivation that dropped instances cannot look cleaner than one
    that recorded them empty."""
    if total_instances <= 0:
        raise ValueError("total_instances must be positive")
    errored = len(errored_instances)
    if errored > total_instances:
        raise ValueError(
            f"{errored} errored exceeds {total_instances} total instances")
    scored = total_instances - errored
    with_gold = sum(
        1 for iid in gold if gold[iid] and iid not in errored_instances)
    zero = scored - with_gold
    rate = zero / scored if scored else 0.0
    return ZeroGoldCheck(
        corpus=corpus, total_instances=total_instances, errored=errored,
        scored=scored, with_gold=with_gold, zero_gold=zero, rate=rate,
        alarm=rate > ZERO_GOLD_ALARM_RATE,
    )


# A tier whose alarm has been ADJUDICATED. The alarm still fires and is still
# reported; the ruling records that the cause was inspected and the tier ships
# with its rate and cause disclosed. Adding an entry here is a design-owner
# decision with a written ruling behind it -- never a lane's convenience.
RULED_ALARM_EXCEPTIONS: dict[str, str] = {
    "go34": (
        "TTG_RECERT_RULING_GO34_ALARM_2026-09-05.md — 4/34 zero-gold (11.8%); "
        "all four are new-file-dominated reference patches, for which the "
        "reference-patch proxy has no pre-existing symbols to score"
    ),
}


class Disposition(str, Enum):
    CERTIFIED = "CERTIFIED"
    """Within the pre-registered zero-gold budget."""
    CERTIFIED_WITH_DISCLOSURE = "CERTIFIED-WITH-DISCLOSURE"
    """Alarmed, adjudicated by a written ruling; ships with rate + cause."""
    NO_GO_PENDING_RULING = "NO-GO-PENDING-RULING"
    """Alarmed with no ruling. This tier publishes nothing until one exists."""


@dataclass(frozen=True)
class TierDisposition:
    corpus: str
    check: ZeroGoldCheck
    disposition: Disposition
    ruling: str | None

    @property
    def publishable(self) -> bool:
        return self.disposition is not Disposition.NO_GO_PENDING_RULING


def tier_disposition(check: ZeroGoldCheck) -> TierDisposition:
    """Decide ONE tier's fate. Deliberately per-tier: an alarm is NO-GO for the
    tier that alarmed, never for the run (R-P5/R-G4), so a single alarming tier
    cannot discard the remaining tiers' hours of derivation and arm runs."""
    if not check.alarm:
        return TierDisposition(check.corpus, check, Disposition.CERTIFIED, None)
    ruling = RULED_ALARM_EXCEPTIONS.get(check.corpus)
    if ruling is not None:
        return TierDisposition(
            check.corpus, check, Disposition.CERTIFIED_WITH_DISCLOSURE, ruling)
    return TierDisposition(
        check.corpus, check, Disposition.NO_GO_PENDING_RULING, None)


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
