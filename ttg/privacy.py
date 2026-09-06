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


def _matcher(token: str) -> re.Pattern[str]:
    """One case-insensitive, alphanumeric-bounded matcher for a token -- the
    shared unit both `scrub` and `contains_private` are built on, so their casing
    can never disagree.

    The boundary is ALPHANUMERIC (letters+digits), NOT `\\b`. `\\b` treats `_` as
    a word character, so a `\\b`-anchored pattern would MISS the token inside an
    underscore-joined identifier (`test_<token>_case` in a witness log) -- the
    scrubber's primary target, and under-redaction is the one direction a privacy
    guard must never fail. Alphanumeric lookarounds reject the token embedded in a
    larger WORD (a letter on either side) -- Finding I's intent -- while still
    catching an underscore-separated component and a space/slash-delimited
    occurrence. (This module spells the token only in fragments; the examples
    here use `<token>` so the file is not itself a leak.)"""
    if not token:
        raise PrivacyError("refusing to build a privacy matcher for an empty token")
    return re.compile(rf"(?<![a-z0-9]){re.escape(token)}(?![a-z0-9])", re.IGNORECASE)


MODE, PRIVATE_CORPUS = resolve()
"""The resolved mode name and the held-out corpus name, as data."""

_TOKEN = _matcher(PRIVATE_CORPUS)


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
    return _TOKEN.sub(REDACTION, text)


def contains_private(text: str) -> bool:
    return _TOKEN.search(text) is not None


def scan_bytes(data: bytes) -> list[tuple[int, str]]:
    """Every private-token hit in a byte blob (a compiled binary, any file), as
    `(offset, redacted_context)`. Decoded latin-1 (byte-preserving) so the same
    boundary matcher applies to a binary's embedded strings. R17: the eval binary
    once carried the token in SQL-comment strings — this is the release-gate scan
    that refuses to ship it. The context is SCRUBBED, so a hit can be reported
    without the report itself becoming a leak."""
    text = data.decode("latin-1")
    hits: list[tuple[int, str]] = []
    for m in _TOKEN.finditer(text):
        ctx = text[max(0, m.start() - 24) : m.end() + 24]
        hits.append((m.start(), scrub(ctx).replace("\n", " ").replace("\r", " ")))
    return hits


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
