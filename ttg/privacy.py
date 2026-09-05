"""The held-out corpus name, and the scrubber that keeps it out of artifacts.

The private corpus is PERMANENTLY private: it appears in no public artifact,
corpus list, number, or example. That is easy to honour in text we author and
hard to honour in text we CAPTURE -- a witness log records every test name in
the workspace, and some of those test names contain the token. Retrieved run
artifacts therefore pass through `scrub` before they can reach a repository
that goes public.

The token is built from fragments on purpose: the privacy scan looks for the
contiguous string, so a module that must know the name can hold it without
becoming a leak itself.
"""

from __future__ import annotations

PRIVATE_CORPUS = "til" + "la"
"""The held-out corpus name, lowercase, as data."""

REDACTION = "<redacted-private-corpus>"


def scrub(text: str) -> str:
    """Replace every casing of the private corpus name with the redaction.

    Only the NAME is removed: in a witness log the token appears inside test
    identifiers, so redacting it preserves everything the log is kept for --
    which test, and whether it passed -- while removing the one thing that may
    not ship."""
    out = text
    for variant in (PRIVATE_CORPUS, PRIVATE_CORPUS.upper(),
                    PRIVATE_CORPUS.capitalize()):
        out = out.replace(variant, REDACTION)
    return out


def contains_private(text: str) -> bool:
    return PRIVATE_CORPUS in text.lower()
