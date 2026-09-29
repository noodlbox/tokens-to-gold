# noodlbox-app #1808 real-binary fixture (L18 condition 2)

One DEV build of `nbx` (2.8.0, debug assertions on), run on ONE box by `scripts/validation/b63-lean-wire-did.sh` stage 6 (lease cbx_af7df8a2a2ec, isolated state root, telemetry off).
- **Source:** noodlbox-app `feat/l22-b63-lean-wire-did` at `4969df714ba1476d83bcae9e5b6e20dad76ee8c3`
- **nbx sha256:** `a06168e5d077ce91a299e61d3dc6fd7c1e6e20c16edbd18b55bbae4388e2c9cd`

Query `handle request --intent implement --max-tokens 32000`: nothing trims (`budget.truncated == false` on both JSON rows).

- `json.did.stdout`: `--format json`, the lean compact wire (D+id). **1-based** lines (`compact_wire.rs` `one_based()`), name grammar applied.
- `grep.g0.stdout`: the default grep block (flat G0). This build does not carry the #1791 fix.
- `json.full.stdout`: `--format json --verbosity full`, the object-shape identity twin from the same retrieval. 0-based `location.line`.

sha256 of the three files:
9a47cfaa3043edf65101d0e5f580b719089fcb025e95a9b7f61a0dc9f0fc53d2  json.did.stdout
ae31afa593e453e11f9dbb8e17b17e08c0f50e519d2181d141e4dab013e789ca  grep.g0.stdout
50a90021a74cacb630ecda35996fc24add8a1b3756d2e527e33f7c6c0c3ae924  json.full.stdout
