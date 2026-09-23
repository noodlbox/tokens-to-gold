#!/usr/bin/env bash
# Run ONE cell (arm x corpus) of the matrix.
#
# FOOTGUN DEFENCE, LAYER 3: this script NEVER builds its own flags. It asks
# `ttg.cli flags` for them and echoes the COMPLETE invocation into the cell
# manifest, so the recorded provenance carries the actual flags rather than a
# prose claim about what an omitted default used to mean. (The recorded
# M23-P4 manifest asserts "flag absent => Off", which is false post-ceea4ab0c.)
#
# PROVENANCE, LAYER 4 (lane 4F): the eval report names neither the engine nor
# the reranker, and nothing checks the corpus bytes or the store. Before the
# run `ttg.cli cell-preflight` refuses a cell whose build commit is not a full
# sha, whose corpus JSONL differs from its pin, or whose store breaks the arm's
# FRESH/REUSE mode; after it `ttg.cli cell-stamp` proves the reranker installed
# in the store is the one the engine's model.lock pins. Both write their
# verified values into the manifest, and either failing fails the cell.
set -euo pipefail

ARM=""; CORPUS=""; BINARY=""; JSONL=""; STORE=""; OUT=""; TIMEOUT="900"
BUILD_COMMIT=""; MODEL_LOCK=""
while [ $# -gt 0 ]; do
  case "$1" in
    --arm) ARM="$2"; shift 2 ;;
    --corpus) CORPUS="$2"; shift 2 ;;
    --binary) BINARY="$2"; shift 2 ;;
    --corpus-jsonl) JSONL="$2"; shift 2 ;;
    --store) STORE="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    --build-commit) BUILD_COMMIT="$2"; shift 2 ;;
    --model-lock) MODEL_LOCK="$2"; shift 2 ;;
    *) echo "run_arm: unknown argument '$1'" >&2; exit 2 ;;
  esac
done
for required in ARM CORPUS BINARY JSONL STORE OUT BUILD_COMMIT MODEL_LOCK; do
  if [ -z "${!required}" ]; then
    flag="${required,,}"; echo "run_arm: --${flag//_/-} is required" >&2; exit 2
  fi
done

PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PKG"

# Single source of truth. If this fails (unknown/unavailable arm, or a policy
# with no budget), the cell does NOT run.
FLAGS="$(python3 -m ttg.cli flags --arm "$ARM" --corpus "$CORPUS")"
# Refuse before any work; on success these are verified manifest lines.
STAMPS="$(python3 -m ttg.cli cell-preflight --arm "$ARM" --corpus "$CORPUS" \
  --corpus-jsonl "$JSONL" --store "$STORE" --build-commit "$BUILD_COMMIT")"
# The feature stamp comes from the binary itself, not from the operator.
CAPABILITIES="$("$BINARY" capabilities)"

MAN="${OUT%.json}.manifest.txt"
LOG="${OUT%.json}.log"
mkdir -p "$(dirname "$OUT")"
{
  echo "# cell manifest — ${ARM} x ${CORPUS}"
  echo "arm:          $ARM"
  echo "corpus:       $CORPUS"
  echo "binary:       $BINARY"
  echo "binary_sha256:$(shasum -a 256 "$BINARY" | awk '{print $1}') (not a reproduction target: OUT_DIR bakes the build path)"
  echo "capabilities: $CAPABILITIES"
  echo "corpus_jsonl: $JSONL"
  echo "store:        $STORE"
  echo "model_lock:   $MODEL_LOCK"
  echo "$STAMPS"
  echo "started:      $(date '+%F %T')"
  echo "# THE FULL INVOCATION — flags are recorded, never inferred from defaults:"
  echo "cmd: NOODLBOX_DATA_DIR=$STORE $BINARY swe-bench $JSONL $FLAGS --timeout $TIMEOUT -f json"
} | tee "$MAN"

set +e
# shellcheck disable=SC2086  # FLAGS is a deliberate word-split flag list
NOODLBOX_DATA_DIR="$STORE" "$BINARY" swe-bench "$JSONL" \
  $FLAGS --timeout "$TIMEOUT" -f json > "$OUT" 2> "$LOG"
RC=$?
set -e
{
  echo "finished:     $(date '+%F %T')"
  echo "exit code:    $RC"
  echo "report bytes: $(wc -c < "$OUT" 2>/dev/null || echo 0)"
} | tee -a "$MAN"
[ "$RC" -eq 0 ] || exit "$RC"
# A cell whose reranker cannot be proven is not a measurement.
python3 -m ttg.cli cell-stamp --arm "$ARM" --store "$STORE" --model-lock "$MODEL_LOCK" \
  | tee -a "$MAN"
