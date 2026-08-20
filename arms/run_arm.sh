#!/usr/bin/env bash
# Run ONE cell (arm x corpus) of the matrix.
#
# FOOTGUN DEFENCE, LAYER 3: this script NEVER builds its own flags. It asks
# `ttg.cli flags` for them and echoes the COMPLETE invocation into the cell
# manifest, so the recorded provenance carries the actual flags rather than a
# prose claim about what an omitted default used to mean. (The recorded
# M23-P4 manifest asserts "flag absent => Off", which is false post-ceea4ab0c.)
set -euo pipefail

ARM=""; CORPUS=""; BINARY=""; JSONL=""; STORE=""; OUT=""; TIMEOUT="900"
while [ $# -gt 0 ]; do
  case "$1" in
    --arm) ARM="$2"; shift 2 ;;
    --corpus) CORPUS="$2"; shift 2 ;;
    --binary) BINARY="$2"; shift 2 ;;
    --corpus-jsonl) JSONL="$2"; shift 2 ;;
    --store) STORE="$2"; shift 2 ;;
    --out) OUT="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    *) echo "run_arm: unknown argument '$1'" >&2; exit 2 ;;
  esac
done
for required in ARM CORPUS BINARY JSONL STORE OUT; do
  if [ -z "${!required}" ]; then echo "run_arm: --${required,,} is required" >&2; exit 2; fi
done

PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PKG"

# Single source of truth. If this fails (unknown/unavailable arm, or a policy
# with no budget), the cell does NOT run.
FLAGS="$(python3 -m ttg.cli flags --arm "$ARM" --corpus "$CORPUS")"

MAN="${OUT%.json}.manifest.txt"
LOG="${OUT%.json}.log"
mkdir -p "$(dirname "$OUT")"
{
  echo "# cell manifest — ${ARM} x ${CORPUS}"
  echo "arm:          $ARM"
  echo "corpus:       $CORPUS"
  echo "binary:       $BINARY"
  echo "binary_sha256:$(shasum -a 256 "$BINARY" | awk '{print $1}')"
  echo "corpus_jsonl: $JSONL"
  echo "store:        $STORE"
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
exit "$RC"
