#!/usr/bin/env bash
# L1 — derive frozen gold from a --reindex pass, then freeze it.
#
# This is the OPT-IN path (`reproduce.sh --rederive-gold`). It is the
# strongest form of G1 evidence -- it proves the gold reproduces from the
# released binary rather than asking you to trust the shipped file -- but it
# is a full re-index (hours per corpus), so it is never the default.
#
# Q2 RIDER: this uses the RELEASED-binary path. The eval crate is closed
# source; a third party re-derives with the released binary, not from source.
set -euo pipefail

CORPUS=""; BINARY=""; JSONL=""; STORE=""; OUTDIR=""; TIMEOUT="900"
while [ $# -gt 0 ]; do
  case "$1" in
    --corpus) CORPUS="$2"; shift 2 ;;
    --binary) BINARY="$2"; shift 2 ;;
    --corpus-jsonl) JSONL="$2"; shift 2 ;;
    --store) STORE="$2"; shift 2 ;;
    --outdir) OUTDIR="$2"; shift 2 ;;
    --timeout) TIMEOUT="$2"; shift 2 ;;
    *) echo "derive_gold: unknown argument '$1'" >&2; exit 2 ;;
  esac
done
PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PKG"
mkdir -p "$OUTDIR"

DERIVED="$OUTDIR/derived_${CORPUS}.json"
FROZEN="$OUTDIR/frozen_gold_${CORPUS}.json"

echo "L1: deriving gold for ${CORPUS} (--reindex; this is the slow path)"
NOODLBOX_DATA_DIR="$STORE" "$BINARY" swe-bench "$JSONL" \
  --graph-gold --raw-query --intent implement --reindex \
  --timeout "$TIMEOUT" -f json > "$DERIVED" 2> "$OUTDIR/derive_${CORPUS}.log"

echo "L1: freezing"
python3 ttg/gold_freezer.py --report "$DERIVED" --binary "$BINARY" --out "$FROZEN"

echo "L1: TIER-1 comparison against the shipped frozen gold"
python3 - "$FROZEN" "gold/frozen_gold_${CORPUS}.json" <<'PY'
import json, sys
from pathlib import Path
fresh, shipped = (json.loads(Path(p).read_text()) for p in sys.argv[1:3])
fg, sg = (d.get("gold", d) for d in (fresh, shipped))
if fg == sg:
    print(f"  TIER-1 PASS: re-derived gold payload is identical ({len(fg)} instances)")
    raise SystemExit(0)
only_fresh, only_shipped = set(fg) - set(sg), set(sg) - set(fg)
print(f"  TIER-1 FAIL: {len(only_fresh)} only-fresh, {len(only_shipped)} only-shipped")
for iid in sorted(set(fg) & set(sg)):
    if fg[iid] != sg[iid]:
        print(f"    {iid}: symbol list differs")
raise SystemExit(1)
PY
