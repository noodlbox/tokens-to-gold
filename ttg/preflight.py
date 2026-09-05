"""U1 fail-closed pre-flight for the reproduction spine.

Before deriving or running a corpus, confirm the eval binary was built to
analyze that corpus's language. A binary without a language's analysis support
(e.g. a `--no-default-features` build vs a Rust corpus) silently extracts no
symbols and produces an all-empty gold that *looks* like a valid zero-coverage
result. This refuses that run, naming the missing feature — so the public
"reproduce it yourself" path cannot depend on the caller remembering a flag.

Pairs with `noodl-eval capabilities`, which emits
`{"analysis_languages": [...]}` for the languages the binary actually analyzes
under its compiled features.
"""

from __future__ import annotations

import json
import subprocess


class UnsupportedLanguageError(RuntimeError):
    """The eval binary cannot analyze a corpus's language under its build."""


# The cargo feature that adds each cfg-gated language to a build. Languages not
# listed are unconditional (no feature flag restores them), so their absence is
# a genuinely broken binary rather than a forgotten flag.
_FEATURE_FOR_LANGUAGE = {"rust": "rust-analysis"}


def analysis_languages(binary: str) -> set[str]:
    """Query the eval binary's compiled analysis capabilities."""
    proc = subprocess.run(
        [binary, "capabilities"],
        capture_output=True, text=True, check=True,
    )
    payload = json.loads(proc.stdout)
    return set(payload["analysis_languages"])


def require_language_support(binary: str, corpus_language: str) -> None:
    """Raise UnsupportedLanguageError if `binary` cannot analyze
    `corpus_language`. No-op when it can."""
    supported = analysis_languages(binary)
    if corpus_language in supported:
        return
    feature = _FEATURE_FOR_LANGUAGE.get(corpus_language)
    hint = (
        f"rebuild with `--features {feature}`"
        if feature
        else "this language is unconditionally supported by a correct build; "
        "the binary appears broken"
    )
    raise UnsupportedLanguageError(
        f"eval binary does not analyze {corpus_language!r} "
        f"(supports: {sorted(supported)}); {hint}."
    )
