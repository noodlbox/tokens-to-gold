#!/usr/bin/env bash
# Build ONE engine (`noodl-eval`) and write its build receipt — in one step.
#
#   arms/build_engine.sh --src <synced engine tree> --commit <40-hex> --out-dir <dir>
#
# The build is handed `--commit` as NOODLBOX_GIT_SHA (engines from noodlbox-app
# #1414 embed and report it); this step also writes the receipt — never by hand:
#   1. MEASURES the synced tree's identity (git blob ids; nothing is compared
#      here — the build host has no history);
#   2. builds the certification binary (`--release`, default features — the
#      shipped config, `rust-analysis` on) from that tree;
#   3. copies it to <out-dir>/noodl-eval and writes <out-dir>/build-receipt.json,
#      re-measuring the tree (a build that touched its own sources refuses).
# The receipt is then checked WHERE THE ENGINE'S HISTORY IS:
#   python3 -m ttg.cli verify-receipt --engine-repo <checkout> \
#     --receipt build-receipt.json --out receipt-verdict.json
# which derives the commit's tree from git; every cell requires that verdict.
set -euo pipefail

SRC=""; COMMIT=""; OUT_DIR=""
PROFILE="release"; FEATURES="default"
while [ $# -gt 0 ]; do
  case "$1" in
    --src) SRC="$2"; shift 2 ;;
    --commit) COMMIT="$2"; shift 2 ;;
    --out-dir) OUT_DIR="$2"; shift 2 ;;
    *) echo "build_engine: unknown argument '$1'" >&2; exit 2 ;;
  esac
done
for required in SRC COMMIT OUT_DIR; do
  if [ -z "${!required}" ]; then
    echo "build_engine: --$(echo "$required" | tr 'A-Z_' 'a-z-') is required" >&2; exit 2
  fi
done
PKG="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SRC="$(cd "$SRC" && pwd)"
mkdir -p "$OUT_DIR"; OUT_DIR="$(cd "$OUT_DIR" && pwd)"

PRE_BUILD="$(cd "$PKG" && python3 -m ttg.cli measure-engine-tree --src "$SRC")"
# The engine's build script bakes the commit into the binary (noodlbox-app #1414;
# `noodl-eval capabilities` reports it as `build_commit`). A synced lease tree has
# no `.git` to resolve it from, and a release build refuses to be unattributable,
# so hand it exactly the commit this receipt will claim. Older engines ignore it.
(cd "$SRC" && NOODLBOX_GIT_SHA="$COMMIT" cargo build --profile "$PROFILE" -p noodlbox-eval)
TARGET_DIR="${CARGO_TARGET_DIR:-$SRC/target}"
cp "$TARGET_DIR/$PROFILE/noodl-eval" "$OUT_DIR/noodl-eval"
(cd "$PKG" && python3 -m ttg.cli write-build-receipt --src "$SRC" --commit "$COMMIT" \
  --pre-build-tree-digest "$PRE_BUILD" --binary "$OUT_DIR/noodl-eval" \
  --profile "$PROFILE" --features "$FEATURES" --out "$OUT_DIR/build-receipt.json")
