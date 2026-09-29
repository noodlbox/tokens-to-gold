# noodlbox-app #1808 real-binary fixture (L18 condition 2)

One DEV build of `nbx` (2.8.0, debug assertions on) from noodlbox-app `feat/l22-b63-lean-wire-did` at 34401a37a, run on ONE box by `scripts/validation/b63-lean-wire-did.sh` stage 6 (lease cbx_69ce6543ee07, isolated state root, telemetry off). Query `handle request --intent implement --max-tokens 32000`: nothing trims (`budget.truncated == false` on both JSON rows).

- `json.did.stdout`: `--format json`, the lean compact wire (D+id). **1-based** lines (`compact_wire.rs` `one_based()`), name grammar applied.
- `grep.g0.stdout`: the default grep block (flat G0). #1808 does not carry the #1791 fix.
- `json.full.stdout`: `--format json --verbosity full`, the object-shape identity twin from the same retrieval. 0-based `location.line`.

sha256:
ae31afa593e4…  grep.g0.stdout
bdc9ee432db4…  json.did.stdout
dc9a9a74f411…  json.full.stdout
