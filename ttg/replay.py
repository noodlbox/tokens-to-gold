"""The 12-cell replay witness (R22 (c)) — the grid is DERIVED, never typed.

WHY THIS MODULE EXISTS
----------------------
`accept` and `accept-vs` are per-cell. Nothing asserted that the whole grid was
compared, and c3's stated failure mode is a cell that is silently ABSENT: eleven
green lines read like twelve, and the one cell that regressed is the one nobody
ran. So the cell set comes from `arms.arm_matrix` — section-5 arms x pinned
corpora — and a cell that was not compared is a REFUSAL naming that cell, never a
shorter table. Nothing here writes `12`.

WHICH ANCHOR EACH CELL USES, and why it is decided by MEASUREMENT
----------------------------------------------------------------
Two anchors exist, and they are not interchangeable:

* the **V1 pins** (`acceptance/MEASURER_V1_REFERENCE_NUMBERS_2026-08-20.json`) —
  an older, independent authority. Stronger evidence where it applies.
* the **certified re-cert reports** — this campaign's own committed outputs. The
  only anchor available for tiers V1 never had (go34, rust43).

A cell is V1-anchored iff (a) the fixture pins it AND (b) the CERTIFIED baseline
itself still reproduces those pins. (b) is checked, not assumed, because a cell
whose V1 reproduction was already disclosed lost cannot be re-demanded of the
released binary: asking it to reproduce something the certification itself did
not would refuse a correct binary for a known reason. That check is not circular
— the certified report is fixed and committed, independent of the binary under
test — and every verdict line NAMES the anchor it used, so a drop in V1-anchored
cells is visible rather than silent.

`replay` is never `--fresh`: `NOISE_FLOOR_PP` is the cross-run re-derivation
tolerance and must not apply to a replay, which is exact-to-4dp by construction.
"""

from __future__ import annotations

from collections.abc import Sequence
from pathlib import Path

from arms.arm_matrix import CORPORA, SECTION5_ARMS
from ttg.acceptance import (
    AcceptanceError,
    MetricCheck,
    check_against_baseline,
    check_arm,
)
from ttg.report_io import load_report

ANCHOR_V1 = "V1-pins"
ANCHOR_CERTIFIED = "certified"


def derive_cells() -> list[tuple[str, str]]:
    """Every `(arm, corpus)` cell the replay must cover, from the matrix itself.

    Read from `SECTION5_ARMS` x `CORPORA` so that adding a tier grows the grid
    without anyone remembering to update a count here."""
    return [(arm, corpus) for arm in SECTION5_ARMS for corpus in sorted(CORPORA)]


def report_path(directory: Path, arm: str, corpus: str) -> Path:
    return Path(directory) / f"{arm}_{corpus}.json"


def missing_cells(
    reports_dir: Path, certified_dir: Path, cells: Sequence[tuple[str, str]]
) -> list[tuple[tuple[str, str], str]]:
    """Cells whose report or certified baseline is absent, each with which side
    is missing. Absence is the failure c3 exists to catch, so it is reported per
    cell rather than as one 'some files missing'."""
    missing: list[tuple[tuple[str, str], str]] = []
    for arm, corpus in cells:
        if not report_path(reports_dir, arm, corpus).is_file():
            missing.append(((arm, corpus), "report"))
        elif not report_path(certified_dir, arm, corpus).is_file():
            missing.append(((arm, corpus), "certified baseline"))
    return missing


def choose_anchor(*, pinned: bool, certified_matches: bool) -> str:
    """V1 pins only when the fixture pins the cell AND the certified baseline
    still reproduces them; otherwise the certified report."""
    return ANCHOR_V1 if pinned and certified_matches else ANCHOR_CERTIFIED


def _fixture_reproduced_by(certified: dict, corpus: str, arm: str) -> tuple[bool, bool]:
    """`(pinned, certified_matches)` for one cell. A cell the fixture does not
    pin raises `AcceptanceError`, which is the 'not pinned' answer, not a fault."""
    try:
        checks = check_arm(certified, corpus, arm, replay=True)
    except AcceptanceError:
        return False, False
    return True, all(check.ok for check in checks)


def replay_cell(
    reports_dir: Path, certified_dir: Path, arm: str, corpus: str
) -> tuple[str, list[MetricCheck]]:
    """Compare one cell against its anchor. Returns `(anchor, checks)`."""
    fresh = load_report(report_path(reports_dir, arm, corpus))
    certified = load_report(report_path(certified_dir, arm, corpus))
    pinned, certified_matches = _fixture_reproduced_by(certified, corpus, arm)
    anchor = choose_anchor(pinned=pinned, certified_matches=certified_matches)
    if anchor == ANCHOR_V1:
        return anchor, check_arm(fresh, corpus, arm, replay=True)
    return anchor, check_against_baseline(fresh, certified, corpus)


def run(reports_dir: Path, certified_dir: Path) -> tuple[list[str], list[str]]:
    """The whole grid. Returns `(lines, failures)`; `failures` non-empty == rc 1.

    Every derived cell must be present, compared, and pass. A cell that compared
    ZERO metrics is a failure too (c4 non-vacuity): a green produced by comparing
    nothing is the parity test's `checked > 0` bug wearing a different hat.
    """
    cells = derive_cells()
    lines: list[str] = []
    failures: list[str] = []

    for cell, side in missing_cells(reports_dir, certified_dir, cells):
        arm, corpus = cell
        failures.append(f"{arm} x {corpus}: {side} absent")
    if failures:
        return lines, failures

    anchors: dict[str, int] = {}
    for arm, corpus in cells:
        anchor, checks = replay_cell(reports_dir, certified_dir, arm, corpus)
        anchors[anchor] = anchors.get(anchor, 0) + 1
        bad = [check for check in checks if not check.ok]
        if not checks:
            failures.append(f"{arm} x {corpus}: compared ZERO metrics (vacuous)")
            lines.append(f"  VACUOUS  {arm:22s} x {corpus:12s} [{anchor}]  0 metrics")
            continue
        if bad:
            failures.append(
                f"{arm} x {corpus}: {len(bad)} metric(s) beyond replay tolerance "
                f"({', '.join(check.metric for check in bad)})"
            )
        lines.append(
            f"  {'PASS' if not bad else 'FAIL':8s} {arm:22s} x {corpus:12s} "
            f"[{anchor}]  {len(checks)} metrics"
        )

    lines.append(
        f"  cells={len(cells)} "
        + " ".join(f"{name}={count}" for name, count in sorted(anchors.items()))
    )
    return lines, failures
