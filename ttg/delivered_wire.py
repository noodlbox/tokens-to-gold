"""Readers of the delivered `nbx search` wire, in both of its shapes (B64
addendum, B63 lean wire): the one place a delivered envelope or grep block is
split into rows.

JSON. A search `result` carries its ranked symbols in exactly one of two shapes,
and the dispatch is EXHAUSTIVE -- exactly one known shape must match, or the
cell fails (a mixed or unknown envelope is never read by a guess):

* OBJECTS (noodlbox-app before #1808): `symbols[]` objects with
  `location.{file_path,start_line}` and `name`; `file_index[].rows[]` objects
  with `name` and a 0-based `line`.
* LINES (the B63 D+id wire, noodlbox-app #1808): `files[]` groups
  `{file_path, [repo_id], [dependency_context], symbols: [line], [members: [line]]}`
  and `file_index[].rows[]` lines. A group key outside that set raises: a new
  row-bearing key is never skipped unread (B88: the pre-#11 reader skipped
  `members`, so every member grep hit was unjoinable). The grammar mirrors the
  product's one row-schema authority,
  `crates/noodlbox-services/src/context/output/compact_wire.rs`:

      symbol  := <id> [<span>] <kind> <name> <role> <reason> [<signature>]
      recall  := [<line>] <kind> <name> [<signature>]
      member  := [<line>] <kind> <name>     (noodlbox-app #2185, B87)
      span    := <a> | <a>-<b>          (1-based lines)
      name    := a bare token (non-empty, no whitespace, no leading `"`)
               | a JSON string literal

  `role` and `reason` must come from the product's closed vocabularies: a name
  the product failed to quote would shift them, so a missed escape raises
  instead of being misread. SYMBOL rows detect a missed escape by their
  vocabularies and MEMBER rows by ending at the name; a recall row's name is
  followed by free-text signature, so an unquoted whitespace name there reads
  as its first word (the product quotes it).

  A member is an identity like any row. A one-line container whose members sit
  on its own line therefore makes that `(path, line)` oracle key ambiguous.

Both shapes yield the same `(path, name, 1-based line)` rows, so an identity
(`path:name`) and an oracle key (`(path, line)`) mean the same thing on either
wire.

GREP. A block is either flat (G0: `path:line:content`) or headed (G1/G2: a path
heading, then indented `  line:content` hits); the rules are in `grep_hits`
(B64 addendum 4, stricter than B63's Amendment 1 on a post-#1791 build).
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum


class WireError(ValueError):
    """A delivered payload whose rows cannot be read under either wire shape."""


@dataclass(frozen=True)
class WireRow:
    """One delivered row: its file, its symbol name, and its 1-based line."""

    path: str
    name: str
    line: int | None

    @property
    def identity(self) -> str:
        return f"{self.path}:{self.name}"


class JsonShape(str, Enum):
    OBJECTS = "objects"
    LINES = "lines"


ROLES = frozenset({"workflow", "definition", "related", "blast_radius", "dependency"})
"""`CompactSymbolRole::label` (noodlbox-services `output/model.rs`)."""

REASONS = frozenset({
    # `compact_symbol` (output/projection.rs): an fts match, the workflow context,
    # or the row's `SymbolOrigin::as_str` (context/types.rs).
    "query_match",
    "workflow_context",
    "anchor",
    "parent_container",
    "routed_member",
    "scoped_member",
    "evidence_splice",
    "file_coverage",
    "file_rerank",
    "reachable_member",
    "edf",
    "admitted_member",
    "file_sibling",
    "file_member",
    "pool_tail_rescue",
    "promoted_definition",
    "query_matched_definition",
    "hook_related",
})

_ID = re.compile(r"[0-9a-f]{12}")
_SPAN = re.compile(r"(?P<start>[0-9]+)(?:-[0-9]+)?")
_LINE = re.compile(r"[0-9]+")
_DECODER = json.JSONDecoder()


def _objects(value: object, what: str) -> list[Mapping[str, object]]:
    if not isinstance(value, list) or not all(isinstance(row, Mapping) for row in value):
        raise WireError(f"{what} is not a list of objects")
    return list(value)


UNSCORED_ROW_LANES = (
    "workflow_symbols", "definitions", "related_members", "blast_radius", "dependency_symbols",
)
"""The `--verbosity full` projection's ranked lanes. No scored row is full
verbosity, so a result carrying rows in any of them is not a compact wire."""


def json_shape(result: Mapping[str, object]) -> JsonShape | None:
    """The one wire shape `result` is in, or None when it delivers no symbol
    lane and no recall row. Mixed or unknown shapes -- and a full-verbosity
    result, whose ranked rows no reader scores -- raise."""
    unscored = [lane for lane in UNSCORED_ROW_LANES if _list(result.get(lane, []), f"`{lane}`")]
    if unscored:
        raise WireError(f"the result carries rows in unscored lanes {unscored} (a full-verbosity envelope)")
    shapes: set[JsonShape] = set()
    if "symbols" in result:
        shapes.add(JsonShape.OBJECTS)
    if "files" in result:
        shapes.add(JsonShape.LINES)
    recall_rows = [
        row
        for group in _objects(result.get("file_index", []), "`file_index`")
        for row in _list(group.get("rows"), "`file_index[].rows`")
    ]
    if recall_rows:
        if all(isinstance(row, Mapping) for row in recall_rows):
            shapes.add(JsonShape.OBJECTS)
        elif all(isinstance(row, str) for row in recall_rows):
            shapes.add(JsonShape.LINES)
        else:
            raise WireError("`file_index` mixes object and line rows")
    if len(shapes) > 1:
        raise WireError("the envelope mixes the object and line wire shapes")
    return next(iter(shapes), None)


def _list(value: object, what: str) -> list[object]:
    if not isinstance(value, list):
        raise WireError(f"{what} is not a list")
    return value


def json_rows(result: Mapping[str, object]) -> list[WireRow]:
    """Every delivered row of a JSON search `result`, in wire order: the ranked
    symbols (on the lean wire, each group's symbols then its members), then the
    `file_index` rows. An unlocated row (empty path) is not a row."""
    shape = json_shape(result)
    if shape is None:
        return []
    if shape is JsonShape.OBJECTS:
        rows = [row for symbol in _objects(result.get("symbols", []), "`symbols`")
                if (row := _object_symbol(symbol)) is not None]
    else:
        rows = [
            row
            for group in _objects(result.get("files", []), "`files`")
            for row in _file_group_rows(group)
        ]
    for group in _objects(result.get("file_index", []), "`file_index`"):
        path = _path(group)
        for entry in _list(group.get("rows"), "`file_index[].rows`"):
            row = _object_recall(path, entry) if shape is JsonShape.OBJECTS else recall_line(path, entry)
            if row.path:
                rows.append(row)
    return rows


_FILE_GROUP_KEYS = frozenset({"file_path", "repo_id", "dependency_context", "symbols", "members"})


def _file_group_rows(group: Mapping[str, object]) -> list[WireRow]:
    """One `files[]` group's rows in wire order: its `symbols` lines, then its
    `members` lines (absent when the group has none). A key outside the group's
    known set raises rather than being skipped."""
    unknown = sorted(set(group) - _FILE_GROUP_KEYS)
    if unknown:
        raise WireError(f"a `files[]` group carries unknown keys {unknown}")
    path = _path(group)
    rows = [
        row
        for line in _list(group.get("symbols"), "`files[].symbols`")
        if (row := symbol_line(path, line)) is not None
    ]
    rows.extend(
        row
        for line in _list(group.get("members", []), "`files[].members`")
        if (row := member_line(path, line)) is not None
    )
    return rows


def _path(group: Mapping[str, object]) -> str:
    path = group.get("file_path")
    if not isinstance(path, str):
        raise WireError("a group has no `file_path`")
    return path


def _object_symbol(symbol: Mapping[str, object]) -> WireRow | None:
    location = symbol.get("location")
    if not isinstance(location, Mapping):
        raise WireError("a symbol has no `location`")
    path = location.get("file_path")
    name = symbol.get("name")
    if not isinstance(path, str) or not isinstance(name, str):
        raise WireError("a symbol has no `location.file_path` or `name`")
    if not path:
        return None
    start = location.get("start_line")
    return WireRow(path, name, start + 1 if isinstance(start, int) else None)


def _object_recall(path: str, row: object) -> WireRow:
    if not isinstance(row, Mapping) or not isinstance(row.get("name"), str):
        raise WireError("a `file_index` row has no `name`")
    line = row.get("line")
    return WireRow(path, str(row["name"]), line + 1 if isinstance(line, int) else None)


def _token(line: str, at: int) -> tuple[str, int]:
    """The bare token starting at `at`, and the index after its separator."""
    end = line.find(" ", at)
    end = len(line) if end < 0 else end
    token = line[at:end]
    if not token:
        raise WireError(f"an empty column at {at} in row {line!r}")
    return token, min(end + 1, len(line))


def _name(line: str, at: int) -> tuple[str, int]:
    """The name column: a JSON string literal when it starts with `"`, else a
    bare token."""
    if line.startswith('"', at):
        try:
            name, end = _DECODER.raw_decode(line, at)
        except json.JSONDecodeError as exc:
            raise WireError(f"a malformed quoted name in row {line!r}: {exc}") from exc
        if not isinstance(name, str) or (end < len(line) and line[end] != " "):
            raise WireError(f"a malformed quoted name in row {line!r}")
        return name, min(end + 1, len(line))
    return _token(line, at)


def symbol_line(path: str, line: object) -> WireRow | None:
    """One `files[].symbols[]` line. None for an unlocated row (empty path)."""
    if not isinstance(line, str):
        raise WireError("a `files[].symbols` row is not a line")
    identifier, at = _token(line, 0)
    if not _ID.fullmatch(identifier):
        raise WireError(f"a row does not lead with a 12-hex id: {line!r}")
    column, after = _token(line, at)
    start: int | None = None
    if span := _SPAN.fullmatch(column):
        start = int(span.group("start"))
        at = after
    at = _token(line, at)[1]  # kind
    name, at = _name(line, at)
    role, at = _token(line, at)
    reason = _token(line, at)[0]
    if role not in ROLES or reason not in REASONS:
        raise WireError(f"row columns after the name are not a role and a reason: {line!r}")
    return WireRow(path, name, start) if path else None


def _located_kind_name(line: str) -> tuple[int | None, str, int]:
    """The `[<line>] <kind> <name>` prefix recall and member rows share (the
    product's `located_kind_name`): the 1-based line when present, the name, and
    the index after the name's separator."""
    column, after = _token(line, 0)
    start: int | None = None
    at = 0
    if _LINE.fullmatch(column):
        start = int(column)
        at = after
    at = _token(line, at)[1]  # kind
    name, at = _name(line, at)
    return start, name, at


def recall_line(path: str, line: object) -> WireRow:
    """One `file_index[].rows[]` line."""
    if not isinstance(line, str):
        raise WireError("a `file_index` row is not a line")
    start, name, _ = _located_kind_name(line)
    return WireRow(path, name, start)


def member_line(path: str, line: object) -> WireRow | None:
    """One `files[].members[]` line: it ends at the name, so anything after it
    (an unquoted whitespace name, a drifted column) raises. None for an
    unlocated group (empty path)."""
    if not isinstance(line, str):
        raise WireError("a `files[].members` row is not a line")
    start, name, at = _located_kind_name(line)
    if at < len(line) or line.endswith(" "):
        raise WireError(f"a member row carries columns after its name: {line!r}")
    return WireRow(path, name, start) if path else None


_FLAT_HIT = re.compile(r"(?P<path>.+?):(?P<line>[0-9]+):")
_HEADED_HIT = re.compile(r"  (?P<line>[0-9]+):")


class UndeliveredHit(WireError):
    """A hit-shaped grep line on a path the retrieval did not deliver."""


@dataclass(frozen=True)
class GrepHits:
    hits: list[tuple[str, int]]
    """`(path, 1-based line)` of every hit, in block order."""
    continuation_lines: int
    """Non-hit, non-heading lines read as raw-newline continuations (pre-#1791
    builds only)."""


def grep_hits(
    text: str, delivered_paths: Sequence[str] | frozenset[str], *, one_line_per_hit: bool
) -> GrepHits:
    """Every hit of a grep block, flat or headed (B64 addendum 4).

    * A column-0 line that is a delivered path is a heading; an indented
      `  line:` hit takes the current heading, and one before any heading raises.
    * A `path:line:` line is a hit; on a path the retrieval did not deliver it
      raises `UndeliveredHit`, on every build.
    * Any other non-empty line is a raw-newline continuation. A build that
      carries the #1791 fix (`one_line_per_hit`, from its receipt verdict) emits
      none, so there it raises; on an earlier build it is counted, never an
      identity. Known pre-#1791 limit: an indented hit after an unrecognised
      heading keeps the previous heading's path.
    """
    paths = frozenset(delivered_paths)
    hits: list[tuple[str, int]] = []
    continuations = 0
    heading: str | None = None
    for line in text.splitlines():
        if not line:
            continue
        if headed := _HEADED_HIT.match(line):
            if heading is None:
                raise WireError(f"an indented hit before any heading: {line!r}")
            hits.append((heading, int(headed.group("line"))))
        elif line in paths:
            heading = line
        elif flat := _FLAT_HIT.match(line):
            if flat.group("path") not in paths:
                raise UndeliveredHit(f"grep hit on a path the retrieval did not deliver: {line[:120]!r}")
            hits.append((flat.group("path"), int(flat.group("line"))))
        elif one_line_per_hit:
            raise WireError(f"a non-hit grep line from a one-line-per-hit (#1791) build: {line[:120]!r}")
        else:
            continuations += 1
    return GrepHits(hits, continuations)
