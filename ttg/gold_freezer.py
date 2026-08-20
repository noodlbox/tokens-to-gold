#!/usr/bin/env python3
"""Write a frozen-gold file from a `noodl-eval swe-bench -f json` report.

`frozen_gold_*.json` is the authoritative gold denominator for every
TokensToGold claim: recall is scored as the frozen gold intersected with an
arm's delivered identities, so the frozen file -- not any per-run derivation --
is what every published number rests on. Yet until this script, NOTHING in any
repo ever WROTE one. The freeze was an ad-hoc operator invocation that existed
nowhere, which made the benchmark's most load-bearing artifact unreproducible.
This is that step, as versioned code.

Self-contained by design (stdlib only): a reproduction script that needs an
unversioned side package is not a reproduction.

BYTE-EXACT SPEC. Measured from the two pinned files, then PROVEN by re-deriving
both byte-for-byte from their source derivation reports -- there is no tenth
property:

 1. Formatting is `json.dumps(obj, indent=1)` -- ONE-space indent -- and NO
    trailing newline. The last byte is `}` (0x7d).
 2. Header keys are in INSERTION order, not sorted: corpus, binary, protocol,
    graph_gold_derivation_version, total_gold_symbols, instances_with_gold, gold.
 3. Gold instance KEYS are sorted.
 4. Zero-gold instances are EXCLUDED (ts40: 38 successful rows -> 37 entries;
    py_nosphinx: 40 -> 39).
 5. Symbol order WITHIN an instance is the source report's order, VERBATIM.
    *** DO NOT SORT IT. *** This is the trap. Sorting leaves every gold SET
    identical, so no set-match score moves and nothing looks wrong -- but it
    reorders 24/37 ts40 and 7/39 py instances and trips the certifier's
    CERTIFIED-MODULO-ORDER (rc4). It then reads as a determinism bug in the
    derivation binary when it is really a freezer-format bug. The sorted variant
    even has the IDENTICAL byte length (21923 for ts40) and a different sha256,
    so a length check cannot see it. Verify against the pinned anchor DIGEST,
    never against size.
 6. total_gold_symbols = sum(len(v) for v in gold.values())  -- 372 / 54.
 7. instances_with_gold = len(gold)                          -- 37 / 39.
 8. binary  = "<binary-filename> <short-sha-8>", e.g.
    "noodl-eval-enriched-v2 4bfec6fd". Derived by `binary_label`, never typed:
    an operator-typed label can silently misattribute a frozen gold to the wrong
    build, which is the provenance hole this script exists to close.
 9. protocol = e.g. "deepswe-frozen ForceReindex".

Pinned anchors this script reproduces byte-for-byte:
  ts40         fcc09bd98d5e648be1c46803b72140b233599ef91e2dd945ba4b52e72d02a0e3
  py_nosphinx  05033580302881b919729bdbd9b485c2b89e0531bd338f3e19acedbcebe67736

Usage:
    python3 gold_freezer.py <report.json> <out.json> \\
        --corpus ts40 --binary /path/to/noodl-eval-enriched-v2 \\
        [--protocol "deepswe-frozen ForceReindex"]
"""

from __future__ import annotations

import argparse
import hashlib
import json
from collections.abc import Mapping, Sequence
from pathlib import Path

SHORT_SHA_LEN = 8
DEFAULT_PROTOCOL = "deepswe-frozen ForceReindex"


def load_report(path: str | Path) -> Mapping[str, object]:
    """Parse a `-f json` report, skipping the run's stdout preamble.

    Same idiom as the sibling `compare_paired.py` / `swe_bench_sharded.py`:
    the binary prints progress before the JSON object.
    """
    lines = Path(path).read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.lstrip().startswith("{"):
            try:
                parsed = json.loads("\n".join(lines[i:]))
            except json.JSONDecodeError:
                continue
            if isinstance(parsed, Mapping):
                return parsed
    raise SystemExit(f"no JSON object found in {path}")


def binary_label(binary_path: str | Path) -> str:
    """Spec row 8: `"<filename> <short-sha-8>"`, derived from the binary itself."""
    p = Path(binary_path)
    digest = hashlib.sha256(p.read_bytes()).hexdigest()
    return f"{p.name} {digest[:SHORT_SHA_LEN]}"


def build_gold_map(results: Sequence[Mapping[str, object]]) -> dict[str, list[str]]:
    """The gold mapping alone (spec rows 3-5), from raw per-instance results.

    Takes plain report data rather than a loader type, so the freeze format has
    exactly one authority regardless of who read the report.

    Raises:
        SystemExit: if no instance carries `gold_symbols` -- the report is NOT
            enriched (needs the ffe23900-class binary) and freezing is
            inapplicable. A silently-empty gold file would poison every
            downstream recall number, so this refuses rather than degrades.
    """
    if all(r.get("gold_symbols") is None for r in results):
        raise SystemExit(
            "no instance carries gold_symbols -- report is NOT enriched "
            "(needs the ffe23900-class binary); freezing is inapplicable"
        )

    gold: dict[str, list[str]] = {}
    for r in results:
        symbols = r.get("gold_symbols")
        # Row 4: failed or zero-gold instances are excluded.
        if r.get("error") is not None or not symbols:
            continue
        if not isinstance(symbols, list):
            raise SystemExit(f"{r.get('instance_id')}: gold_symbols is not a list")
        # Row 5: list() preserves the report's order. NEVER sorted() here.
        gold[str(r["instance_id"])] = [str(s) for s in symbols]

    if not gold:
        raise SystemExit("every instance is failed or zero-gold -- nothing to freeze")
    return dict(sorted(gold.items()))  # Row 3: instance KEYS sorted.


def document_from_gold(
    gold: dict[str, list[str]],
    corpus: str,
    binary: str,
    protocol: str,
    graph_gold_derivation_version: int,
) -> dict[str, object]:
    """Assemble the JSON document around a built gold map (rows 2, 6, 7).

    The return type is the JSON boundary shape: a frozen-gold file is
    heterogeneous by definition. Everything typed lives in `build_gold_map`.
    """
    return {  # Row 2: insertion order IS the header order.
        "corpus": corpus,
        "binary": binary,
        "protocol": protocol,
        "graph_gold_derivation_version": graph_gold_derivation_version,
        "total_gold_symbols": sum(len(v) for v in gold.values()),  # Row 6
        "instances_with_gold": len(gold),  # Row 7
        "gold": gold,
    }


def report_results(report: Mapping[str, object]) -> list[Mapping[str, object]]:
    """The report's per-instance rows, validated -- the one narrowing of the
    JSON boundary, so no caller has to hand-narrow an `object`."""
    results = report.get("results")
    if not isinstance(results, list):
        raise SystemExit("report is missing results[]")
    if not all(isinstance(r, Mapping) for r in results):
        raise SystemExit("report results[] holds a non-object row")
    return results


def freeze_bytes(
    report: Mapping[str, object], corpus: str, binary: str, protocol: str
) -> bytes:
    """The exact bytes of the frozen-gold file (row 1: indent=1, no trailing NL)."""
    results = report_results(report)
    version = report.get("graph_gold_derivation_version")
    if not isinstance(version, int):
        raise SystemExit("report is missing graph_gold_derivation_version")
    doc = document_from_gold(build_gold_map(results), corpus, binary, protocol, version)
    return json.dumps(doc, indent=1).encode("utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="Write a frozen-gold file from a report.")
    ap.add_argument("report", help="noodl-eval swe-bench -f json report")
    ap.add_argument("out", help="frozen_gold_<corpus>.json to write")
    ap.add_argument("--corpus", required=True, help='e.g. "ts40", "py_nosphinx"')
    ap.add_argument("--binary", required=True, help="path to the deriving eval binary")
    ap.add_argument("--protocol", default=DEFAULT_PROTOCOL)
    args = ap.parse_args()

    blob = freeze_bytes(
        load_report(args.report),
        args.corpus,
        binary_label(args.binary),
        args.protocol,
    )
    Path(args.out).write_bytes(blob)
    # The digest is the only valid check: the row-5 trap yields an identical size.
    print(f"{hashlib.sha256(blob).hexdigest()}  {args.out}  ({len(blob)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
