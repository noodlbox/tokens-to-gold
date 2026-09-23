#!/usr/bin/env bash
# Build ONE engine (`noodl-eval`) and write its build receipt — in one step.
#
#   arms/build_engine.sh --src <synced engine tree> --commit <40-hex> \
#     --expected-tree-digest <from `ttg.cli engine-tree-digest` where the history is> \
#     --out-dir <dir>
#
# The receipt is the ONLY evidence of which commit a binary came from
# (`noodl-eval` embeds none), so it is never hand-written: this script
#   1. refuses unless the synced tree is exactly the commit's tree (git blob ids);
#   2. builds the certification binary (`--release`, default features — the
#      shipped config, `rust-analysis` on) from that tree;
#   3. copies it to <out-dir>/noodl-eval and writes <out-dir>/build-receipt.json,
#      re-identifying the tree after the build (a build must not touch its sources).
# Run cells with `--binary <out-dir>/noodl-eval --build-receipt <out-dir>/build-receipt.json`.
set -euo pipefail

SRC=""; COMMIT=""; EXPECTED=""; OUT_DIR=""
PROFILE="release"; FEATURES="default"
while [ $# -gt 0 ]; do
  case "$1" in
    --src) SRC="$2"; shift 2 ;;
    --commit) COMMIT="$2"; shift 2 ;;
    --expected-tree-digest) EXPECTED="$2"; shift 2 ;;
    --out-dir) OUT_DIR="$2"; shift 2 ;;
    *) echo "build_engine: unknown argument '$1'" >&2; exit 2 ;;
  esac
done
for required in SRC COMMIT EXPECTED OUT_DIR; do
  if [ -z "${!required}" ]; then
    echo "build_engine: --$(echo "$required" | tr 'A-Z_' 'a-z-') is required" >&2; exit 2
  fi
done
PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$(cd "$SRC" && pwd)"
mkdir -p "$OUT_DIR"; OUT_DIR="$(cd "$OUT_DIR" && pwd)"

(cd "$PKG" && python3 -m ttg.cli verify-engine-tree --src "$SRC" --expected-digest "$EXPECTED")
(cd "$SRC" && cargo build --profile "$PROFILE" -p noodlbox-eval)
TARGET_DIR="${CARGO_TARGET_DIR:-$SRC/target}"
cp "$TARGET_DIR/$PROFILE/noodl-eval" "$OUT_DIR/noodl-eval"
(cd "$PKG" && python3 -m ttg.cli write-build-receipt --src "$SRC" --commit "$COMMIT" \
  --expected-digest "$EXPECTED" --binary "$OUT_DIR/noodl-eval" \
  --profile "$PROFILE" --features "$FEATURES" --out "$OUT_DIR/build-receipt.json")
