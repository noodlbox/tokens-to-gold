"""The product arm: score what `nbx search` actually delivers (PREREGISTRATION
addenda of 2026-09-29, LEDGER B64).

The ranked-list arms price a reconstruction of the engine's untrimmed ranked
list. This module prices and scores the response an agent RECEIVES: the exact
stdout/stderr bytes of the shipped CLI (or the MCP tool's content text), matched
with the unchanged `ttg.matcher.match_gold` against the frozen gold.

Three pure pieces, each the one authority for its question:

* `json_identities` -- the delivered `file:name` identities of a JSON envelope
  (`symbols[]` with a location, then `file_index[].rows[]`, in wire order).
* `grep_identities` -- the identities of a grep block, resolved through the
  same cell's identity oracle by `(path, 1-based line)`. Fail-closed: a hit with
  no oracle row raises `UnjoinableHit`. The headline credits a hit only when
  exactly one oracle name sits at its key (the LOWER bound); the all-names
  credit is carried beside it as the upper bound.
* `price` -- o200k tokens of the delivered bytes, through an injected counter
  (production: the engine's `TokenCounter`, see `ttg.token_count`). The
  headline `ttg_wire` counts stdout + stderr as ONE concatenation.

Nothing here reconstructs, estimates, or re-renders a payload.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from enum import Enum

from ttg.matcher import match_gold

TokenCount = Callable[[bytes], int]
"""o200k_base token count of a byte string. One authority, injected."""

_GREP_HIT = re.compile(r"^(?P<path>.+?):(?P<line>[0-9]+):")


class DeliveredSurface(str, Enum):
    """The pre-registered delivered rows (addendum §1 and addendum 2 C)."""

    GREP = "delivered.grep"
    JSON = "delivered.json"
    DEFAULT = "delivered.default"
    MCP = "delivered.mcp"

    @property
    def is_grep(self) -> bool:
        return self in (DeliveredSurface.GREP, DeliveredSurface.DEFAULT)


class DeliveredScoringError(ValueError):
    """A delivered payload that cannot be scored; the cell is a FAILED cell."""


class UnjoinableHit(DeliveredScoringError):
    """A grep hit whose `(path, line)` key has no identity-oracle row.

    Addendum §3: fail-closed. An identity is never guessed from content text."""


@dataclass(frozen=True)
class GrepIdentities:
    """The two credits of a grep block, plus how many hits were ambiguous."""

    lower: list[str]
    """Headline: one identity per hit whose key resolves to exactly one name."""
    upper: list[str]
    """Every name at every hit's key, in hit order."""
    ambiguous_hits: int


@dataclass(frozen=True)
class Price:
    """o200k token counts of one delivered response (addendum 2 B)."""

    wire: int
    """stdout + stderr as one concatenation -- the headline `ttg_wire`."""
    stdout: int
    stderr: int


def _envelope_result(text: str) -> Mapping[str, object]:
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise DeliveredScoringError(f"delivered JSON does not parse: {exc}") from exc
    result = doc.get("result") if isinstance(doc, Mapping) else None
    if not isinstance(result, Mapping):
        raise DeliveredScoringError("delivered JSON has no `result` object")
    return result


def _rows(value: object) -> list[Mapping[str, object]]:
    return [row for row in value if isinstance(row, Mapping)] if isinstance(value, list) else []


def json_identities(text: str) -> list[str]:
    """The delivered `file:name` identities of a JSON search envelope, in wire
    order: located `symbols[]`, then every `file_index` row (B52's
    `payload_items`). Counts and totals are never identities."""
    result = _envelope_result(text)
    identities: list[str] = []
    for symbol in _rows(result.get("symbols")):
        location = symbol.get("location")
        path = location.get("file_path") if isinstance(location, Mapping) else None
        if isinstance(path, str) and path:
            identities.append(f"{path}:{symbol.get('name')}")
    for group in _rows(result.get("file_index")):
        path = group.get("file_path")
        identities.extend(f"{path}:{row.get('name')}" for row in _rows(group.get("rows")))
    return identities


def _oracle_index(oracle_text: str) -> dict[tuple[str, int], list[str]]:
    """`(path, 1-based line)` -> the distinct names the oracle places there, in
    oracle order. Both wire line fields are 0-based; the grep renderer adds 1."""
    result = _envelope_result(oracle_text)
    index: dict[tuple[str, int], list[str]] = {}

    def add(path: object, zero_based: object, name: object) -> None:
        if isinstance(path, str) and path and isinstance(zero_based, int) and isinstance(name, str):
            names = index.setdefault((path, zero_based + 1), [])
            if name not in names:
                names.append(name)

    for symbol in _rows(result.get("symbols")):
        location = symbol.get("location")
        if isinstance(location, Mapping):
            add(location.get("file_path"), location.get("start_line"), symbol.get("name"))
    for group in _rows(result.get("file_index")):
        for row in _rows(group.get("rows")):
            add(group.get("file_path"), row.get("line"), row.get("name"))
    return index


def grep_identities(grep_text: str, oracle_text: str) -> GrepIdentities:
    """Resolve every grep hit through the same cell's identity oracle.

    A line that is not a `path:line:` hit (a `#` section marker) carries no
    identity. A hit whose key the oracle lacks raises `UnjoinableHit`."""
    index = _oracle_index(oracle_text)
    lower: list[str] = []
    upper: list[str] = []
    ambiguous = 0
    for line in grep_text.splitlines():
        hit = _GREP_HIT.match(line)
        if hit is None:
            continue
        key = (hit.group("path"), int(hit.group("line")))
        names = index.get(key)
        if not names:
            raise UnjoinableHit(f"grep hit {key[0]}:{key[1]} has no identity-oracle row")
        upper.extend(f"{key[0]}:{name}" for name in names)
        if len(names) == 1:
            lower.append(f"{key[0]}:{names[0]}")
        else:
            ambiguous += 1
    return GrepIdentities(lower=lower, upper=upper, ambiguous_hits=ambiguous)


def price(stdout: bytes, stderr: bytes, count: TokenCount) -> Price:
    """Price one delivered CLI response: the headline counts stdout + stderr as
    ONE concatenation (a shell tool hands the agent both streams)."""
    return Price(wire=count(stdout + stderr), stdout=count(stdout), stderr=count(stderr))


def recall(gold: Sequence[str], identities: Sequence[str]) -> float:
    """Frozen-gold recall of a delivered identity list (the unchanged matcher)."""
    return match_gold(gold, identities).recall
