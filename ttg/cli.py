"""The harness entry point. `reproduce.sh` is a thin wrapper over this.

Subcommands:
  flags       emit one cell's COMPLETE flag list (the single source of truth
              the shell runner consumes -- the runner never builds flags itself)
  verify-gold check the shipped frozen gold against its pinned digests
  score       roll a report up under BOTH bases, run the G2 curve parity, and
              check reproduction against the measurer-owned numbers
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from arms.arm_matrix import CORPORA, DEFAULT_ARMS, SWEEP_ARMS, ArmError, flags_for
from ttg.acceptance import check_report_file, load_fixture, render_checks
from ttg.curve_recompute import curve_parity_findings
from ttg.acceptance import load_frozen_gold
from ttg.own_repo import OWN_REPO_ARMS, OwnRepoError, fetch_pr, own_repo_flags
from ttg.derive_checks import drift_report, render_drift, zero_gold_check
from ttg.regression import DEFAULT_METRICS, compare_reports, render_table
from ttg.provision import (
    build_manifest,
    ts_py_discovery_equivalent,
    write_errors,
    write_manifest,
)
from ttg.report_io import load_report
from ttg.rollup import rollup

PKG = Path(__file__).resolve().parent.parent

# Q3 RULING: rel2-measurer OWNS the reference numbers. The harness REPRODUCES
# them and must not independently re-derive them; a mismatch is a harness
# defect, not a new measurement. The authoritative record is the acceptance
# fixture — there is no second copy in this file.


def _resolve_arms(spec: str) -> list[str]:
    if spec == "default":
        return list(DEFAULT_ARMS)
    if spec == "all":
        return list(SWEEP_ARMS)
    return [a.strip() for a in spec.split(",") if a.strip()]


def cmd_flags(args: argparse.Namespace) -> int:
    print(" ".join(flags_for(args.arm, args.corpus)))
    return 0


def cmd_verify_gold(args: argparse.Namespace) -> int:
    sums = (PKG / "gold" / "SHA256SUMS").read_text().split()
    pinned = dict(zip(sums[1::2], sums[0::2]))
    ok = True
    for name, want in pinned.items():
        got = hashlib.sha256((PKG / "gold" / name).read_bytes()).hexdigest()
        status = "OK" if got == want else "MISMATCH"
        ok &= got == want
        print(f"  {status:8s} {name}  {got[:16]}")
    return 0 if ok else 1


def cmd_accept(args: argparse.Namespace) -> int:
    """The B3 ACCEPTANCE GATE: exact-to-4-decimals on replay."""
    checks = check_report_file(args.report, args.corpus, args.arm, replay=not args.fresh)
    print(render_checks(args.corpus, args.arm, checks))
    ok = all(check.ok for check in checks)
    mode = "fresh (noise floor)" if args.fresh else "replay (EXACT to 4dp)"
    print(f"    -> {'ACCEPTED' if ok else 'REJECTED'}  [{mode}]")
    return 0 if ok else 1


def cmd_score(args: argparse.Namespace) -> int:
    report = load_report(args.report)
    roll = rollup(report, frozen_instance_ids=list(load_frozen_gold(args.corpus)))
    print(roll.render(args.corpus))
    print()

    findings = curve_parity_findings(report)
    if findings:
        print(f"  G2 curve parity : FAIL ({len(findings)} findings)")
        for finding in findings[:10]:
            print(f"      {finding}")
    else:
        print("  G2 curve parity : PASS (offline recompute reproduces the binary)")

    print()
    print(f"  G1 reproduction : arm={args.arm} (measurer-owned; harness reproduces)")
    acceptance = check_report_file(args.report, args.corpus, args.arm)
    print(render_checks(args.corpus, args.arm, acceptance))
    reproduced = all(check.ok for check in acceptance)
    return 0 if reproduced and not findings else 1


def cmd_from_pr(args: argparse.Namespace) -> int:
    """B7: build a one-instance own-repo corpus from a public merged PR."""
    try:
        inst = fetch_pr(args.repo, args.pr)
    except OwnRepoError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    jsonl = out / "instance.jsonl"
    jsonl.write_text(inst.to_jsonl_row() + "\n")
    print(f"wrote {jsonl}  ({inst.instance_id} @ {inst.base_commit[:12]})")
    for note in inst.disclosures:
        print(f"  DISCLOSURE: {note}")
    print()
    print("Next (the freezer path — gold always comes from the versioned pipeline):")
    print(f"  1) derive + freeze YOUR gold (full index of the pre-change checkout):")
    print(f"     ttg/derive_gold.sh --corpus own_repo --binary <noodl-eval> \\")
    print(f"        --corpus-jsonl {jsonl} --store {out}/store --outdir {out}/gold")
    print(f"  2) run the shipped treatment (and optionally the other section-5 arms):")
    for arm in OWN_REPO_ARMS:
        print(f"     # {arm}:")
        print(
            f"     NOODLBOX_DATA_DIR={out}/store <noodl-eval> swe-bench {jsonl} "
            + " ".join(own_repo_flags(arm))
            + f" --timeout 900 -f json > {out}/{arm}.json"
        )
    print(f"  3) score against YOUR frozen gold:")
    print(f"     python3 -m ttg.cli score-own --report {out}/shipped_treatment.json \\")
    print(f"        --gold {out}/gold/frozen_gold_own_repo.json")
    return 0


def cmd_score_own(args: argparse.Namespace) -> int:
    """Score an own-repo report against the user's OWN frozen gold file."""
    doc = json.loads(Path(args.gold).read_text())
    gold = doc.get("gold", doc)
    if not isinstance(gold, dict) or not gold:
        print(f"ERROR: {args.gold}: no gold payload", file=sys.stderr)
        return 2
    report = load_report(args.report)
    roll = rollup(report, frozen_instance_ids=list(gold))
    print(roll.render("own-repo"))
    print()
    findings = curve_parity_findings(report)
    if findings:
        print(f"  G2 curve parity : FAIL ({len(findings)} findings)")
        for finding in findings[:10]:
            print(f"      {finding}")
    else:
        print("  G2 curve parity : PASS (offline recompute reproduces the binary)")
    thin = [iid for iid, syms in gold.items() if len(syms) <= 2]
    if thin:
        print(
            f"  THIN-GOLD GUARD : {len(thin)}/{len(gold)} instance(s) carry <=2 gold "
            "symbols — per-instance coverage is largely binary (0/1); run more "
            "PRs before reading a trend"
        )
    return 1 if findings else 0


def _gold_map(path: str) -> dict[str, list[str]]:
    doc = json.loads(Path(path).read_text())
    gold = doc.get("gold", doc)
    return {str(k): [str(x) for x in v] for k, v in gold.items()}


def cmd_zero_gold(args: argparse.Namespace) -> int:
    """R-P5 NO-GO alarm. Non-zero exit is the point: a tier above the
    pre-registered rate must not proceed to publish on its own."""
    check = zero_gold_check(args.corpus, _gold_map(args.gold), args.total)
    print(check.summary())
    return 1 if check.alarm else 0


def cmd_drift(args: argparse.Namespace) -> int:
    """U2/R-B4 sidecar. Drift is a reported FINDING, so this exits 0 and the
    run continues on the frozen anchor."""
    print(render_drift(drift_report(
        args.corpus, _gold_map(args.frozen), _gold_map(args.rederived))))
    return 0


def cmd_regress(args: argparse.Namespace) -> int:
    """The R12 regression verdict table (HELD / IMPROVED / REGRESSED).

    Paired per-instance deltas between two reports, each verdict decided by the
    bootstrap 95% CI relative to the pre-registered floor and carrying the exact
    paired sign test."""
    baseline = load_report(args.baseline)
    current = load_report(args.current)
    ids = None
    if args.gold:
        ids = sorted(load_frozen_gold(args.gold))
    print(render_table(compare_reports(baseline, current, DEFAULT_METRICS, ids)))
    return 0


def cmd_provision(args: argparse.Namespace) -> int:
    """Provision a corpus's checkouts and emit the PUBLIC manifest (R-P4).

    The manifest is the third-party checkout-set proof and carries the
    `rs_file_count` column that decides R-B2 comparability. Provisioning
    failures are recorded as errored exclusions, never dropped."""
    out = Path(args.out) if args.out else PKG / "corpora" / f"{args.corpus}.manifest.jsonl"
    out.parent.mkdir(parents=True, exist_ok=True)
    result = build_manifest(Path(args.jsonl), Path(args.checkouts))
    write_manifest(result.rows, out)
    print(f"manifest: {out}  rows={len(result.rows)}")

    if result.errors:
        err_out = out.with_suffix(".errors.jsonl")
        write_errors(result.errors, err_out)
        print(f"ERRORED EXCLUSIONS: {len(result.errors)} -> {err_out}")
        for e in result.errors:
            print(f"  errored {e.instance_id}: {e.reason}")

    with_rs = [r for r in result.rows if r.rs_file_count > 0]
    total_rs = sum(r.rs_file_count for r in result.rows)
    print(f"rs_file_count: {total_rs} across {len(with_rs)} checkout(s)")
    if args.corpus in ("ts40", "py_nosphinx"):
        # R-B2: rust ON/OFF is discovery-equivalent for the regression corpora
        # iff no checkout carries a .rs file. Otherwise a --no-default-features
        # sidecar build is ALSO required for the Aug-20-comparable numbers.
        if ts_py_discovery_equivalent(result.rows):
            print("R-B2: EQUIVALENT — no .rs in any checkout; the rust-ON "
                  "certification binary carries the regression numbers.")
        else:
            print("R-B2: NOT EQUIVALENT — .rs present; a --no-default-features "
                  "sidecar build is REQUIRED for ts40/py_nosphinx, reported "
                  "separately from the as-shipped numbers.")
            for r in with_rs:
                print(f"  {r.instance_id}: {r.rs_file_count} .rs")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ttg", description=__doc__)
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_flags = sub.add_parser("flags", help="emit one cell's complete flag list")
    p_flags.add_argument("--arm", required=True)
    p_flags.add_argument("--corpus", required=True, choices=sorted(CORPORA))
    p_flags.set_defaults(func=cmd_flags)

    p_verify = sub.add_parser("verify-gold", help="check frozen gold digests")
    p_verify.set_defaults(func=cmd_verify_gold)

    p_score = sub.add_parser("score", help="roll up + G2 parity + G1 reproduction")
    p_score.add_argument("--report", required=True)
    p_score.add_argument("--corpus", required=True, choices=sorted(CORPORA))
    p_score.add_argument("--arm", default="shipped_treatment")
    p_score.set_defaults(func=cmd_score)

    p_accept = sub.add_parser("accept", help="the B3 acceptance gate")
    p_accept.add_argument("--report", required=True)
    p_accept.add_argument("--corpus", required=True, choices=sorted(CORPORA))
    p_accept.add_argument("--arm", default="shipped_treatment")
    p_accept.add_argument(
        "--fresh", action="store_true",
        help="a fresh --rederive-gold run: allow movement within the noise floor",
    )
    p_accept.set_defaults(func=cmd_accept)

    p_fixture = sub.add_parser("fixture", help="show the pinned reference fixture")
    p_fixture.set_defaults(
        func=lambda a: (print(json.dumps(load_fixture()["provenance"], indent=2)), 0)[1]
    )

    p_frompr = sub.add_parser(
        "from-pr", help="own repo: build a one-instance corpus from a merged PR"
    )
    p_frompr.add_argument("--repo", required=True, help="owner/name (public)")
    p_frompr.add_argument("--pr", required=True, type=int)
    p_frompr.add_argument("--out", required=True)
    p_frompr.set_defaults(func=cmd_from_pr)

    p_scoreown = sub.add_parser(
        "score-own", help="own repo: score a report against YOUR frozen gold"
    )
    p_scoreown.add_argument("--report", required=True)
    p_scoreown.add_argument("--gold", required=True)
    p_scoreown.set_defaults(func=cmd_score_own)

    p_prov = sub.add_parser(
        "provision", help="clone a corpus's checkouts + emit the public manifest"
    )
    p_prov.add_argument("--corpus", required=True)
    p_prov.add_argument("--jsonl", required=True, help="private corpus JSONL")
    p_prov.add_argument("--checkouts", required=True, help="checkout root")
    p_prov.add_argument("--out", help="default: corpora/<corpus>.manifest.jsonl")
    p_prov.set_defaults(func=cmd_provision)

    p_reg = sub.add_parser(
        "regress", help="R12 per-metric HELD/IMPROVED/REGRESSED verdict table"
    )
    p_reg.add_argument("--baseline", required=True, help="Aug-20 anchor report")
    p_reg.add_argument("--current", required=True, help="v2.3.18 report")
    p_reg.add_argument("--gold", help="frozen gold: restrict to the binding basis")
    p_reg.set_defaults(func=cmd_regress)

    p_zg = sub.add_parser(
        "zero-gold", help="R-P5 zero-gold NO-GO alarm for a derived tier"
    )
    p_zg.add_argument("--corpus", required=True)
    p_zg.add_argument("--gold", required=True, help="derived/frozen gold json")
    p_zg.add_argument("--total", type=int, required=True, help="corpus instances")
    p_zg.set_defaults(func=cmd_zero_gold)

    p_drift = sub.add_parser(
        "drift", help="derivation-drift sidecar: SET-MATCH vs the frozen anchor"
    )
    p_drift.add_argument("--corpus", required=True)
    p_drift.add_argument("--frozen", required=True)
    p_drift.add_argument("--rederived", required=True)
    p_drift.set_defaults(func=cmd_drift)

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ArmError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
