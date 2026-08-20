#!/usr/bin/env bash
# Run a set of cells. Default is the two headline cells (treatment + A0);
# `--arms all` runs the full 7-arm sweep (Q1 ruling: reproducing the CLAIM
# should be cheap, reproducing the SWEEP should be possible).
set -euo pipefail

ARMS="default"; CORPORA="ts40,py_nosphinx"; BINARY=""; CORPUS_DIR=""; STORE=""; OUTDIR=""
while [ $# -gt 0 ]; do
  case "$1" in
    --arms) ARMS="$2"; shift 2 ;;
    --corpora) CORPORA="$2"; shift 2 ;;
    --binary) BINARY="$2"; shift 2 ;;
    --corpus-dir) CORPUS_DIR="$2"; shift 2 ;;
    --store) STORE="$2"; shift 2 ;;
    --outdir) OUTDIR="$2"; shift 2 ;;
    *) echo "run_matrix: unknown argument '$1'" >&2; exit 2 ;;
  esac
done
PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

case "$ARMS" in
  default) ARM_LIST="wf_b3 a0_off" ;;
  all)     ARM_LIST="a0_off wf_b1 wf_b2 wf_b3 pfc_b1 pfc_b2 pfc_b3" ;;
  *)       ARM_LIST="${ARMS//,/ }" ;;
esac
CORPUS_LIST="${CORPORA//,/ }"

TOTAL=0; FAILED=0
for corpus in $CORPUS_LIST; do
  for arm in $ARM_LIST; do
    TOTAL=$((TOTAL+1))
    echo "=== cell ${TOTAL}: ${arm} x ${corpus} ==="
    if ! "$PKG/arms/run_arm.sh" \
        --arm "$arm" --corpus "$corpus" --binary "$BINARY" \
        --corpus-jsonl "$CORPUS_DIR/${corpus}.jsonl" \
        --store "$STORE" --out "$OUTDIR/${arm}_${corpus}.json"; then
      FAILED=$((FAILED+1))
      echo "  cell FAILED: ${arm} x ${corpus}"
    fi
  done
done
echo "matrix: ${TOTAL} cells, ${FAILED} failed"
[ "$FAILED" -eq 0 ]
