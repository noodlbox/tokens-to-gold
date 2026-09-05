"""U1 pre-flight gate — witnessed against fake eval binaries.

A fake binary is a tiny script that emits a chosen `capabilities` payload, so
the harness-side refusal is exercised without building the real eval binary
(the behavioural must-red — a Rust repo yields symbols only with the feature —
is witnessed on a lease). The negative control is a rust-OFF binary vs a rust
corpus: it MUST raise. A rust-ON binary vs the same corpus MUST pass.
"""

from __future__ import annotations

import stat
import tempfile
import unittest
from pathlib import Path

from ttg.preflight import (
    PreU1BinaryError,
    UnsupportedLanguageError,
    analysis_languages,
    require_language_support,
)

_ON = ["python", "typescript", "javascript", "go", "rust"]
_OFF = ["python", "typescript", "javascript", "go"]  # --no-default-features


def _fake_binary(dirpath: Path, langs: list[str]) -> str:
    """A script that prints the capabilities JSON for `langs` on `capabilities`."""
    payload = '{"analysis_languages": [%s]}' % ", ".join(f'"{l}"' for l in langs)
    script = dirpath / "fake-eval"
    script.write_text(
        "#!/usr/bin/env bash\n"
        'if [ "$1" = "capabilities" ]; then\n'
        f"  printf '%s' '{payload}'\n"
        "else\n  echo unexpected >&2; exit 3\nfi\n"
    )
    script.chmod(script.stat().st_mode | stat.S_IXUSR)
    return str(script)


class PreflightTest(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.addCleanup(self._tmp.cleanup)

    def test_parses_capability_payload(self) -> None:
        self.assertEqual(analysis_languages(_fake_binary(self.dir, _ON)), set(_ON))

    def test_rust_off_binary_refuses_rust_corpus_naming_the_feature(self) -> None:
        binary = _fake_binary(self.dir, _OFF)
        with self.assertRaises(UnsupportedLanguageError) as ctx:
            require_language_support(binary, "rust")
        self.assertIn("--features rust-analysis", str(ctx.exception))

    def test_rust_on_binary_permits_rust_corpus(self) -> None:
        require_language_support(_fake_binary(self.dir, _ON), "rust")  # no raise

    def test_non_rust_corpora_pass_on_both_builds(self) -> None:
        for langs in (_ON, _OFF):
            for corpus_lang in ("python", "typescript", "go"):
                require_language_support(_fake_binary(self.dir, langs), corpus_lang)

    def test_pre_u1_binary_raises_typed_error(self) -> None:
        # A binary with no `capabilities` subcommand (exits non-zero) — the
        # Aug-20 anchor class — must raise a typed, actionable error.
        script = self.dir / "old-eval"
        script.write_text("#!/usr/bin/env bash\necho 'unknown subcommand' >&2\nexit 2\n")
        script.chmod(script.stat().st_mode | stat.S_IXUSR)
        with self.assertRaises(PreU1BinaryError) as ctx:
            require_language_support(str(script), "rust")
        self.assertIn("eval/ttg-recert-2.3", str(ctx.exception))

    def test_missing_unconditional_language_flags_broken_binary(self) -> None:
        # A binary somehow lacking Go (no feature restores it) is broken, not a
        # forgotten flag — the message must say so rather than suggest a feature.
        binary = _fake_binary(self.dir, ["python"])
        with self.assertRaises(UnsupportedLanguageError) as ctx:
            require_language_support(binary, "go")
        self.assertIn("broken", str(ctx.exception))
        self.assertNotIn("--features", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
