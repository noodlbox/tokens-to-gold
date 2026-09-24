# V2 repo remediation red witness

This directory is deliberately outside the strict `v2/` publication package.
It records review evidence only; it is not a result authority, release asset,
public locator, or runtime permission.

## Frozen pre-fix input

- Repository HEAD: `d94c1d6aa5796851d280e8f1201f756a65b9e989`
- `v2/authority.json`: `51c13b209d514437fd91e1f948c67191172542c50144ffb7c697029c91fd6c31`
- `v2/SHA256SUMS`: `eb5d1fd4d4b00b863d28eded0a0317b8651446cd4304948ccafc557c2d1e4c`
- `v2/verify.py`: `9b3e7db5e520cc120c7a5fe956b3527ff2bee781932278643d00dc919e7aacb1`
- `ttg/curve_recompute.py`: `d7f7fe0231edd605668ccc2f431ce5851da351f85478a0d9ab85b2b7d587207c`

The red driver is [`pre_fix_probe.py`](./pre_fix_probe.py). It now checks the
four frozen hashes above before loading the historical candidate, so it cannot
mislabel the remediated checkout as the pre-fix input.

Executed before remediation:

```sh
PYTHONDONTWRITEBYTECODE=1 python3 v2-remediation-evidence/pre_fix_probe.py \
  --repo-root /Users/youssefkhalil/Desktop/Youssef/noodlbox/worktrees/ttg-v2-publish \
  --audit-root /Users/youssefkhalil/Desktop/Youssef/noodlbox
```

Exit status: `0`.

```text
RED accepted: rr02-missing-preregistration
RED accepted: rr02-native-producer-downgrade
RED accepted: rr02-producer-version-drift
RED accepted: rr02-tokenizer-mismatch
RED accepted: rr04-bundle-status-drift
RED accepted: rr05-extra-package-file
RED accepted: rr06-boolean-median
RED accepted: rr09-fixture-scorer-escape
RED accepted: rr01-stored-curve-corruption
RED accepted: rr03-zero-gold-error-row-removal
RED exposed: rr08-copy-failure-left-partial-target
RED omitted: rr07-v2-verifier-from-ci-lint
```

Each accepted mutation was restamped before validation. The curve mutation
changed only a stored `TtG@50` value, leaving retained primitives and all 16
headline tuples intact. The removed Rust error was zero-gold
`astral-sh__ruff-15626`, so its removal also left every tuple intact.

## Retained empty-vector encoding inspection

The first post-fix raw replay stopped on selected native-floor rows whose ranked
vectors were absent. Read-only source inspection resolved this as a producer
serialization boundary, not a source mismatch:

- producer tree: `3723be44085ab470bad55241853276f85568291e`
- source: `crates/noodlbox-eval/src/benchmarks/instance.rs`
- source SHA-256: `356dcd6697b4088575b15b26f6a049c0f46d754d25ee66ddf290cb3b8ad9e9bb`
- both `retrieved_symbols` and `retrieved_wire_positions` are `Vec` fields with
  `serde(default, skip_serializing_if = "Vec::is_empty")`

Across the 16 selected report/arm sets, joint absence occurred only in nine
native-floor rows. Every one retained an exact zero-delivery curve: whole and
all three checkpoints were zero, delivered tokens were zero, and TtG@50/80/100
were null.

- TypeScript (`ef53786171843f2636be40a58e17cc6f4f98f37a469a6ac2e2685f0e56d82bfa`):
  `arktype-json-schema-refs-dependencies`, `cliffy-config-file-parsing`
- Go (`ba0abf2286bd3be057083b6d15b86e790540ee1caab5ac2a4b919f1d59ba9827`):
  `opa-rego-rule-profiling`, `prometheus-typed-label-sorting`,
  `scc-bounded-memory-spilling`, `scriggo-method-declarations`,
  `tengo-callable-instance-isolation`
- Rust (`e9cec0819e15ca28897e2f51af37ade5e3e25b78efb0e48b947831fdfba06a28`):
  `uutils__coreutils-6575`, `uutils__coreutils-6731`

The remediated helper therefore treats only *joint absence* as the serialized
empty ranked list. One-sided absence, explicit non-list values, and any nonzero
stored curve still reject. This rule changes no input byte and no result tuple.
