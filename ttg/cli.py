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

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ArmError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
