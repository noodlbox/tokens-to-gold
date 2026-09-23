#!/usr/bin/env bash
# Run ONE cell (arm x corpus) of the matrix.
#
# FOOTGUN DEFENCE, LAYER 3: this script NEVER builds its own flags. It asks
# `ttg.cli flags` for them and echoes the COMPLETE invocation into the cell
# manifest, so the recorded provenance carries the actual flags rather than a
# prose claim about what an omitted default used to mean. (The recorded
# M23-P4 manifest asserts "flag absent => Off", which is false post-ceea4ab0c.)
#
# PROVENANCE, LAYER 4 (lane 4F): every stamp lives in `ttg/cell_stamps.py`; this
# script only calls it. Before the engine runs, `ttg.cli cell-preflight` refuses
# a cell whose binary is not the one its build receipt names, or whose receipt
# lacks the verdict `verify-receipt` issued against the engine's git history, whose corpus JSONL differs from its pin, whose
# corpus language the binary cannot analyze, or whose store breaks the arm's
# FRESH/REUSE policy. The engine writes its report to `<out>.partial`; only
# after `ttg.cli cell-stamp` proves the reranker is the report moved into place
# (and a FRESH store marked complete, or a REUSE store's marker given back). The
# receipt and its verdict are copied beside the manifest.
set -euo pipefail

ARM=""; CORPUS=""; BINARY=""; JSONL=""; STORE=""; OUT=""; TIMEOUT="900"
BUILD_RECEIPT=""; RECEIPT_VERDICT=""; BUILD_COMMIT=""
while [ $# -gt 0 ]; do
  case "$1" in
    --arm) ARM="$2"; shift 2 ;;
    --corpus) CORPUS="$2"; shift 2 ;;
    --binary) BINARY="$2"; shift 2 ;;
    --corpus-jsonl) JSONL="$2"; shift 2 ;;
    --store) STORE="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --build-receipt) BUILD_RECEIPT="$2"; shift 2 ;;
    --receipt-verdict) RECEIPT_VERDICT="$2"; shift 2 ;;
    --build-commit) BUILD_COMMIT="$2"; shift 2 ;;
    *) echo "run_arm: unknown argument '$1'" >&2; exit 2 ;;
  esac
done
for required in ARM CORPUS BINARY JSONL STORE OUT BUILD_RECEIPT RECEIPT_VERDICT BUILD_COMMIT; do
  if [ -z "${!required}" ]; then
    echo "run_arm: --$(echo "$required" | tr 'A-Z_' 'a-z-') is required" >&2; exit 2
  fi
done

PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PKG"

# Single source of truth. If this fails (unknown/unavailable arm, or a policy
# with no budget), the cell does NOT run.
FLAGS="$(python3 -m ttg.cli flags --arm "$ARM" --corpus "$CORPUS")"
# Refuse before any work; on success these are the verified manifest lines.
STAMPS="$(python3 -m ttg.cli cell-preflight --arm "$ARM" --corpus "$CORPUS" \
  --corpus-jsonl "$JSONL" --store "$STORE" --binary "$BINARY" \
  --build-receipt "$BUILD_RECEIPT" --receipt-verdict "$RECEIPT_VERDICT" \
  --build-commit "$BUILD_COMMIT")"

MAN="${OUT%.json}.manifest.txt"
LOG="${OUT%.json}.log"
PARTIAL="${OUT}.partial"
mkdir -p "$(dirname "$OUT")"
rm -f "$OUT" "$PARTIAL"
cp "$BUILD_RECEIPT" "${OUT%.json}.build-receipt.json"
cp "$RECEIPT_VERDICT" "${OUT%.json}.receipt-verdict.json"
{
  echo "# cell manifest — ${ARM} x ${CORPUS}"
  echo "arm:          $ARM"
  echo "corpus:       $CORPUS"
  echo "binary:       $BINARY"
  echo "corpus_jsonl: $JSONL"
  echo "store:        $STORE"
  echo "$STAMPS"
  echo "started:      $(date '+%F %T')"
  echo "# THE FULL INVOCATION — flags are recorded, never inferred from defaults:"
  echo "cmd: NOODLBOX_DATA_DIR=$STORE $BINARY swe-bench $JSONL $FLAGS --timeout $TIMEOUT -f json"
} | tee "$MAN"

set +e
# shellcheck disable=SC2086  # FLAGS is a deliberate word-split flag list
NOODLBOX_DATA_DIR="$STORE" "$BINARY" swe-bench "$JSONL" \
  $FLAGS --timeout "$TIMEOUT" -f json > "$PARTIAL" 2> "$LOG"
RC=$?
set -e
{
  echo "finished:     $(date '+%F %T')"
  echo "exit code:    $RC"
  echo "report bytes: $(wc -c < "$PARTIAL" 2>/dev/null || echo 0)"
} | tee -a "$MAN"
[ "$RC" -eq 0 ] || exit "$RC"
# Publishes $OUT only if every post-run stamp passes; otherwise $OUT stays absent.
python3 -m ttg.cli cell-stamp --arm "$ARM" --corpus "$CORPUS" --corpus-jsonl "$JSONL" \
  --store "$STORE" --build-receipt "$BUILD_RECEIPT" --report "$OUT" | tee -a "$MAN"
