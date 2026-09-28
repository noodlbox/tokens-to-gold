"""Render delivered-arm reports as the page's headline tables (LEDGER B64).

Every report passes `require_delivered` before a number is composed, so a
ranked-list ceiling report can never be rendered here. One table per corpus,
the headline row (`delivered.grep` at 8k and 32k) first; every other delivered
row beside it, never merged.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ttg.publication import require_delivered

HEADLINE_ROWS = ("grep.8000", "grep.32000")
ROW_ORDER = ("grep.8000", "grep.32000", "grep.4000", "json.4000", "json.8000", "json.32000", "default", "mcp")


def _tokens(value: object) -> str:
    return f"{value:,}" if isinstance(value, int) else "—"


def _summary(report: Mapping[str, object], row: str) -> Mapping[str, object] | None:
    rows = report.get("rows")
    entry = rows.get(row) if isinstance(rows, Mapping) else None
    summary = entry.get("summary") if isinstance(entry, Mapping) else None
    return summary if isinstance(summary, Mapping) else None


def render_corpus(report: Mapping[str, object]) -> str:
    require_delivered(report)
    out = [
        f"### `{report.get('corpus')}` — delivered by `nbx search`",
        "",
        "| Row | Gold delivered (headline) | upper bound | ambiguous hits | reach@80 "
        "| ttg_wire median / p90 / max | stdout / stderr median | over budget | failed cells |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for row in ROW_ORDER:
        s = _summary(report, row)
        if s is None:
            continue
        mark = " **(headline)**" if row in HEADLINE_ROWS else ""
        flag = " ⚑" if s.get("ambiguity_flag") else ""
        failed = s.get("failed_cells")
        n_failed = len(failed) if isinstance(failed, list) else 0
        publishable = "" if s.get("publishable") else " (not publishable)"
        out.append(
            f"| `{row}`{mark} | {float(s['gold_delivered']):.4f} | {float(s['gold_delivered_upper']):.4f}{flag} "
            f"| {s.get('ambiguous_hits')} | {float(s['reach_at_80_within_budget']):.4f} "
            f"| {_tokens(s.get('ttg_wire_median'))} / {_tokens(s.get('ttg_wire_p90'))} / {_tokens(s.get('ttg_wire_max'))} "
            f"| {_tokens(s.get('ttg_stdout_median'))} / {_tokens(s.get('ttg_stderr_median'))} "
            f"| {s.get('over_budget_cells')} | {n_failed}{publishable} |"
        )
    identical = report.get("mcp_byte_identical_to_cli_json")
    if identical is True:
        out.append("")
        out.append("The MCP `nbx_search` content is byte-identical to CLI `--format json` (same defaults).")
    out.append("")
    return "\n".join(out)


def render_headline(reports: Sequence[Mapping[str, object]]) -> str:
    for report in reports:
        require_delivered(report)
    return "\n".join(["## What `nbx search` delivers", "", *(render_corpus(r) for r in reports)])
