#!/usr/bin/env bash
# Run a set of cells. Default is the two headline cells (treatment + A0);
# `--arms all` runs the full 7-arm sweep (Q1 ruling: reproducing the CLAIM
# should be cheap, reproducing the SWEEP should be possible).
#
# `--store` is a ROOT: each FRESH cell runs in its own `<root>/<arm>_<corpus>`
# store and a REUSE cell in the store of the arm it reuses (`ttg.cli
# store-name`). Every cell is stamped against `--build-receipt` (see run_arm.sh).
set -euo pipefail

ARMS="default"; CORPORA="ts40,py_nosphinx"; BINARY=""; CORPUS_DIR=""; STORE=""; OUTDIR=""
BUILD_RECEIPT=""; BUILD_COMMIT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --arms) ARMS="$2"; shift 2 ;;
    --corpora) CORPORA="$2"; shift 2 ;;
    --binary) BINARY="$2"; shift 2 ;;
    --corpus-dir) CORPUS_DIR="$2"; shift 2 ;;
    --store) STORE="$2"; shift 2 ;;
    --outdir) OUTDIR="$2"; shift 2 ;;
    --build-receipt) BUILD_RECEIPT="$2"; shift 2 ;;
    --build-commit) BUILD_COMMIT="$2"; shift 2 ;;
    *) echo "run_matrix: unknown argument '$1'" >&2; exit 2 ;;
  esac
done
# An empty --store root would place cell stores at `/<arm>_<corpus>`: refuse.
for required in BINARY CORPUS_DIR STORE OUTDIR BUILD_RECEIPT BUILD_COMMIT; do
  if [ -z "${!required}" ]; then
    echo "run_matrix: --$(echo "$required" | tr 'A-Z_' 'a-z-') is required" >&2; exit 2
  fi
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
    if ! cell_name="$(cd "$PKG" && python3 -m ttg.cli store-name --arm "$arm" --corpus "$corpus")"; then
      FAILED=$((FAILED+1))
      echo "  cell FAILED: ${arm} x ${corpus} (no store for this arm)"
      continue
    fi
    if ! "$PKG/arms/run_arm.sh" \
        --arm "$arm" --corpus "$corpus" --binary "$BINARY" \
        --corpus-jsonl "$CORPUS_DIR/${corpus}.jsonl" \
        --store "$STORE/$cell_name" --out "$OUTDIR/${arm}_${corpus}.json" \
        --build-receipt "$BUILD_RECEIPT" --build-commit "$BUILD_COMMIT"; then
      FAILED=$((FAILED+1))
      echo "  cell FAILED: ${arm} x ${corpus}"
    fi
  done
done
echo "matrix: ${TOTAL} cells, ${FAILED} failed"
[ "$FAILED" -eq 0 ]
