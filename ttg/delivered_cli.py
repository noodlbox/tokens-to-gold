"""CLI verbs of the delivered arm (LEDGER B64); registered by `ttg.cli`.

`delivered-run` refuses to start a cell until the build receipt, its git
verdict, both binaries (`nbx`, `noodl-eval`) and the corpus pin all verify.
`delivered-score` prices through the verified `noodl-eval count-tokens`.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from ttg.cell_stamps import (
    load_build_receipt,
    load_receipt_verdict,
    verify_binary_against_receipt,
    verify_corpus,
    verify_nbx_against_receipt,
)
from ttg.delivered_cells import run_corpus
from ttg.delivered_page import render_headline
from ttg.delivered_provenance import account_orgs
from ttg.delivered_report import GrepContract, paired_delta, score_corpus
from ttg.report_io import load_report
from ttg.token_count import EngineTokenCounter

PKG = Path(__file__).resolve().parent.parent


def verified_build(build_dir: Path, commit: str) -> tuple[dict[str, object], GrepContract]:
    """Verify the build directory's receipt, verdict and both binaries; return
    the build stamp every delivered report carries, and the build's #1791 grep
    contract from its verdict."""
    receipt_path = build_dir / "build-receipt.json"
    receipt = load_build_receipt(receipt_path)
    verdict = load_receipt_verdict(build_dir / "receipt-verdict.json", receipt_path, receipt)
    verify_binary_against_receipt(build_dir / "noodl-eval", receipt, commit)
    verify_nbx_against_receipt(build_dir / "nbx", receipt, commit)
    stamp: dict[str, object] = {
        "commit": receipt.commit,
        "nbx_sha256": receipt.nbx_sha256,
        "noodl_eval_sha256": receipt.binary_sha256,
        "cargo_profile": receipt.cargo_profile,
        "cargo_features": receipt.cargo_features,
        "model_lock_sha256": receipt.model_lock_sha256,
        "receipt_verified_against_git": True,
        "commit_date": verdict.commit_date,
        "grep_fix_commit": verdict.grep_fix_commit,
        "grep_one_line_per_hit": verdict.grep_one_line_per_hit,
        "grep_pre_fix_on_newer_commit": verdict.pre_fix_on_newer_commit,
    }
    return stamp, GrepContract(
        one_line_per_hit=verdict.grep_one_line_per_hit,
        pre_fix_on_newer_commit=verdict.pre_fix_on_newer_commit,
    )


class MissingAccountError(RuntimeError):
    """The delivered arm runs as a signed-in agent; without a key every analyze
    of a repository that is not a public Hub package is refused."""


def cmd_delivered_run(args: argparse.Namespace) -> int:
    if not os.environ.get("NOODLBOX_API_KEY"):
        raise MissingAccountError(
            "delivered-run needs NOODLBOX_API_KEY in its environment: the arm measures a "
            "signed-in agent (pass it through `scripts/crabbox/run.sh --secrets NOODLBOX_API_KEY`)"
        )
    build, _ = verified_build(Path(args.build_dir), args.commit)
    jsonl = Path(args.corpus_jsonl)
    corpus_sha = verify_corpus(jsonl, args.corpus, PKG / "corpora" / "jsonl.SHA256SUMS")
    root = Path(args.root)
    stamp = root / "out" / args.corpus / "build.json"
    stamp.parent.mkdir(parents=True, exist_ok=True)
    orgs = account_orgs(os.environ["NOODLBOX_API_KEY"])
    stamp.write_text(
        json.dumps({**build, "corpus_sha256": corpus_sha, "account_orgs": orgs}, indent=1), encoding="utf-8"
    )
    only = frozenset(args.only) if args.only else None
    cells = run_corpus(str(Path(args.build_dir) / "nbx"), root, args.corpus, jsonl, only)
    print(f"delivered-run {args.corpus}: {len(cells)} cells under {root / 'out' / args.corpus}")
    return 0


def cmd_delivered_score(args: argparse.Namespace) -> int:
    build, grep_contract = verified_build(Path(args.build_dir), args.commit)
    counter = EngineTokenCounter(Path(args.build_dir) / "noodl-eval")
    report = score_corpus(Path(args.root) / "out", args.corpus, counter, build, grep_contract)
    Path(args.out).write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(f"delivered report: {args.out}")
    return 0


def cmd_delivered_page(args: argparse.Namespace) -> int:
    print(render_headline([load_report(path) for path in args.reports]))
    return 0


def cmd_delivered_compare(args: argparse.Namespace) -> int:
    base, head = load_report(args.base), load_report(args.head)
    print(json.dumps([paired_delta(base, head, row) for row in args.rows], indent=1))
    return 0


def register(sub: argparse._SubParsersAction) -> None:
    run = sub.add_parser("delivered-run", help="run the delivered arm's cells for one corpus (sequential)")
    for flag in ("--build-dir", "--commit", "--corpus", "--corpus-jsonl", "--root"):
        run.add_argument(flag, required=True)
    run.add_argument("--only", nargs="+", help="run only these instance ids (a smoke; never publishable)")
    run.set_defaults(func=cmd_delivered_run)

    score = sub.add_parser("delivered-score", help="score recorded delivered cells into a report")
    for flag in ("--build-dir", "--commit", "--corpus", "--root", "--out"):
        score.add_argument(flag, required=True)
    score.set_defaults(func=cmd_delivered_score)

    page = sub.add_parser("delivered-page", help="render delivered reports as the headline tables")
    page.add_argument("reports", nargs="+")
    page.set_defaults(func=cmd_delivered_page)

    compare = sub.add_parser("delivered-compare", help="paired head-vs-base delta per delivered row")
    compare.add_argument("--base", required=True)
    compare.add_argument("--head", required=True)
    compare.add_argument("--rows", nargs="+", default=["grep.8000", "grep.32000"])
    compare.set_defaults(func=cmd_delivered_compare)
