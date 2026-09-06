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
import shutil
import subprocess


class UnsupportedLanguageError(RuntimeError):
    """The eval binary cannot analyze a corpus's language under its build."""


class PreU1BinaryError(RuntimeError):
    """The eval binary predates the `capabilities` subcommand (U1), so its
    analysis support cannot be introspected — including the Aug-20 anchor."""


# The cargo feature that adds each cfg-gated language to a build. Languages not
# listed are unconditional (no feature flag restores them), so their absence is
# a genuinely broken binary rather than a forgotten flag.
_FEATURE_FOR_LANGUAGE = {"rust": "rust-analysis"}

# Which language a corpus's checkouts are, i.e. which analysis support the eval
# binary must have compiled in for that corpus to yield gold at all. ts40 is
# TS+JS: both are unconditional, so either name answers the same question.
LANGUAGE_BY_CORPUS = {
    "ts40": "typescript",
    "py_nosphinx": "python",
    "gauntlet_py56": "python",
    "go34": "go",
    "rust43": "rust",
}


class UnknownCorpusError(KeyError):
    """No language is registered for this corpus, so the pre-flight cannot
    vouch for it — refused rather than waved through."""


def language_for_corpus(corpus: str) -> str:
    try:
        return LANGUAGE_BY_CORPUS[corpus]
    except KeyError:
        raise UnknownCorpusError(
            f"no language registered for corpus {corpus!r}; add it to "
            "LANGUAGE_BY_CORPUS before running it"
        ) from None


def require_corpus_support(binary: str, corpus: str) -> None:
    """Pre-flight a corpus by name — the form the run path calls."""
    require_language_support(binary, language_for_corpus(corpus))


class MissingToolError(RuntimeError):
    """A comparator arm's external tool is not on PATH; refuse before any run."""


def require_native_floor_tools() -> None:
    """The native_floor (explorer) arm shells out to ripgrep. A missing rg made
    the eval binary emit an empty comparator floor (run10b) that would inflate
    every lift claim, so refuse the arm at t=0 rather than run it blind — the
    same fail-closed pattern as the language pre-flight (U1). The eval binary
    also errors per-instance without rg (defence in depth); this catches it
    before a checkout is even provisioned."""
    if shutil.which("rg") is None:
        raise MissingToolError(
            "the native_floor arm requires ripgrep (`rg`) on PATH; it is absent. "
            "Install it (warmup-remote.sh declares it) — a silent empty floor "
            "understates the baseline and inflates every lift claim measured "
            "against it"
        )


def analysis_languages(binary: str) -> set[str]:
    """Query the eval binary's compiled analysis capabilities.

    Raises PreU1BinaryError for a binary that predates the `capabilities`
    subcommand (a pre-U1 build, including the Aug-20 anchor) — a typed error
    naming the fix, not a raw CalledProcessError the caller must decode."""
    proc = subprocess.run(
        [binary, "capabilities"], capture_output=True, text=True,
    )
    if proc.returncode != 0:
        raise PreU1BinaryError(
            f"{binary!r} has no `capabilities` subcommand — it predates U1; "
            "rebuild from >= eval/ttg-recert-2.3."
        )
    return set(json.loads(proc.stdout)["analysis_languages"])


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
