#!/usr/bin/env bash
# Run the cells of ONE store group in order: run_matrix.sh's worker, given the
# run's settings as flags and then one line of `ttg.cli cell-groups`:
#
#   run_cell_group.sh --binary B --corpus-dir D --store-root R --outdir O \
#     --build-receipt F --receipt-verdict V --build-commit C --concurrency N \
#     --results FILE -- <store> <corpus> <arm>...
#
# Cells of one group share a store, so they never overlap; run_matrix.sh runs
# several groups at once. Each cell's outcome is one line appended to the
# results file (`OK <arm> <corpus>` or `FAILED <arm> <corpus>`), and every line
# the cells print goes to stderr prefixed with `[<store>]`, so concurrent groups
# stay attributable.
set -euo pipefail

BINARY=""; CORPUS_DIR=""; STORE_ROOT=""; OUTDIR=""; BUILD_RECEIPT=""; RECEIPT_VERDICT=""
BUILD_COMMIT=""; CONCURRENCY=""; RESULTS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --binary) BINARY="$2"; shift 2 ;;
    --corpus-dir) CORPUS_DIR="$2"; shift 2 ;;
    --store-root) STORE_ROOT="$2"; shift 2 ;;
    --outdir) OUTDIR="$2"; shift 2 ;;
    --build-receipt) BUILD_RECEIPT="$2"; shift 2 ;;
    --receipt-verdict) RECEIPT_VERDICT="$2"; shift 2 ;;
    --build-commit) BUILD_COMMIT="$2"; shift 2 ;;
    --concurrency) CONCURRENCY="$2"; shift 2 ;;
    --results) RESULTS="$2"; shift 2 ;;
    --) shift; break ;;
    *) echo "run_cell_group: unknown argument '$1'" >&2; exit 2 ;;
  esac
done
for required in BINARY CORPUS_DIR STORE_ROOT OUTDIR BUILD_RECEIPT RECEIPT_VERDICT BUILD_COMMIT \
    CONCURRENCY RESULTS; do
  if [ -z "${!required}" ]; then
    echo "run_cell_group: --$(echo "$required" | tr 'A-Z_' 'a-z-') is required" >&2; exit 2
  fi
done
store="${1:?run_cell_group: a group line <store> <corpus> <arm>... is required}"
corpus="${2:?run_cell_group: the group line has no corpus}"
shift 2
[ $# -gt 0 ] || { echo "run_cell_group: the group line has no arm" >&2; exit 2; }
PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for arm in "$@"; do
  echo "=== cell: ${arm} x ${corpus} (store ${store}) ===" >&2
  set +e
  "$PKG/arms/run_arm.sh" \
      --arm "$arm" --corpus "$corpus" --binary "$BINARY" \
      --corpus-jsonl "$CORPUS_DIR/${corpus}.jsonl" \
      --store "$STORE_ROOT/$store" --out "$OUTDIR/${arm}_${corpus}.json" \
      --build-receipt "$BUILD_RECEIPT" --receipt-verdict "$RECEIPT_VERDICT" \
      --build-commit "$BUILD_COMMIT" --concurrency "$CONCURRENCY" 2>&1 \
    | awk -v prefix="[$store] " '{ print prefix $0; fflush() }' >&2
  rc=${PIPESTATUS[0]}
  set -e
  if [ "$rc" -eq 0 ]; then
    echo "OK ${arm} ${corpus}" >> "$RESULTS"
  else
    echo "FAILED ${arm} ${corpus}" >> "$RESULTS"
    echo "[$store] cell FAILED: ${arm} x ${corpus}" >&2
  fi
done
