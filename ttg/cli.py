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

    args = parser.parse_args(argv)
    try:
        return int(args.func(args))
    except ArmError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
