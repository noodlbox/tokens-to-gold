#!/usr/bin/env bash
# Run a set of cells. Default is the two headline cells (treatment + A0);
# `--arms all` runs the full 7-arm sweep (Q1 ruling: reproducing the CLAIM
# should be cheap, reproducing the SWEEP should be possible).
#
# `--store` is a ROOT: each FRESH cell runs in its own `<root>/<arm>_<corpus>`
# store and a REUSE cell in the store of the arm it reuses (`ttg.cli
# cell-groups`). Every cell is stamped against `--build-receipt` (see run_arm.sh).
#
# CONCURRENCY. Cells run `--jobs` store groups at a time (default 2). `ttg.cli
# cell-groups` owns the grouping: cells of one store run in order, the FRESH cell
# first; groups of different stores share only the engine's locked repository
# mirrors and the host. That is safe only on an engine that scopes its
# repository cache to each store's NOODLBOX_DATA_DIR (noodlbox-app #2129,
# EVAL-CLONE-RACE), so `--jobs` above 1 is refused unless the receipt verdict
# shows that build carries it (`ttg.cli check-concurrency`). Every cell's
# manifest stamps the width it ran at; wall times compare only at equal width.
# `--jobs 1` runs every cell in turn. The default is the width witnessed equal to
# a sequential run (noodlbox-app #2126: go34, two FRESH cells, rows identical).
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

# Before any cell: the width must be safe on this build, and the arm and corpus
# lists must name known, distinct cells.
(cd "$PKG" && python3 -m ttg.cli check-concurrency --jobs "$JOBS" \
  --build-receipt "$BUILD_RECEIPT" --receipt-verdict "$RECEIPT_VERDICT")
GROUPS_LIST="$(cd "$PKG" && python3 -m ttg.cli cell-groups --arms "$ARMS" --corpora "$CORPORA")"
EXPECTED="$(awk '{ n += NF - 2 } END { print n + 0 }' <<< "$GROUPS_LIST")"

mkdir -p "$OUTDIR"
RESULTS="$(mktemp "$OUTDIR/.matrix-results.XXXXXX")"
trap 'rm -f "$RESULTS"' EXIT
# xargs runs in its own process group (set -m), so a runner that dies outside its
# cells, which makes GNU xargs return without waiting for the other runners, can
# take the whole run down with it instead of leaving engines running.
set -m
xargs -P "$JOBS" -L 1 "$PKG/arms/run_cell_group.sh" \
  --binary "$BINARY" --corpus-dir "$CORPUS_DIR" --store-root "$STORE" --outdir "$OUTDIR" \
  --build-receipt "$BUILD_RECEIPT" --receipt-verdict "$RECEIPT_VERDICT" \
  --build-commit "$BUILD_COMMIT" --concurrency "$JOBS" --results "$RESULTS" -- \
  <<< "$GROUPS_LIST" &
runners=$!
set +m
# A cell's failure is recorded in $RESULTS; a group runner itself exits 0, so a
# non-zero status here is a runner that died outside its cells.
if ! wait "$runners"; then
  kill -TERM -- "-$runners" 2> /dev/null || true
  wait "$runners" 2> /dev/null || true
  echo "run_matrix: a cell group runner failed outside its cells; the run was stopped" >&2
  exit 1
fi

TOTAL="$(wc -l < "$RESULTS" | tr -d ' ')"
[ "$TOTAL" -eq "$EXPECTED" ] || { echo "run_matrix: $TOTAL cell results for $EXPECTED cells" >&2; exit 1; }
FAILED="$(awk '$1 == "FAILED" { n++ } END { print n + 0 }' "$RESULTS")"
echo "matrix: ${TOTAL} cells, ${FAILED} failed"
[ "$FAILED" -eq 0 ]
