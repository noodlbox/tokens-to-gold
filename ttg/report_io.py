"""Loading eval reports, including the stdout-capture form.

The M23-P4 L1 derivation reports are **stdout captures, not clean JSON**:
`deepswe_frozen_ts40.json` carries a 5,688-line log preamble and the JSON
document begins at line 5689. Every consumer to date rediscovered this by
crashing on `json.load`. The packaging step emits clean fixtures, but the
loader still accepts the raw captures so an operator can point the harness at
an unprocessed run without a manual edit.

The skip is deliberately narrow: find the first line that begins a JSON
object at column 0 and parse from there. A preamble that is truncated
mid-JSON must RAISE, never silently parse a prefix into a plausible-looking
partial report.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Mapping
from pathlib import Path
from typing import Final

_JSON_START: Final = "\n{"


class ReportFormatError(ValueError):
    """The file is neither clean JSON nor a recoverable stdout capture."""


LEGACY_ROW_KEYS: Final[dict[str, str]] = {
    "token_coverage_wire": "token_coverage_ranked_list",
    "retrieved_wire_positions": "retrieved_ranked_list_positions",
}
"""Engine report keys before LEDGER B64 renamed the ranked-list price.

A report written by an engine before that rename is dated evidence and is never
rewritten on disk. It is upgraded in memory, once, here -- the one seam every
report read passes through -- so the rest of the harness knows one name. A row
carrying both spellings is refused: that is not a report any engine wrote."""


def _upgrade_legacy_rows(report: dict[str, object]) -> dict[str, object]:
    results = report.get("results")
    if not isinstance(results, list):
        return report
    for row in results:
        if not isinstance(row, dict):
            continue
        for legacy, current in LEGACY_ROW_KEYS.items():
            if legacy not in row:
                continue
            if current in row:
                raise ReportFormatError(
                    f"row {row.get('instance_id')!r} carries both {legacy!r} and {current!r}"
                )
            row[current] = row.pop(legacy)
    return report


def loads_report(text: str) -> dict[str, object]:
    """Parse a report from text, tolerating a leading stdout preamble."""
    stripped = text.lstrip()
    if stripped.startswith("{"):
        try:
            return _upgrade_legacy_rows(json.loads(stripped))
        except json.JSONDecodeError as exc:
            raise ReportFormatError(f"clean-JSON parse failed: {exc}") from exc
    marker = text.find(_JSON_START)
    if marker < 0:
        raise ReportFormatError(
            "no JSON document found: the file has no line beginning with '{' "
            "at column 0, so it is neither clean JSON nor a stdout capture"
        )
    try:
        return _upgrade_legacy_rows(json.loads(text[marker + 1 :]))
    except json.JSONDecodeError as exc:
        raise ReportFormatError(
            f"found a JSON start at byte {marker + 1} but the document is not "
            f"parseable — a truncated capture is not a partial report: {exc}"
        ) from exc


def load_report(path: str | Path) -> dict[str, object]:
    """Load a report from disk, tolerating a leading stdout preamble."""
    return loads_report(Path(path).read_text(encoding="utf-8"))


def result_rows(report: Mapping[str, object]) -> list[Mapping[str, object]]:
    """Every non-error result row, in report order."""
    results = report.get("results")
    if not isinstance(results, list):
        raise ReportFormatError("report has no results[]")
    return [r for r in results if isinstance(r, Mapping) and "error" not in r]


def binding_curve(row: Mapping[str, object]) -> Mapping[str, object]:
    """The binding ranked-list curve for a result row.

    `token_coverage_ranked_list` when the arm prices its ranked list (shipped/levers),
    else `token_coverage` — the native_floor comparator delivers spans whose ranked-list
    price IS their source-text token count (curve price == read for spans, B5 §5),
    carried as `token_coverage`. This is the single reader both the rollup and
    the within-budget reach consume, so the two can never disagree on which curve
    is binding for an arm."""
    curve = row.get("token_coverage_ranked_list")
    if isinstance(curve, Mapping) and curve.get("by_budget"):
        return curve
    tc = row.get("token_coverage")
    return tc if isinstance(tc, Mapping) else {}


def gold_bearing_rows(
    report: Mapping[str, object],
) -> Iterator[Mapping[str, object]]:
    """Non-error rows whose frozen gold is non-empty — the BINDING basis."""
    for row in result_rows(report):
        gold = row.get("gold_symbols")
        if isinstance(gold, list) and gold:
            yield row
