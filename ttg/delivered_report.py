"""Score the delivered arm's cells into a report (PREREGISTRATION addenda of
2026-09-29).

Reads only what `ttg.delivered_cells` wrote: each invocation's argv, exit code
and exact stdout/stderr bytes. Per scored row and instance it records the
delivered identities' frozen-gold recall (the grep rows' lower bound is the
headline, the upper bound and ambiguous-hit count sit beside it) and the o200k
price of the bytes delivered. A FAILED cell scores 0.0 and is listed; a corpus
row with more than `MAX_FAILED_CELLS` failed cells is not publishable.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from pathlib import Path

from ttg.acceptance import load_frozen_gold
from ttg.delivered import (
    DeliveredScoringError,
    DeliveredSurface,
    TokenCount,
    grep_identities,
    json_identities,
    price,
    recall,
)
from ttg.delivered_cells import BUDGETS, MCP_ROW, mcp_response
from ttg.paired_stats import bootstrap_mean_ci, sign_test

MAX_FAILED_CELLS = 2
"""Addendum §1: a corpus row with more failed cells than this is not publishable."""

AMBIGUITY_FLAG_PP = 0.5
"""Addendum §3 / addendum 2 A: the upper/lower gap that carries a visible note."""

REACH_COVERAGE = 0.8


@dataclass(frozen=True)
class ScoredRow:
    """One (row, budget) scoring plan: which cell file to read, how to read it."""

    key: str
    surface: DeliveredSurface
    budget: int | None
    oracle: str | None = None


SCORED_ROWS: tuple[ScoredRow, ...] = (
    *(ScoredRow(f"grep.{b}", DeliveredSurface.GREP, b, "oracle.implement") for b in BUDGETS),
    *(ScoredRow(f"json.{b}", DeliveredSurface.JSON, b) for b in BUDGETS),
    ScoredRow("default", DeliveredSurface.DEFAULT, None, "oracle.explore"),
    ScoredRow(MCP_ROW, DeliveredSurface.MCP, None),
)

MCP_COMPARAND = "json.explore_default"


@dataclass(frozen=True)
class InstanceScore:
    instance_id: str
    failed: str | None
    gold_lower: float
    gold_upper: float
    ambiguous_hits: int
    ttg_wire: int | None
    ttg_stdout: int | None
    ttg_stderr: int | None


class CellFiles:
    """One instance's recorded cell."""

    def __init__(self, cell_dir: Path) -> None:
        self.dir = cell_dir
        self.manifest: Mapping[str, object] = json.loads((cell_dir / "cell.json").read_text(encoding="utf-8"))

    def row_rc(self, key: str) -> int | None:
        rows = self.manifest.get("rows")
        row = rows.get(key) if isinstance(rows, Mapping) else None
        rc = row.get("rc") if isinstance(row, Mapping) else None
        return rc if isinstance(rc, int) else None

    def stdout(self, key: str) -> bytes:
        return (self.dir / f"{key}.stdout").read_bytes()

    def stderr(self, key: str) -> bytes:
        return (self.dir / f"{key}.stderr").read_bytes()


def mcp_content_text(transcript: bytes) -> str:
    """The `nbx_search` tool result's content text: the body an MCP client puts
    in context (addendum 2 C). A tool error or a missing answer fails the cell."""
    response = mcp_response(transcript)
    if response is None:
        raise DeliveredScoringError("no nbx_search response in the MCP transcript")
    result = response.get("result")
    if not isinstance(result, Mapping):
        raise DeliveredScoringError(f"MCP call returned no result: {response.get('error')}")
    if result.get("isError") is True:
        raise DeliveredScoringError("MCP nbx_search returned a tool error")
    content = result.get("content")
    texts = [
        part["text"]
        for part in content if isinstance(part, Mapping) and part.get("type") == "text" and isinstance(part.get("text"), str)
    ] if isinstance(content, list) else []
    if not texts:
        raise DeliveredScoringError("MCP nbx_search result carries no text content")
    return "".join(texts)


def _failed(instance_id: str, reason: str) -> InstanceScore:
    return InstanceScore(instance_id, reason, 0.0, 0.0, 0, None, None, None)


def score_instance(cell: CellFiles, row: ScoredRow, gold: Sequence[str], count: TokenCount) -> InstanceScore:
    iid = str(cell.manifest.get("instance_id"))
    analyze = cell.manifest.get("analyze")
    if not isinstance(analyze, Mapping) or analyze.get("rc") != 0:
        return _failed(iid, "analyze failed")
    if cell.row_rc(row.key) != 0:
        return _failed(iid, f"{row.key} exited {cell.row_rc(row.key)}")
    try:
        if row.surface is DeliveredSurface.MCP:
            body = mcp_content_text(cell.stdout(row.key))
            identities = json_identities(body)
            cost = price(body.encode(), b"", count)
            return InstanceScore(iid, None, recall(gold, identities), recall(gold, identities), 0,
                                 cost.wire, cost.stdout, None)
        stdout, stderr = cell.stdout(row.key), cell.stderr(row.key)
        cost = price(stdout, stderr, count)
        if row.surface.is_grep:
            if row.oracle is None or cell.row_rc(row.oracle) != 0:
                return _failed(iid, f"identity oracle {row.oracle} failed")
            grep = grep_identities(stdout.decode(), cell.stdout(row.oracle).decode())
            return InstanceScore(iid, None, recall(gold, grep.lower), recall(gold, grep.upper),
                                 grep.ambiguous_hits, cost.wire, cost.stdout, cost.stderr)
        identities = json_identities(stdout.decode())
        return InstanceScore(iid, None, recall(gold, identities), recall(gold, identities), 0,
                             cost.wire, cost.stdout, cost.stderr)
    except DeliveredScoringError as exc:
        return _failed(iid, str(exc))


def _percentile(values: Sequence[int], q: float) -> int | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[min(len(ordered) - 1, int(q * len(ordered)))]


def summarize(row: ScoredRow, scores: Sequence[InstanceScore]) -> dict[str, object]:
    n = len(scores)
    wires = [s.ttg_wire for s in scores if s.ttg_wire is not None]
    failed = [(s.instance_id, s.failed) for s in scores if s.failed is not None]
    lower = sum(s.gold_lower for s in scores) / n if n else 0.0
    upper = sum(s.gold_upper for s in scores) / n if n else 0.0
    return {
        "row": row.key,
        "surface": row.surface.value,
        "budget": row.budget,
        "n": n,
        "gold_delivered": lower,
        "gold_delivered_upper": upper,
        "ambiguous_hits": sum(s.ambiguous_hits for s in scores),
        "ambiguity_flag": (upper - lower) * 100 > AMBIGUITY_FLAG_PP,
        "reach_at_80_within_budget": sum(1 for s in scores if s.gold_lower >= REACH_COVERAGE) / n if n else 0.0,
        "ttg_wire_median": round(statistics.median(wires)) if wires else None,
        "ttg_wire_p90": _percentile(wires, 0.9),
        "ttg_wire_max": max(wires) if wires else None,
        "ttg_stdout_median": round(statistics.median(v)) if (v := [s.ttg_stdout for s in scores if s.ttg_stdout is not None]) else None,
        "ttg_stderr_median": round(statistics.median(v)) if (v := [s.ttg_stderr for s in scores if s.ttg_stderr is not None]) else None,
        "over_budget_cells": sum(1 for w in wires if row.budget is not None and w > row.budget),
        "failed_cells": [{"instance_id": iid, "reason": reason} for iid, reason in failed],
        "publishable": len(failed) <= MAX_FAILED_CELLS,
    }


def mcp_byte_identical(cells: Sequence[CellFiles]) -> bool | None:
    """True iff every cell's MCP content text equals its CLI JSON comparand's
    stdout byte for byte; None when no cell has both."""
    verdicts = []
    for cell in cells:
        if cell.row_rc(MCP_ROW) != 0 or cell.row_rc(MCP_COMPARAND) != 0:
            continue
        try:
            body = mcp_content_text(cell.stdout(MCP_ROW)).encode()
        except DeliveredScoringError:
            continue
        verdicts.append(body == cell.stdout(MCP_COMPARAND))
    return all(verdicts) if verdicts else None


def score_corpus(out_root: Path, corpus: str, count: TokenCount, build: Mapping[str, object]) -> dict[str, object]:
    """The delivered report for one corpus: every gold-bearing instance, every
    scored row. A gold-bearing instance with no recorded cell is a failed cell."""
    gold = load_frozen_gold(corpus)
    corpus_dir = out_root / corpus
    cells = {iid: CellFiles(corpus_dir / iid) for iid in gold if gold[iid] and (corpus_dir / iid / "cell.json").is_file()}
    rows: dict[str, object] = {}
    for row in SCORED_ROWS:
        scores = [
            score_instance(cells[iid], row, gold[iid], count) if iid in cells else _failed(iid, "no cell recorded")
            for iid in sorted(i for i in gold if gold[i])
        ]
        rows[row.key] = {"summary": summarize(row, scores), "instances": [asdict(s) for s in scores]}
    return {
        "arm": "delivered",
        "arm_kind": "delivered",
        "publishable_as_delivered": True,
        "corpus": corpus,
        "build": dict(build),
        "mcp_byte_identical_to_cli_json": mcp_byte_identical(list(cells.values())),
        "rows": rows,
    }


def paired_delta(base: Mapping[str, object], head: Mapping[str, object], row: str) -> dict[str, object]:
    """Head − base per instance for one row's headline recall, in pp: the
    bootstrap 95 % CI and the exact sign test, paired by instance id."""

    def by_instance(report: Mapping[str, object]) -> dict[str, float]:
        rows = report.get("rows")
        entry = rows.get(row) if isinstance(rows, Mapping) else None
        instances = entry.get("instances") if isinstance(entry, Mapping) else None
        if not isinstance(instances, list):
            raise DeliveredScoringError(f"report has no scored row {row!r}")
        return {
            str(s["instance_id"]): float(s["gold_lower"])
            for s in instances if isinstance(s, Mapping)
        }

    b, h = by_instance(base), by_instance(head)
    deltas = [(h.get(iid, 0.0) - b.get(iid, 0.0)) * 100 for iid in sorted(b.keys() | h.keys())]
    ci = bootstrap_mean_ci(deltas)
    sign = sign_test(deltas)
    return {
        "row": row,
        "n": len(deltas),
        "mean_delta_pp": sum(deltas) / len(deltas) if deltas else 0.0,
        "ci95_pp": [ci.lower, ci.upper] if ci is not None else None,
        "sign": asdict(sign),
    }
