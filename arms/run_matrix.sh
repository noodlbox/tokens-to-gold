#!/usr/bin/env bash
# Run a set of cells. Default is the two headline cells (treatment + A0);
# `--arms all` runs the full 7-arm sweep (Q1 ruling: reproducing the CLAIM
# should be cheap, reproducing the SWEEP should be possible).
#
# `--store` is a ROOT: each FRESH cell runs in its own `<root>/<arm>_<corpus>`
# store and a REUSE cell in the store of the arm it reuses (`ttg.cli
# store-name`). Every cell is stamped against `--build-receipt` (see run_arm.sh).
#
# CONCURRENCY. Cells run `--jobs` store groups at a time (default 2, the width
# witnessed equal to a sequential run; raise it once a wider run is witnessed
# too). `ttg.cli cell-groups` owns the grouping: cells of one store run in
# order, the FRESH cell first, and different stores never share anything: the
# engine scopes its repository cache to each store's NOODLBOX_DATA_DIR
# (noodlbox-app #2129, EVAL-CLONE-RACE). `--jobs 1` runs every cell in turn.
set -euo pipefail

ARMS="default"; CORPORA="ts40,py_nosphinx"; BINARY=""; CORPUS_DIR=""; STORE=""; OUTDIR=""
BUILD_RECEIPT=""; RECEIPT_VERDICT=""; BUILD_COMMIT=""; JOBS=2
while [ $# -gt 0 ]; do
  case "$1" in
    --arms) ARMS="$2"; shift 2 ;;
    --corpora) CORPORA="$2"; shift 2 ;;
    --binary) BINARY="$2"; shift 2 ;;
    --corpus-dir) CORPUS_DIR="$2"; shift 2 ;;
    --store) STORE="$2"; shift 2 ;;
    --outdir) OUTDIR="$2"; shift 2 ;;
    --build-receipt) BUILD_RECEIPT="$2"; shift 2 ;;
    --receipt-verdict) RECEIPT_VERDICT="$2"; shift 2 ;;
    --build-commit) BUILD_COMMIT="$2"; shift 2 ;;
    --jobs) JOBS="$2"; shift 2 ;;
    *) echo "run_matrix: unknown argument '$1'" >&2; exit 2 ;;
  esac
done
# An empty --store root would place cell stores at `/<arm>_<corpus>`: refuse.
for required in BINARY CORPUS_DIR STORE OUTDIR BUILD_RECEIPT RECEIPT_VERDICT BUILD_COMMIT; do
  if [ -z "${!required}" ]; then
    echo "run_matrix: --$(echo "$required" | tr 'A-Z_' 'a-z-') is required" >&2; exit 2
  fi
done
[[ "$JOBS" =~ ^[1-9][0-9]*$ ]] || { echo "run_matrix: --jobs must be a positive integer, got '$JOBS'" >&2; exit 2; }
PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# One line per store group (an unknown arm or corpus fails here, before any cell).
GROUPS_LIST="$(cd "$PKG" && python3 -m ttg.cli cell-groups --arms "$ARMS" --corpora "$CORPORA")"

mkdir -p "$OUTDIR"
RESULTS="$(mktemp "$OUTDIR/.matrix-results.XXXXXX")"
trap 'rm -f "$RESULTS"' EXIT
export RUN_MATRIX_BINARY="$BINARY" RUN_MATRIX_CORPUS_DIR="$CORPUS_DIR" RUN_MATRIX_STORE="$STORE" \
  RUN_MATRIX_OUTDIR="$OUTDIR" RUN_MATRIX_BUILD_RECEIPT="$BUILD_RECEIPT" \
  RUN_MATRIX_RECEIPT_VERDICT="$RECEIPT_VERDICT" RUN_MATRIX_BUILD_COMMIT="$BUILD_COMMIT" \
  RUN_MATRIX_RESULTS="$RESULTS"
# A cell's failure is recorded in $RESULTS and counted below; a group runner
# itself exits 0, so a non-zero status here is a runner that died outside its
# cells, and every cell must have left exactly one result line.
if ! printf '%s\n' "$GROUPS_LIST" | xargs -P "$JOBS" -L 1 "$PKG/arms/run_cell_group.sh"; then
  echo "run_matrix: a cell group runner failed outside its cells" >&2
  exit 1
fi

EXPECTED="$(printf '%s\n' "$GROUPS_LIST" | awk '{ n += NF - 2 } END { print n + 0 }')"
TOTAL="$(wc -l < "$RESULTS" | tr -d ' ')"
[ "$TOTAL" -eq "$EXPECTED" ] || { echo "run_matrix: $TOTAL cell results for $EXPECTED cells" >&2; exit 1; }
FAILED="$(awk '$1 == "FAILED" { n++ } END { print n + 0 }' "$RESULTS")"
echo "matrix: ${TOTAL} cells, ${FAILED} failed"
[ "$FAILED" -eq 0 ]
