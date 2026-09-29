# B63 Step 2 cells (reader parity fixtures)

Four cells of one retrieval, `ts40/ofetch-per-origin-circuit-breaker`, base `main`, budget 4k. They are copied from the B63 raw bundles (`lane-evidence/l21/b63/results/out`), sha256 in the PR.

They are **B63-harness renderings**: L21's `b63_wire.rs` reshaped a `main` binary's output. They are **not** noodlbox-app #1808 product wire.
- **Line base:** D+id lines are **0-based** (the harness used the JSON values). #1808 renders 1-based.
- **Name grammar:** they predate it. Names are bare, never JSON literals.
- **Newlines:** they predate #1791, so grep content can carry raw newlines.

**Use:** identity parity (`path:name`) and grep hit parsing only, against `grade_b63.py` on the same cell. **Never** use them for a `(path, line)` oracle join. The real-binary join fixture is `../did_1808/`.
