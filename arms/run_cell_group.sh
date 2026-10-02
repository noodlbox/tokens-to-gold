#!/usr/bin/env bash
# Run the cells of ONE store group in order (run_matrix.sh's worker; one line of
# `ttg.cli cell-groups`): <store> <corpus> <arm>...
#
# Cells of one group share a store, so they never overlap; run_matrix.sh runs
# several groups at once. The run's common settings arrive in the environment
# (RUN_MATRIX_*), so an argument line carries only the group. Each cell's
# outcome is one line appended to $RUN_MATRIX_RESULTS: `OK <arm> <corpus>` or
# `FAILED <arm> <corpus>`.
set -euo pipefail

store="${1:?usage: run_cell_group.sh <store> <corpus> <arm>...}"
corpus="${2:?usage: run_cell_group.sh <store> <corpus> <arm>...}"
shift 2
PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

for arm in "$@"; do
  echo "=== cell: ${arm} x ${corpus} (store ${store}) ==="
  if "$PKG/arms/run_arm.sh" \
      --arm "$arm" --corpus "$corpus" --binary "$RUN_MATRIX_BINARY" \
      --corpus-jsonl "$RUN_MATRIX_CORPUS_DIR/${corpus}.jsonl" \
      --store "$RUN_MATRIX_STORE/$store" --out "$RUN_MATRIX_OUTDIR/${arm}_${corpus}.json" \
      --build-receipt "$RUN_MATRIX_BUILD_RECEIPT" --receipt-verdict "$RUN_MATRIX_RECEIPT_VERDICT" \
      --build-commit "$RUN_MATRIX_BUILD_COMMIT"; then
    echo "OK ${arm} ${corpus}" >> "$RUN_MATRIX_RESULTS"
  else
    echo "FAILED ${arm} ${corpus}" >> "$RUN_MATRIX_RESULTS"
    echo "  cell FAILED: ${arm} x ${corpus}"
  fi
done
