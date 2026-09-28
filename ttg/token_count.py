"""The one tokenizer authority for delivered pricing: the engine's `TokenCounter`.

`noodl-eval count-tokens` reads bytes on stdin and prints their o200k_base token
count (the engine's `TOKENIZER_ENCODING`). The harness never carries a second
tokenizer, so the delivered arm and the engine can never disagree on what a
token is (PREREGISTRATION addendum §2).
"""

from __future__ import annotations

import subprocess
from pathlib import Path

ENCODING = "o200k_base"


class TokenCountError(RuntimeError):
    """The engine counter failed or answered something that is not a count."""


class EngineTokenCounter:
    """`TokenCount` backed by `noodl-eval count-tokens`."""

    def __init__(self, noodl_eval: str | Path) -> None:
        self._binary = str(noodl_eval)

    def __call__(self, data: bytes) -> int:
        proc = subprocess.run(
            [self._binary, "count-tokens", "--encoding", ENCODING],
            input=data,
            capture_output=True,
            check=False,
        )
        if proc.returncode != 0:
            raise TokenCountError(
                f"noodl-eval count-tokens exited {proc.returncode}: "
                f"{proc.stderr.decode(errors='replace').strip()}"
            )
        text = proc.stdout.decode().strip()
        if not text.isdigit():
            raise TokenCountError(f"noodl-eval count-tokens printed {text!r}, not a count")
        return int(text)
