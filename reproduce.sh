#!/usr/bin/env bash
# tokens-to-gold — the one command.
#
#   ./reproduce.sh --binary <noodl-eval> --corpus-dir <dir> --store <dir>
#   ./reproduce.sh --score-only --report-dir <dir>
#
# Stages: verify -> preflight -> (derive) -> run -> score -> report.
# Default gold source is the SHIPPED frozen gold; `--rederive-gold` re-derives
# it from the released binary and asserts TIER-1 identity (slow, opt-in).
#
# WHICH BINARY TO BUILD (two, and they are not interchangeable)
#
#   1. CERTIFICATION build -- default features:
#          cargo build --release -p noodlbox-eval
#      `noodlbox-eval` defaults to `rust-analysis`, mirroring the shipped
#      product (`nbx` default = ["rust-analysis"]). This is the binary whose
#      numbers describe the config users actually run, and the ONLY binary that
#      can carry a Rust corpus: without the feature, .rs files are dropped at
#      discovery and rust43 derives an all-empty gold that reads as a valid
#      0-coverage result.
#
#   2. REGRESSION SIDECAR build -- explicitly feature-stripped:
#          cargo build --release -p noodlbox-eval --no-default-features
#      Reproduces the Aug-20 anchor's rust-OFF configuration for ts40 /
#      py_nosphinx ONLY, and only when the provisioning manifest's
#      `rs_file_count` says it is needed (if every checkout is 0, the two builds
#      are discovery-equivalent and the certification build carries the
#      regression numbers too). Its numbers are the Aug-20-comparable
#      REGRESSION numbers; the certification build's are the AS-SHIPPED
#      numbers. They are reported separately and never merged.
#
# The preflight stage below refuses the mismatch (a Rust corpus on a sidecar
# build), so picking the wrong one is an error, not a silent bad number.
set -euo pipefail

ARMS="default"; CORPORA="ts40,py_nosphinx"; BINARY=""; CORPUS_DIR=""
STORE=""; OUTDIR="./out"; REDERIVE=0; SCORE_ONLY=0; REPORT_DIR=""
ARM="shipped_treatment"
while [ $# -gt 0 ]; do
  case "$1" in
    --arms) ARMS="$2"; shift 2 ;;
    --corpus|--corpora) CORPORA="$2"; shift 2 ;;
    --binary) BINARY="$2"; shift 2 ;;
    --corpus-dir) CORPUS_DIR="$2"; shift 2 ;;
    --store) STORE="$2"; shift 2 ;;
    --outdir) OUTDIR="$2"; shift 2 ;;
    --rederive-gold) REDERIVE=1; shift ;;
    --from-frozen-gold) REDERIVE=0; shift ;;
    --score-only) SCORE_ONLY=1; shift ;;
    --arm) ARM="$2"; shift 2 ;;
    --report-dir) REPORT_DIR="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "reproduce: unknown argument '$1'" >&2; exit 2 ;;
  esac
done
[ "$CORPORA" = "all" ] && CORPORA="ts40,py_nosphinx"
PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$PKG"
CORPUS_LIST="${CORPORA//,/ }"

echo "== stage 0/5: resolve every (arm, corpus) cell =="
# Before ANY stage: an arm whose flags depend on per-corpus data (every
# waterfill / per-file-caps cell derives its budget from a corpus base_20k)
# would otherwise fail in run_matrix after provisioning, derivation and the
# sidecar. Refuse at t=0 with the exact error instead.
python3 -m ttg.cli check-arms --arms "$ARMS" --corpora "$CORPORA"

echo "== stage 1/5: verify shipped frozen gold =="
python3 -m ttg.cli verify-gold

if [ "$SCORE_ONLY" -eq 1 ]; then
  [ -n "$REPORT_DIR" ] || { echo "--score-only needs --report-dir" >&2; exit 2; }
  echo; echo "== stages 2-4 skipped (--score-only) =="
else
  [ -n "$BINARY" ] && [ -n "$CORPUS_DIR" ] && [ -n "$STORE" ] || {
    echo "reproduce: --binary, --corpus-dir and --store are required" >&2; exit 2; }
  if [ "$REDERIVE" -eq 1 ]; then
    echo; echo "== stage 2/5: re-derive gold (L1, slow) =="
    # U1 first: a derivation on a binary that cannot analyze the corpus is
    # exactly how an all-empty gold gets frozen.
    python3 -m ttg.cli preflight --binary "$BINARY" --corpora "$CORPORA" --arms "$ARMS"
    for corpus in $CORPUS_LIST; do
      ttg/derive_gold.sh --corpus "$corpus" --binary "$BINARY" \
        --corpus-jsonl "$CORPUS_DIR/${corpus}.jsonl" --store "$STORE" \
        --outdir "$OUTDIR/gold"
    done
  else
    echo; echo "== stage 2/5: using SHIPPED frozen gold (default) =="
    echo "   (run with --rederive-gold to re-derive it from the released binary)"
  fi
  echo; echo "== stage 2b/5: U1 preflight (refuse a corpus this binary cannot analyze) =="
  python3 -m ttg.cli preflight --binary "$BINARY" --corpora "$CORPORA" --arms "$ARMS"

  echo; echo "== stage 3/5: run arms (L3) =="
  arms/run_matrix.sh --arms "$ARMS" --corpora "$CORPORA" --binary "$BINARY" \
    --corpus-dir "$CORPUS_DIR" --store "$STORE" --outdir "$OUTDIR/reports"
  REPORT_DIR="$OUTDIR/reports"
fi

echo; echo "== stage 4/5: score (L4) =="
RC=0
for corpus in $CORPUS_LIST; do
  # Exact selection, never a glob: reports are named `<arm>_<corpus>.json` by
  # run_matrix.sh, and a glob would happily score one arm's report against
  # another arm's reference numbers.
  report="$REPORT_DIR/${ARM}_${corpus}.json"
  if [ ! -e "$report" ]; then
    echo "--- missing: $(basename "$report") ---"
    RC=1
    continue
  fi
  echo "--- $(basename "$report") ---"
  python3 -m ttg.cli score --report "$report" --corpus "$corpus" --arm "$ARM" || RC=1
  echo
done

echo "== stage 5/5: report =="
if [ "$RC" -eq 0 ]; then
  echo "  ALL GATES PASS (G1 acceptance vs the pinned measurer fixture + G2 curve parity)"
else
  echo "  GATE FAILURE — see the per-report output above"
fi
exit "$RC"
