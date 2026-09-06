#!/usr/bin/env bash
# One-time setup: arm the repository's git hooks.
#
# The commit-msg privacy guard lives in scripts/git-hooks/ and only runs once
# git is told to look there — a fresh clone has core.hooksPath unset, so the
# guard is dormant until this runs. R15: make arming it a single explicit step
# rather than a line every contributor is expected to remember.
set -euo pipefail
here="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

git -C "$here" config core.hooksPath scripts/git-hooks
echo "installed: core.hooksPath = scripts/git-hooks"
echo "  the commit-msg held-out-corpus guard is now armed for this clone."
echo
echo "release gate (run before shipping the eval binary):"
echo "  python3 -m ttg.cli scan-binary --path <noodl-eval>"
