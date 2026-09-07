"""The held-out corpus name, and the scrubber that keeps it out of artifacts.

The private corpus is PERMANENTLY private: it appears in no public artifact,
corpus list, number, or example. That is easy to honour in text we author and
hard to honour in text we CAPTURE -- a witness log records every test name in
the workspace, and some of those test names contain the token. Retrieved run
artifacts therefore pass through `scrub` before they can reach a repository
that goes public.

## The token is RESOLVED, with an EXPLICIT mode (R18a)

The token comes from one of two modes, and the mode is TOLD, never inferred:

* **in-module** (the default): built from fragments in this module. The privacy
  scan looks for the CONTIGUOUS assembled string, so a module that holds the
  name in fragments (`"til" + "la"`) is not itself a leak.
* **external**: read from `TTG_PRIVATE_CORPUS` when `TTG_PRIVATE_CORPUS_MODE`
  selects it. External mode is WORKS-OR-THROWS: an absent OR empty value raises,
  never a silent fallback to the in-module fragments -- a guard that silently
  scrubbed the wrong token would be a false success on a leak-prevention path.

Every consumer reports the resolved MODE NAME (`mode()`), never the token value.

## One matcher, and a startup self-canary

`scrub()` and `contains_private()` share ONE compiled case-insensitive matcher,
so a casing `scrub()` misses can never be a casing `contains_private()` reports
(the earlier mixed-case bug: DETECTED but left un-redacted). At import a
self-canary asserts the resolved token is detected by its own matcher -- if the
token and the matcher ever disagree the module ABORTS rather than run a privacy
guard that cannot see its own token.
"""

from __future__ import annotations

import os
import re
from collections.abc import Callable
from typing import NamedTuple

REDACTION = "<redacted-private-corpus>"

MODE_IN_MODULE = "in-module"
MODE_EXTERNAL = "external"
_MODE_ENV = "TTG_PRIVATE_CORPUS_MODE"
_TOKEN_ENV = "TTG_PRIVATE_CORPUS"


class PrivacyError(RuntimeError):
    """The privacy token could not be resolved, or disagrees with its matcher."""


def resolve() -> tuple[str, str]:
    """Resolve `(mode_name, token)` from the EXPLICIT mode. Reads the
    environment fresh on each call. External mode is works-or-throws."""
    mode = os.environ.get(_MODE_ENV, MODE_IN_MODULE).strip().lower()
    if mode == MODE_IN_MODULE:
        # Fragment-built on purpose: holding the name here is not a leak because
        # the scan looks for the contiguous assembled string.
        return MODE_IN_MODULE, "til" + "la"
    if mode == MODE_EXTERNAL:
        raw = os.environ.get(_TOKEN_ENV)
        if raw is None or not raw.strip():
            raise PrivacyError(
                f"{_MODE_ENV}=external but {_TOKEN_ENV} is absent or empty -- "
                "external mode is works-or-throws, never a silent fallback to "
                "the in-module fragments"
            )
        return MODE_EXTERNAL, raw.strip().lower()
    raise PrivacyError(
        f"unknown {_MODE_ENV}={mode!r}; expected "
        f"{MODE_IN_MODULE!r} or {MODE_EXTERNAL!r}"
    )


def _substring_matcher(token: str) -> re.Pattern[str]:
    """THE GATE: a case-insensitive CONTIGUOUS SUBSTRING, no boundary. The
    founder rule is that the name never exists as a contiguous string in ANY
    public artifact, so the gate (`contains_private`, consumed by T6, the
    commit-msg hook, and scan-history) catches EVERY occurrence -- inside a
    larger word included. A gate that needs a boundary exception is a weaker
    gate."""
    if not token:
        raise PrivacyError("refusing to build a privacy matcher for an empty token")
    return re.compile(re.escape(token), re.IGNORECASE)


def _matcher(token: str) -> re.Pattern[str]:
    """The REDACTION matcher (scrub only, NOT the gate): case-insensitive and
    ALPHANUMERIC-bounded (letters+digits, NOT `\\b` -- `\\b` treats `_` as a word
    char and would miss the token as an underscore-joined identifier component
    like `test_<token>_case`, the scrubber's primary target). It catches the
    token as a whole word / identifier component while leaving a longer word that
    merely contains it un-mangled. scrub is a helper; `contains_private` (the
    substring gate) is truth. (This module spells the token only in fragments.)"""
    if not token:
        raise PrivacyError("refusing to build a privacy matcher for an empty token")
    return re.compile(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", re.IGNORECASE)


MODE, PRIVATE_CORPUS = resolve()
"""The resolved mode name and the held-out corpus name, as data."""

_SUBSTRING = _substring_matcher(PRIVATE_CORPUS)  # the gate
_BOUNDARY = _matcher(PRIVATE_CORPUS)  # scrub redaction only


def mode() -> str:
    """The resolved mode NAME (`in-module` / `external`) -- never the value.
    Consumers print this so a run's provenance records HOW the token was
    resolved without ever recording WHAT it is."""
    return MODE


def scrub(text: str) -> str:
    """Replace every casing of the private corpus name with the redaction.

    Only the NAME is removed: in a witness log the token appears inside test
    identifiers, so redacting it preserves everything the log is kept for --
    which test, and whether it passed -- while removing the one thing that may
    not ship."""
    return _BOUNDARY.sub(REDACTION, text)


def contains_private(text: str) -> bool:
    """THE GATE: is the token present as a contiguous substring (any casing)?"""
    return _SUBSTRING.search(text) is not None


def scan_bytes(
    data: bytes, filename: str, allowlist: "tuple[AllowEntry, ...] | None" = None
) -> tuple[list[tuple[int, str]], dict[str, int]]:
    """Scan a byte blob (a compiled binary, any file) for the token — the SAME
    scanner as the text tier, not a second one.

    `latin-1` is the decode because it is BIJECTIVE over 0x00-0xFF: every byte
    maps to exactly one code point and back, so a byte-substring scan is exactly
    a text-substring scan. No byte can be lost, merged, or replaced, which a
    lossy decode (utf-8 with `errors=`) would do — and a replaced byte is a hit
    the gate never sees.

    Delegating to `scan_text` means the bytes tier inherits the IDENTIFIER-scoped
    `AllowEntry` walk and the allowlist validation, rather than the window-scoped
    `tuple[str, ...]` form it used to carry. That form is DELETED: a window match
    can excuse a hit two identifiers away, which is exactly the shape ruled
    against for the text tier (an allowlist that widens under pressure is worse
    than none).

    `filename` is the asset's basename, so an entry scoped to one artifact can
    never excuse a hit in another. Returns `scan_text`'s
    `(violations, allowlisted)`.
    """
    return scan_text(
        data.decode("latin-1"),
        filename,
        BINARY_ALLOWLIST if allowlist is None else allowlist,
    )


# Reviewed TEXT-surface allowlist (mirrors the binary tier): known
# identifier-table coincidences where the token appears IN-WORD inside a
# legitimate PUBLIC symbol, never as the corpus name. Each entry is scoped to
# (ASSET, pattern): `asset` is the ONE file basename the exception covers, and
# `pattern` is a context substring (case-insensitive). A hit is allowlisted only
# when the file's basename equals `asset` AND its ±24-char context contains the
# pattern -- so the entry can never excuse a hit in any other file (a cross-file
# plant still fails). Allowlisted hits are COUNTED under the entry name, never
# silently dropped. A STANDALONE hit, or an in-word hit no entry covers, is a
# VIOLATION.
class AllowEntry(NamedTuple):
    """A reviewed identifier-coincidence exception: the token, as the in-word
    span of `pattern` (case-insensitive) inside a hit's OWN enclosing
    identifier, in file `asset` only. `justification` records why it is not a
    leak."""

    name: str
    asset: str
    pattern: str
    justification: str

    def validate(self, token: str) -> None:
        """Refuse an entry whose pattern is part of the token itself.

        The G3 guarantee — prose can never hide behind an identifier entry —
        holds only because a prose hit's enclosing run is the BARE token, which
        no legitimate identifier pattern contains. An entry whose pattern were
        the token (or any fragment of it) WOULD match that bare run, and
        `-- Measured on a <token>-scale catalog ...` would be allowlisted. That
        is the one way this mechanism can be turned against itself.

        It RAISES (a refusal) rather than recording a violation or skipping the
        entry: a malformed guard is an operator error to fix, not a finding to
        report, and a guard that quietly ignored its own broken entry would be a
        false GREEN. The message never spells either value.
        """
        if not self.pattern:
            raise PrivacyError(
                f"allowlist entry {self.name!r} has an empty pattern; an empty "
                "pattern is contained in every identifier and would allowlist "
                "everything in its asset"
            )
        if self.pattern.lower() in token.lower():
            raise PrivacyError(
                f"allowlist entry {self.name!r} has a pattern that is part of "
                "the held-out corpus name itself; such an entry matches the "
                "BARE-token run and would allowlist prose occurrences (the R17 "
                "defect class). Patterns name the SURROUNDING identifier, never "
                "the token."
            )


TEXT_ALLOWLIST: tuple[AllowEntry, ...] = (
    AllowEntry(
        name="arktype-distill",
        asset="deepswe_frozen_ts40.json",
        pattern="distill",
        justification=(
            "the four public arktype identifiers whose name contains `distill` "
            "(ark/type/attributes.ts) in the ts40 corpus's OWN source; the token "
            "is the in-word span of `distill`, not the corpus name. V1 asset "
            "published since August; its sha is pinned and unchanged. (The "
            "identifiers are not spelled here: their `distill` form contains the "
            "token, and this module never carries it contiguously.)"
        ),
    ),
)


BINARY_ALLOWLIST: tuple[AllowEntry, ...] = ()
"""Reviewed exceptions for the BYTES tier. EMPTY on purpose.

R22 expects exactly one: the `jiff` cross-seam coincidence, where two unrelated
identifiers abut (`...MismatchTimeZone` / `largest...`) and the tail of one plus
the head of the next spell the name across the boundary. It is not ours and no
source reword removes it. The entry is added only AT R22, in its own commit, with
the empirical confirmation attached — so the MECHANISM cannot be used to admit an
entry before the evidence for it exists. Any other count or context at R22 is the
R17 defect class: do not attach.
"""


_IDENT_CHARS: frozenset[str] = frozenset(
    "_abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
)


def _is_ident_char(ch: str) -> bool:
    """`[A-Za-z0-9_]`, as an EXPLICIT ASCII set — never `str.isalnum()`.

    This is load-bearing for the bytes tier: under `latin-1`, bytes 0xC0-0xFF
    decode to accented letters that `str.isalnum()` accepts. If those extended an
    identifier run, arbitrary binary garbage could pull a pattern into a hit's
    "enclosing identifier" and widen what an allowlist entry covers. Identifiers
    in this codebase are ASCII, so the class is written out rather than delegated
    to Unicode tables that a future Python could widen underneath us.
    """
    return ch in _IDENT_CHARS


def _classify_hits(
    text: str, filename: str, allowlist: tuple[AllowEntry, ...]
) -> tuple[list[tuple[int, str]], dict[str, int]]:
    """THE FUNNEL: the one place an allowlist is turned into hit classifications.

    Every scan — text tier and bytes tier alike — reaches this function, so the
    entry validation below cannot be bypassed by adding another public entry
    point that forgets to call it. Validation runs BEFORE the first hit is
    examined and regardless of whether there are any, because a malformed entry
    is an error in the guard itself, not a property of the artifact.
    """
    for entry in allowlist:
        entry.validate(PRIVATE_CORPUS)
    violations: list[tuple[int, str]] = []
    allowlisted: dict[str, int] = {}
    n = len(text)
    for m in _SUBSTRING.finditer(text):
        left = m.start()
        while left > 0 and _is_ident_char(text[left - 1]):
            left -= 1
        right = m.end()
        while right < n and _is_ident_char(text[right]):
            right += 1
        ident_low = text[left:right].lower()
        entry_name = next(
            (
                e.name
                for e in allowlist
                if e.asset == filename and e.pattern.lower() in ident_low
            ),
            None,
        )
        if entry_name is not None:
            allowlisted[entry_name] = allowlisted.get(entry_name, 0) + 1
            continue
        raw = text[max(0, m.start() - 24) : m.end() + 24]
        red = _SUBSTRING.sub(REDACTION, raw).replace("\n", " ").replace("\r", " ")
        violations.append((m.start(), red))
    return violations, allowlisted


def scan_text(
    text: str, filename: str, allowlist: tuple[AllowEntry, ...] = TEXT_ALLOWLIST
) -> tuple[list[tuple[int, str]], dict[str, int]]:
    """Substring-scan `text` (from file basename `filename`) for the token,
    classifying each hit against the reviewed `allowlist`. The match is
    IDENTIFIER-scoped, not window-scoped: from each hit we walk left and right to
    the first non-`[A-Za-z0-9_]` boundary to recover the hit's OWN enclosing
    identifier, and test the entry pattern against THAT (case-insensitive
    contains), for the entry's asset only -- so `distill` in a NEIGHBOURING
    identifier within the same JSON line cannot excuse an unrelated hit. Returns
    `(violations, allowlisted)`: `violations` is `(offset, redacted_context)`;
    `allowlisted` maps an entry NAME to its hit count. A hit is allowlisted only
    when `filename` equals the entry's asset AND the hit's enclosing identifier
    contains the pattern; everything else -- a standalone hit, an in-word
    coincidence no entry covers, or the same identifier in a DIFFERENT file -- is
    a violation."""
    return _classify_hits(text, filename, allowlist)


def _self_canary(token: str, detector: Callable[[str], bool]) -> None:
    """Abort unless `detector` sees `token` inside a synthetic string. Guards the
    invariant that the resolved token and the live matcher agree -- a privacy
    guard that cannot detect its own token is worse than none, because it reads
    as passing."""
    if not detector(f"canary-{token}-canary"):
        raise PrivacyError(
            "privacy self-canary FAILED: the resolved token is not detected by "
            "its own matcher -- refusing to run a guard blind to its own token"
        )


_self_canary(PRIVATE_CORPUS, contains_private)
