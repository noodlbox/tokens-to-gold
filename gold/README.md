# Frozen gold

Frozen per-corpus gold (`frozen_gold_<corpus>.json`), digest-pinned in
`SHA256SUMS` and in `PIN.toml [gold]`. The score stage loads these directly.

**`frozen_gold_payload.json` is the held-out CONFIRM tier — INTERNAL, not a
published tier: it is deliberately absent from `arms/arm_matrix.py` `CORPORA`
and from preflight, so it never enters the public results grid; its confirm
numbers are internal (locked claims language), and it lives here only so the
harness's own score stage loads it offline.** See
`reports/internal-confirm/MANIFEST.json` for the tier record (N, the twelve
excluded instance ids, provenance, and the `score-own` reproduce command).
