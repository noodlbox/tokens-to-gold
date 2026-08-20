"""TIER-1 frozen-gold comparison — payload plus the claim-bearing header.

MUST-NOT #3: never whole-file `cmp` a frozen gold. The header stamps the
PRODUCING BINARY, so two byte-different files can carry an identical gold
payload. A whole-file compare therefore reports a perfect reproduction as a
failure — which it did, three times, in this campaign.

What is compared:

* the **gold payload** (instance -> symbol list, order-sensitive: the freezer
  never sorts), and
* the **five claim-bearing header fields** below.

The `binary` stamp is REPORTED but never gated: binary SHA is a function of
the absolute build path (`OUT_DIR`), so it is not a reproduction target.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Final

CLAIM_FIELDS: Final[tuple[str, ...]] = (
    "corpus",
    "protocol",
    "graph_gold_derivation_version",
    "total_gold_symbols",
    "instances_with_gold",
)


@dataclass(frozen=True)
class Tier1Result:
    ok: bool
    payload_ok: bool
    field_findings: list[str] = field(default_factory=list)
    payload_findings: list[str] = field(default_factory=list)
    binary_note: str = ""

    def render(self) -> str:
        lines = [f"  TIER-1: {'PASS' if self.ok else 'FAIL'}"]
        for finding in (*self.field_findings, *self.payload_findings):
            lines.append(f"    {finding}")
        if self.binary_note:
            lines.append(f"    {self.binary_note}  (reported, NOT gated)")
        return "\n".join(lines)


def _payload(doc: Mapping[str, object]) -> Mapping[str, object]:
    gold = doc.get("gold", doc)
    if not isinstance(gold, Mapping):
        raise ValueError("no gold payload")
    return gold


def compare_frozen_gold(candidate: str | Path, anchor: str | Path) -> Tier1Result:
    """Compare a re-derived frozen gold against the pinned anchor."""
    cand = json.loads(Path(candidate).read_text())
    anch = json.loads(Path(anchor).read_text())

    field_findings = [
        f"{name}: candidate={cand.get(name)!r} anchor={anch.get(name)!r}"
        for name in CLAIM_FIELDS
        if name in cand or name in anch
        if cand.get(name) != anch.get(name)
    ]

    cand_gold, anch_gold = _payload(cand), _payload(anch)
    payload_findings: list[str] = []
    only_cand = sorted(set(cand_gold) - set(anch_gold))
    only_anch = sorted(set(anch_gold) - set(cand_gold))
    if only_cand:
        payload_findings.append(f"only in candidate ({len(only_cand)}): {only_cand[:5]}")
    if only_anch:
        payload_findings.append(f"only in anchor ({len(only_anch)}): {only_anch[:5]}")
    payload_findings.extend(
        f"{iid}: symbol list differs (order-sensitive — the freezer never sorts)"
        for iid in sorted(set(cand_gold) & set(anch_gold))
        if cand_gold[iid] != anch_gold[iid]
    )

    binary_note = ""
    if cand.get("binary") != anch.get("binary"):
        binary_note = (
            f"binary stamp differs: candidate={cand.get('binary')!r} "
            f"anchor={anch.get('binary')!r}"
        )
    payload_ok = not payload_findings
    return Tier1Result(
        ok=payload_ok and not field_findings,
        payload_ok=payload_ok,
        field_findings=field_findings,
        payload_findings=payload_findings,
        binary_note=binary_note,
    )
