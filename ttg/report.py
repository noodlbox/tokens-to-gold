"""The 4-language re-certification report — composed, never re-scored.

This assembles the PUBLISHED artifact for the 2026-09 re-cert from the per-cell
arm reports of the two-lease split, in the S7 LOCKED claims language. It owns no
scoring of its own: every number comes from `acceptance.score_arm` (the frozen-
gold cell scorer, MUST-NOT #1 safe), `rollup` (cost-to-coverage), and
`acceptance.check_arm` (the exact-to-4dp V1 replay). One binary scores every
cell; the split is a lease-budget device, invisible in the numbers.

Locked-language discipline (S7 memo, enforced here):
  * external metrics are coverage@budget (Gold@B_wire), head-only@k, and
    cost-to-coverage (median TtG@80) -- per-LANGUAGE, never blended, bound-
    labelled `ttg_wire`, always with N (the gold-bearing denominator);
  * whole-list recall is INTERNAL -- carried on the cell but NEVER rendered;
  * py head-only@10 is annotated NOT superiority-claimable (p=0.125);
  * no proven / 0-FP / moat / cost-hero; no bare "recall".

The V1 regression witness is the EXACT-to-4dp replay (`check_arm`), not a paired
bootstrap: the run9 per-instance baseline reports were destroyed by the shared-
OUT copy-back, so a bootstrap-vs-V1 is not computable -- and the exact replay is
strictly stronger (the deltas ARE zero, not merely bounded below the floor). The
paired-bootstrap machinery is still exercised, on the ONE comparison whose two
reports both exist: the lever effect (treatment - ablation).
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Final

from ttg.acceptance import (
    SUPERIORITY_CLAIMABLE,
    check_report_file,
    load_frozen_gold,
    score_arm,
)
from ttg.regression import DEFAULT_METRICS, compare_reports, render_table
from ttg.report_io import load_report
from ttg.rollup import rollup

PKG = Path(__file__).resolve().parent.parent

# Fixed publication order: one column per LANGUAGE, never blended.
CORPUS_LANG: Final[dict[str, str]] = {
    "ts40": "TypeScript",
    "py_nosphinx": "Python",
    "go34": "Go",
    "rust43": "Rust",
}
# The gold-bearing denominator per corpus (S7: ts40 37 / py 39; new tiers 30/40).
CORPUS_N: Final[dict[str, int]] = {
    "ts40": 37,
    "py_nosphinx": 39,
    "go34": 30,
    "rust43": 40,
}
NATIVE_FLOOR: Final = "native_floor"
ARMS: Final[tuple[str, ...]] = (
    "shipped_treatment",
    "levers_off_ablation",
    NATIVE_FLOOR,
)
BOUND: Final = "ttg_wire"
ONE_BINARY_SHA: Final = (
    "bf920e4a765b0fa5a403ee95ddfbb3d3a66449d07d2286da2bce878520e30783"
)

# The frozen gold each tier's distribution is read FROM (not from memory). ts40
# and py live in the canonical gold/ dir; the new tiers' gold still lives in
# their run artifacts until A4 commits them to gold/, so those are the fallback.
_GOLD_FALLBACKS: Final[dict[str, Path]] = {
    "go34": PKG
    / "runs"
    / "recert-2026-09"
    / "run8"
    / "out"
    / "gold"
    / "frozen_gold_go34.json",
    "rust43": PKG
    / "runs"
    / "recert-2026-09"
    / "certified"
    / "harbor-hermit-ts40py"
    / "frozen_gold_rust43.json",
}


@dataclass(frozen=True)
class GoldDistribution:
    """The symbols-per-instance shape of a tier's FROZEN gold. `thin_keys` (the
    count of instances whose gold is exactly ONE symbol) is the thin-keys caveat
    the page carries: a tier dominated by single-symbol gold is an easier target
    than its N alone suggests."""

    n: int
    thin_keys: int
    median_per_instance: float
    max_per_instance: int


def _resolve_gold_path(corpus: str, gold_dir: Path) -> Path | None:
    canonical = gold_dir / f"frozen_gold_{corpus}.json"
    if canonical.is_file():
        return canonical
    fallback = _GOLD_FALLBACKS.get(corpus)
    return fallback if fallback is not None and fallback.is_file() else None


def gold_distribution(gold_path: str | Path) -> GoldDistribution:
    """Compute the symbols-per-instance distribution from a frozen gold file's
    `gold` dict (list length per instance) -- read from disk, never remembered."""
    doc = json.loads(Path(gold_path).read_text(encoding="utf-8"))
    gold = doc.get("gold", doc)
    if not isinstance(gold, dict) or not gold:
        raise ValueError(f"{gold_path}: no gold payload")
    lengths = [len(v) for v in gold.values()]
    return GoldDistribution(
        n=len(lengths),
        thin_keys=sum(1 for x in lengths if x == 1),
        median_per_instance=statistics.median(lengths),
        max_per_instance=max(lengths),
    )


@dataclass(frozen=True)
class CellScore:
    """One (corpus, arm) cell in the locked language. whole_list_internal is
    carried for completeness but is INTERNAL and never rendered.

    Every arm prices retrieval by wire. shipped/levers deliver a curated wire
    index (`token_coverage_wire`); the native_floor (rg) comparator delivers
    spans — read content whose wire price IS its source-text token count under
    the same shared tokenizer (wire == read for spans, B5 §5) — carried as
    `token_coverage`. `rollup` treats both as the binding wire curve, so
    coverage@budget and cost-to-coverage are genuine wire-priced values for the
    floor, never a measured-looking 0.0000. Its head-only@k is NOT rendered: a
    span head and a symbol head are not comparable in one head-only row."""

    corpus: str
    arm: str
    n: int
    gold_at_8k: float
    gold_at_32k: float
    head_at_10: float
    head_at_25: float
    reach_at_80: float
    ttg80_median_wire: int | None
    whole_list_internal: float


@dataclass(frozen=True)
class Cell:
    """A cell is either SCORED or PENDING (its arm report is not in yet)."""

    corpus: str
    arm: str
    score: CellScore | None
    pending_reason: str | None


def _report_path(reports_dir: Path, corpus: str, arm: str) -> Path:
    return reports_dir / f"{arm}_{corpus}.json"


def _gold_available(corpus: str, gold_dir: Path) -> bool:
    return (gold_dir / f"frozen_gold_{corpus}.json").is_file()


def score_cell(report: Mapping[str, object], corpus: str, arm: str) -> CellScore:
    """Score one cell against its FROZEN gold. Recall metrics + N from
    `score_arm`; cost-to-coverage (median TtG@80) from the binding rollup."""
    metrics = score_arm(report, corpus)
    roll = rollup(report, frozen_instance_ids=list(load_frozen_gold(corpus)))
    return CellScore(
        corpus=corpus,
        arm=arm,
        n=metrics.n,
        gold_at_8k=metrics.gold_at_8k_wire,
        gold_at_32k=metrics.gold_at_32k_wire,
        head_at_10=metrics.head_only_at_10,
        head_at_25=metrics.head_only_at_25,
        reach_at_80=metrics.reach_at_80,
        ttg80_median_wire=roll.binding.median_ttg_at_coverage[80],
        whole_list_internal=metrics.whole_list_INTERNAL,
    )


def collect_cells(reports_dir: Path, gold_dir: Path) -> list[Cell]:
    """Every (corpus, arm) cell, scored where its report AND its frozen gold are
    present, PENDING otherwise. A present report with absent gold is a hard
    error -- a number with no denominator is exactly what the frozen basis
    forbids -- so `load_frozen_gold` is allowed to raise."""
    cells: list[Cell] = []
    for corpus in CORPUS_LANG:
        for arm in ARMS:
            path = _report_path(reports_dir, corpus, arm)
            if not path.is_file():
                cells.append(Cell(corpus, arm, None, "report not staged"))
                continue
            if not _gold_available(corpus, gold_dir):
                cells.append(Cell(corpus, arm, None, "frozen gold not staged"))
                continue
            cells.append(
                Cell(corpus, arm, score_cell(load_report(path), corpus, arm), None)
            )
    return cells


def _f(value: float) -> str:
    return f"{value:.4f}"


def _ttg(value: int | None) -> str:
    return f"{value:,} wire" if value is not None else "not reached"


def _cell_by(cells: Sequence[Cell], corpus: str, arm: str) -> Cell:
    for cell in cells:
        if cell.corpus == corpus and cell.arm == arm:
            return cell
    raise KeyError(f"no cell for {arm} x {corpus}")


def render_language_table(cells: Sequence[Cell]) -> str:
    """The 4-language coverage table, one block per LANGUAGE (never blended),
    bound-labelled, with N. Whole-list recall is not printed (INTERNAL)."""
    out: list[str] = [
        f"## Coverage by language (bound: {BOUND}; N = gold-bearing basis)",
        "",
        "All numbers are one binary scored offline against each corpus's FROZEN "
        "gold. Whole-list recall is an internal diagnostic and is not reported "
        "here. Head-only@k is the ranked-head claim; coverage@budget and "
        "cost-to-coverage are the delivered-index claims.",
        "",
    ]
    for corpus, language in CORPUS_LANG.items():
        out.append(f"### {language}  (corpus `{corpus}`, N={CORPUS_N[corpus]})")
        out.append("")
        out.append(
            "| Arm | Gold@8k_wire | Gold@32k_wire | head-only@10 | head-only@25 "
            "| reach@80 | cost-to-coverage (median TtG@80) |"
        )
        out.append("|---|---|---|---|---|---|---|")
        for arm in ARMS:
            cell = _cell_by(cells, corpus, arm)
            if cell.score is None:
                out.append(f"| {arm} | _PENDING ({cell.pending_reason})_ | | | | | |")
                continue
            s = cell.score
            g8 = _f(s.gold_at_8k)
            g32 = _f(s.gold_at_32k)
            ttg = _ttg(s.ttg80_median_wire)
            if arm == NATIVE_FLOOR:
                # The span comparator IS wire-priced (coverage@budget + TtG), but
                # its head-only@k is not comparable to a symbol arm's, so it is
                # omitted; its reach@80 shown here is the UNBOUNDED whole-list
                # reach. (Basis + the span/symbol non-comparability: footnote ².)
                out.append(
                    f"| {arm} | {g8} | {g32} | — ² | — ² "
                    f"| {_f(s.reach_at_80)} ² | {ttg} |"
                )
                continue
            h10 = _f(s.head_at_10)
            if SUPERIORITY_CLAIMABLE.get((corpus, "head_only_at_10")) is False:
                h10 += " ¹"
            out.append(
                f"| {arm} | {g8} | {g32} | {h10} "
                f"| {_f(s.head_at_25)} | {_f(s.reach_at_80)} | {ttg} |"
            )
        out.append("")
    if any(
        SUPERIORITY_CLAIMABLE.get((c, "head_only_at_10")) is False for c in CORPUS_LANG
    ):
        out.append(
            "¹ head-only@10 is NOT superiority-claimable on this corpus "
            "(p=0.125); the claimable head-only superiority is @25 only."
        )
    if any(cell.arm == NATIVE_FLOOR and cell.score is not None for cell in cells):
        out.append(
            "² native_floor (rg + targeted reads) delivers SPANS, not symbols. A "
            "span is read content, so its wire price is its source-text token "
            "count under the SAME shared tokenizer as the curated wire path "
            "(wire == read for spans, B5 §5); coverage@budget and cost-to-"
            "coverage are therefore genuine wire-priced floor values, never a "
            "measured zero. head-only@k is omitted because a span head and a "
            "symbol head are not comparable in one head-only row; the reach@80 "
            "shown for the floor is the UNBOUNDED whole-list reach."
        )
    out.append("")
    return "\n".join(out)


def render_regression_witness(reports_dir: Path) -> str:
    """The 2.1.0->2.3.18 stability witness: the EXACT-to-4dp V1 replay for every
    ts40/py cell the V1 fixture pins, plus the lost-baseline disclosure."""
    out: list[str] = [
        "## Regression witness vs V1 (2.1.0 -> 2.3.18)",
        "",
        "The V1 per-instance baseline reports were destroyed by the shared-OUT "
        "copy-back, so a paired bootstrap vs V1 is not computable. The witness "
        "is the EXACT-to-4dp replay against the pinned V1 reference numbers "
        "(`acceptance.check_arm`) -- strictly stronger than a bootstrap CI: the "
        "deltas ARE zero, not merely bounded below the floor.",
        "",
    ]
    any_cell = False
    for corpus in ("ts40", "py_nosphinx"):
        for arm in ("shipped_treatment", "levers_off_ablation"):
            path = _report_path(reports_dir, corpus, arm)
            if not path.is_file():
                out.append(f"- {arm} x {corpus}: _PENDING (report not staged)_")
                continue
            checks = check_report_file(path, corpus, arm)
            reproduced = all(c.ok for c in checks)
            worst = max((abs(c.delta_pp) for c in checks), default=0.0)
            verdict = "HELD (exact-to-4dp replay)" if reproduced else "MISMATCH"
            out.append(
                f"- {arm} x {corpus}: {verdict} "
                f"(max |Δ| = {worst:.2f}pp over {len(checks)} locked metrics)"
            )
            any_cell = True
    if not any_cell:
        out.append("_No ts40/py cells staged yet._")
    out.append("")
    return "\n".join(out)


def render_lever_effect(reports_dir: Path) -> str:
    """The one paired-bootstrap that IS computable: shipped_treatment minus
    levers_off_ablation, both present on the same lease. This is the lever
    effect, NOT a comparison to V1."""
    out: list[str] = [
        "## Lever effect (paired bootstrap: treatment − ablation)",
        "",
        "The only paired-bootstrap comparison whose two reports both exist: the "
        "shipped treatment against the levers-off ablation, per corpus. This "
        "measures what the curation levers do on THIS binary; it is not a "
        "comparison to the V1 numbers (that is the exact replay above).",
        "",
    ]
    any_corpus = False
    for corpus in CORPUS_LANG:
        base = _report_path(reports_dir, corpus, "levers_off_ablation")
        cur = _report_path(reports_dir, corpus, "shipped_treatment")
        if not (base.is_file() and cur.is_file()):
            out.append(f"### {CORPUS_LANG[corpus]} (`{corpus}`): _PENDING_")
            out.append("")
            continue
        ids = sorted(load_frozen_gold(corpus))
        verdicts = compare_reports(
            load_report(base), load_report(cur), DEFAULT_METRICS, ids
        )
        out.append(f"### {CORPUS_LANG[corpus]} (`{corpus}`, N={len(ids)})")
        out.append("")
        out.append(render_table(verdicts))
        out.append("")
        any_corpus = True
    if not any_corpus:
        out.append("_No corpus has both arms staged yet._")
        out.append("")
    return "\n".join(out)


def render_gold_distribution(gold_dir: Path) -> str:
    """The thin-keys caveat: symbols-per-instance shape of each tier's FROZEN
    gold. A tier heavy in single-symbol gold is easier than its N implies."""
    out: list[str] = [
        "## Gold-symbol distribution (thin-keys caveat)",
        "",
        "Computed from each tier's FROZEN gold (`gold` dict, symbols per "
        "instance). Thin keys are instances whose gold is exactly one symbol -- "
        "a tier heavy in thin keys is an easier target than its N alone shows.",
        "",
        "| Language | corpus | N | thin keys (=1 symbol) | median symbols/instance | max symbols/instance |",
        "|---|---|---|---|---|---|",
    ]
    for corpus, language in CORPUS_LANG.items():
        path = _resolve_gold_path(corpus, gold_dir)
        if path is None:
            out.append(
                f"| {language} | `{corpus}` | {CORPUS_N[corpus]} "
                "| _gold not staged_ | | |"
            )
            continue
        dist = gold_distribution(path)
        median = (
            int(dist.median_per_instance)
            if dist.median_per_instance == int(dist.median_per_instance)
            else round(dist.median_per_instance, 1)
        )
        out.append(
            f"| {language} | `{corpus}` | {dist.n} | {dist.thin_keys} "
            f"| {median} | {dist.max_per_instance} |"
        )
    out.append("")
    return "\n".join(out)


def render_provenance() -> str:
    return "\n".join(
        [
            "## Provenance",
            "",
            f"- **One binary, every cell.** eval `noodl-eval` sha256 "
            f"`{ONE_BINARY_SHA}` (features: rust-analysis). Built on lease 1, "
            "sha-verified onto lease 2 -- one binary by construction.",
            "- **Cell leases.** ts40 + py_nosphinx arms and the rust43 frozen "
            "gold: lease `harbor-hermit` (`cbx_cf3818ae73ee`). go34 frozen gold: "
            "reused from run8 (`bf8de741…`, adjudicated). go34 + rust43 arms: "
            "lease `quick-shrimp` (`cbx_165584a56d81`).",
            "- **Harness.** pinned tip `015ab18` (tokens-to-gold origin/main).",
            "- **Frozen-gold protocol.** derived once per corpus (`--reindex`, "
            "stamped), every arm scores set-membership against it; denominators "
            "are the gold-bearing counts (ts40 37 / py 39 / go34 30 / rust43 40).",
            "",
        ]
    )


def render_disclosures() -> str:
    return "\n".join(
        [
            "## Disclosures",
            "",
            "- **go34 zero-gold alarm (CERTIFIED-WITH-DISCLOSURE).** 4 of 34 "
            "instances are zero-gold = 11.8%, above the pre-registered 10% "
            "alarm; all four are new-file-dominated reference patches (50–100% "
            "of touched files created by the patch), for which the reference-"
            "patch proxy has no pre-existing symbols to score. The alarm fired "
            "as designed; ruling `TTG_RECERT_RULING_GO34_ALARM_2026-09-05.md`. "
            "N=30 is the gold-bearing basis.",
            "- **rust43 exclusions (N=40).** 43 instances − 1 errored − 2 "
            "zero-gold. Errored: `astral-sh__ruff-15626` (a publication-authority "
            "source-root race; disclosed, one instance, a separate follow-up). "
            "Zero-gold: `tokio-rs__axum-1730`, `tokio-rs__tokio-4384` "
            "(new-file-dominated). The coreutils indexing fix (workspace-without-"
            "members) took the errored count from 6 to 1 -- the 5 coreutils "
            "instances now derive.",
            "- **levers_off_ablation reproduction witness: LOST, disclosed.** The "
            "run9 baseline reports the ablation's reproduction was to be paired "
            "against were destroyed by a shared-OUT copy-back; levers_off is not "
            "pinned in PIN.toml. The ablation still RAN (its numbers are in the "
            "table); only its vs-V1 reproduction witness is unavailable.",
            "- **Dual witness + drift sidecar: CITED, not re-run.** The eval "
            "source is unchanged since `8d8905250` (the split touched only the "
            "crabbox driver scripts), so the run11c/run12c witnesses are "
            "witnesses of this source: 259 nextest failures = 258 DATABASE_URL "
            "sqlx::test reds (no Postgres on a lease; CI is their gate) + 1 known "
            "hotpath 6770 bind-race flake; 189/189 eval. Drift sidecar: ts40 "
            "37/37, py 39/39 set-match against the frozen anchor.",
            "",
        ]
    )


def build_report_doc(
    reports_dir: str | Path, gold_dir: str | Path | None = None
) -> str:
    """The full published document. `reports_dir` holds `{arm}_{corpus}.json`;
    `gold_dir` holds `frozen_gold_{corpus}.json` (default: the harness gold/)."""
    reports = Path(reports_dir)
    gold = Path(gold_dir) if gold_dir is not None else PKG / "gold"
    cells = collect_cells(reports, gold)
    scored = sum(1 for c in cells if c.score is not None)
    header = "\n".join(
        [
            "# TokensToGold — 2.3.18 re-certification (4-language)",
            "",
            f"_Locked claims language (S7). {scored} of {len(cells)} cells "
            "scored; the rest are PENDING their lease._",
            "",
        ]
    )
    return "\n".join(
        [
            header,
            render_language_table(cells),
            render_gold_distribution(gold),
            render_regression_witness(reports),
            render_lever_effect(reports),
            render_provenance(),
            render_disclosures(),
        ]
    )
