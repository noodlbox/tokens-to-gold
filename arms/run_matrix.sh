#!/usr/bin/env bash
# Run a set of cells. Default is the two headline cells (treatment + A0);
# `--arms all` runs the full 7-arm sweep (Q1 ruling: reproducing the CLAIM
# should be cheap, reproducing the SWEEP should be possible).
#
# `--store` is a ROOT: each FRESH cell runs in its own `<root>/<arm>_<corpus>`
# store and a REUSE cell in the store of the arm it reuses (`ttg.cli
# cell-groups`). Every cell is stamped against `--build-receipt` (see run_arm.sh).
#
# CONCURRENCY. Cells run `--jobs` store groups at a time (default
# DEFAULT_CELL_JOBS in arms/arm_matrix.py). `ttg.cli cell-groups` owns the
# grouping: cells of one store run in order, the FRESH cell first; groups of
# different stores share only the engine's locked repository mirrors and the
# host. That is safe only on an engine that scopes its
# repository cache to each store's NOODLBOX_DATA_DIR (noodlbox-app #2129,
# EVAL-CLONE-RACE), so `--jobs` above 1 is refused unless the receipt verdict
# shows that build carries it (`ttg.cli check-concurrency`). Every cell's
# manifest stamps the width it ran at; wall times compare only at equal width.
# `--jobs 1` runs every cell in turn. An interrupt (INT, TERM, HUP) stops every
# runner and engine before the script exits; one still alive 30 s after TERM is
# killed, and named on stderr.
set -euo pipefail

ARMS="default"; CORPORA="ts40,py_nosphinx"; BINARY=""; CORPUS_DIR=""; STORE=""; OUTDIR=""
BUILD_RECEIPT=""; RECEIPT_VERDICT=""; BUILD_COMMIT=""; JOBS=""
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
PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

# Before any cell: the width (the caller's --jobs, else the default) must be safe
# on this build, and the arm and corpus lists must name known, distinct cells.
jobs_args=()
[ -z "$JOBS" ] || jobs_args=(--jobs "$JOBS")
# ${a[@]+"${a[@]}"}: bash before 4.4 (macOS /bin/bash) calls an empty array unbound.
JOBS="$(cd "$PKG" && python3 -m ttg.cli check-concurrency ${jobs_args[@]+"${jobs_args[@]}"} \
  --build-receipt "$BUILD_RECEIPT" --receipt-verdict "$RECEIPT_VERDICT")"
GROUPS_LIST="$(cd "$PKG" && python3 -m ttg.cli cell-groups --arms "$ARMS" --corpora "$CORPORA")"
EXPECTED="$(awk '{ n += NF - 2 } END { print n + 0 }' <<< "$GROUPS_LIST")"

mkdir -p "$OUTDIR"
RESULTS="$(mktemp "$OUTDIR/.matrix-results.XXXXXX")"
trap 'rm -f "$RESULTS"' EXIT
# xargs runs in its own process group (set -m), so the whole run (runners and
# engines) can be stopped together: when a runner dies outside its cells, and
# when this script is interrupted, which no longer reaches that group by itself.
# The group is xargs' pid; the traps hold from before the launch.
runners=""
stop_runners() {
  [ -n "$runners" ] || return 0
  kill -TERM -- "-$runners" 2> /dev/null || return 0
  local waited=0
  while kill -0 -- "-$runners" 2> /dev/null && [ "$waited" -lt 300 ]; do
    sleep 0.1
    waited=$((waited + 1))
  done
  if kill -0 -- "-$runners" 2> /dev/null; then
    echo "run_matrix: still running 30 s after TERM, killed: $(pgrep -g "$runners" | tr '\n' ' ')" >&2
    kill -KILL -- "-$runners" 2> /dev/null || true
  fi
}
trap 'stop_runners; exit 130' INT
trap 'stop_runners; exit 143' TERM
trap 'stop_runners; exit 129' HUP
set -m
xargs -P "$JOBS" -L 1 "$PKG/arms/run_cell_group.sh" \
  --binary "$BINARY" --corpus-dir "$CORPUS_DIR" --store-root "$STORE" --outdir "$OUTDIR" \
  --build-receipt "$BUILD_RECEIPT" --receipt-verdict "$RECEIPT_VERDICT" \
  --build-commit "$BUILD_COMMIT" --concurrency "$JOBS" --results "$RESULTS" -- \
  <<< "$GROUPS_LIST" &
runners=$!
set +m
# A cell's failure is recorded in $RESULTS; a group runner itself exits 0, so a
# non-zero status here is a runner that died outside its cells. xargs then
# finishes the other runners (123), or, when the runner was killed by a signal
# or exited 255, returns at once (GNU) with the others still running.
if ! wait "$runners"; then
  stop_runners
  echo "run_matrix: a cell group runner failed outside its cells; the run was stopped" >&2
  exit 1
fi

TOTAL="$(wc -l < "$RESULTS" | tr -d ' ')"
[ "$TOTAL" -eq "$EXPECTED" ] || { echo "run_matrix: $TOTAL cell results for $EXPECTED cells" >&2; exit 1; }
FAILED="$(awk '$1 == "FAILED" { n++ } END { print n + 0 }' "$RESULTS")"
echo "matrix: ${TOTAL} cells, ${FAILED} failed"
[ "$FAILED" -eq 0 ]
