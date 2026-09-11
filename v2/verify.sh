#!/usr/bin/env bash
# Stdlib-only entry point for the V2 Tier A A1 publication verifier.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
exec python3 "$SCRIPT_DIR/verify.py" "$@"
