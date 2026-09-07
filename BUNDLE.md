# The artifact bundle — the 14-row publication contract

> **Versions** — TokensToGold benchmark **V1** · harness release **v1-2.3.18** · engine **noodlbox 2.3.18**. Three numbers coexist: the benchmark scope is V1 (the launch-scope doc); the harness release is tagged `v1-2.3.18` (benchmark V1 · engine 2.3.18) — named so no tag reads as a benchmark V2, none exists yet — and carries the reach-split metric-schema change (`reach_at_80` → `whole_list` + `within_32k`); the engine is the 2.3.18 build pinned in `PIN.toml [recert.binary]`.

Every public benchmark result here ships with each row of this contract either
**FILLED** (with its in-repo pointer) or **EXPLAINED-ABSENT** (with the reason,
stated publicly). Explained absence is permitted; silent absence is not.

TokensToGold is a **retrieval / context-selection** benchmark — deterministic,
wire-priced, no LLM judge, no agent loop. Several contract rows exist for
whole-agent benchmarks and are absent here **by construction**; each such row
says so below, on the boundary that keeps the quantities honest.

## Held-out corpus (canonical claim — the single source others reference)

**The held-out corpus is not named in any public artifact.**

That is the whole claim, and it is exactly this: a mechanical *not-named*
property, never "confidential" and never "non-derivable". The held-out corpus is
itself a private repository, so the derivability of its name grants nothing; the
claim is literal absence and nothing more. Because the claim is that narrow, the
guards that enforce it — the T6 privacy scan, the commit-message hook, and the
history-scan CLI (R18b) — are its SOLE evidence, not a defence in depth; the
narrow claim raises the load on those guards. Every other artifact
(`PREREGISTRATION.md`, `README.md`, the page) references THIS sentence rather
than restating it, so the copies cannot drift apart.

| # | Row | Status | Where / why |
|---|---|---|---|
| 1 | **Manifest** | FILLED | `PIN.toml` — gold-derivation source commit (`0c061c57` / base `6d3ccaf0`, committed + pushed), gold digests, artifact digests; `acceptance/` pins the measured `main` SHA + binary digest; corpus repo lists in `corpora/`. Model/provider/agent fields are N/A by construction (no agent) |
| 2 | **Preregistration** | FILLED | `PREREGISTRATION.md` — corpora, endpoints, margins, exclusions, stop rule, deviations; the scoring basis is BINDING (see `README.md`) |
| 3 | **Gold lineage** | FILLED | `gold/` (frozen, digest-pinned) + `ttg/derive_gold.sh` + `ttg/gold_freezer.py` (the versioned freezer). Caveats published in `README.md`: gold is a **reference-patch proxy** (alternate valid implementations may touch different code); the corpora are public with two distinct lineages — `ts40` from DataCurve DeepSWE (held-out reference solutions), `py_nosphinx` from SWE-bench Lite (gold patches); see `README.md` "Two corpora, two lineages" — contamination-resistance is **by construction** (deterministic frozen-gold scoring), not task secrecy. The Python gold is thin (26/39 instances carry exactly one gold symbol → per-instance coverage is largely binary). Judge agreement is N/A (deterministic set-match) |
| 4 | **Conditions** | FILLED | `arms/arm_matrix.py` — every arm's COMPLETE flag list is code, not prose; the treatment measures the shipped default (`for_intent(Implement)` = waterfill @ 16k wire), the ablation passes explicit `--curation off --m22-levers-off`, the native floor is the in-binary `--explorer` policy (frozen parameters disclosed in its module header). Agent prompts / tool schemas / hooks are N/A |
| 5 | **State policy** | FILLED | `README.md` (store modes) + `arms/` runner manifests: FRESH vs REUSE declared per arm; REUSE arms require the scored-only corpora (the belt-drift guard is code: `assert_corpus_matches_protocol`); no-write tells recorded in run manifests |
| 6 | **Task definition** | FILLED | `corpora/*.instances.tsv` (instance lists + digests); gold = the frozen per-instance symbol sets in `gold/`; the validator is the deterministic offline scorer (`ttg/`); failure rule: non-reachers stay in the denominator (intent-to-treat) |
| 7 | **Raw trajectory** | EXPLAINED-ABSENT | No agent loop exists → there are no messages or tool calls to record. The deterministic analogue IS published: per-ranked-symbol wire positions in every report (`retrieved_wire_positions`), from which the full curve recomputes offline (`ttg/curve_recompute.py`). Boundary: tool-response ≠ whole-agent |
| 8 | **Output** | EXPLAINED-ABSENT | No agent action is produced → no final answer, patch, or abstention exists. The scored coverage verdict is the output; the offline scorer's report is the validator log |
| 9 | **Usage ledger** | EXPLAINED-ABSENT | TtG prices **wire tokens** (`ttg_wire`) — deliberately NOT provider-billed tokens. There is no provider, no cache accounting, and no dollar figure anywhere in this benchmark. Boundary: wire tokens ≠ billed tokens; payload ≠ cost |
| 10 | **Index ledger** | EXPLAINED-ABSENT | Index build economics (build time, RAM, break-even) is not a TtG endpoint: the benchmark measures coverage under a fixed wire budget *given* an index. Derivation wall-times appear in run manifests as provenance, not as an economics claim |
| 11 | **Scoring** | FILLED | Per-instance rows in every report; aggregates recomputed offline and asserted against the in-binary rollup (`ttg/rollup.py`, `ttg/acceptance.py`); paired stats per the preregistration. Judge rubric N/A |
| 12 | **Failure publication** | FILLED | Excluded instances + reasons are pinned (`corpora/`, the exclusion record); non-reachers stay in the frozen denominators (ts40 37 / py 39); every report retains its error rows |
| 13 | **Reproduction** | FILLED | **This repository is the reproduction**: `./reproduce.sh` (verify → derive → run → score → report), digest-pinned inputs (`PIN.toml`, `gold/SHA256SUMS`, `corpora/SHA256SUMS`), and third-party offline curve recomputation from report primitives (`ttg/curve_recompute.py`). The reproducible target is the **artifact** (the gold payload + the scored curves) and the pinned **committed source** — never a binary file digest (the build path bakes into the binary; see `README.md`) |
| 14 | **Longitudinal policy** | EXPLAINED-ABSENT | Static offline benchmark over public repositories: no human participants, no telemetry, no cohort — nothing to retain or attrit |

## The must-remain-separate boundaries

The rows above stay honest only if these quantities are never merged — this
benchmark never does, and quotes of it must not either:

- **wire tokens ≠ billed tokens** — no dollar or provider-cost claim exists here
- **tool-response ≠ whole-agent** — one response's tokens, not a session's
- **one query ≠ a task or session**
- **payload reduction ≠ cost reduction**
- **retrieval coverage ≠ task success** — no solve-rate claim exists here

## native_floor pricing basis (2026-09-07)

The native_floor comparator delivers SPANS (read content), so its wire price is
its source-text token count under the same shared tokenizer as the wire path
(wire ≡ read for spans; B5 §5 L154). It is genuinely wire-priced — coverage@budget
and cost-to-coverage are real values, not n/a. The floor and the treatment share
the tokenizer AND the pricing walk — ONE code path, not two implementations
agreeing (engine at `cece1486`): one `Arc<TokenCounter>`
(`crates/noodlbox-eval/src/context/evaluator.rs:127`), one production construction
(`benchmark_runner.rs:759`), one injection (`with_token_costing:834-839`); both
arms run the same `priced_walk` (packet `:715`, span `evaluate_explorer:1820-1825`
/ `:1825`); the engine comment `:1816` says why one walk — a second would leave an
inter-arm divergence unfalsifiable from the report. reach@80 is two fields:
`reach_at_80_whole_list` (uncapped) and `reach_at_80_within_32k` (capped at 32k
wire); head-only@k is omitted (span vs symbol head not comparable). The V1 floor
reference (fixture native_floor ts40/py) is from B5 §5 and the re-cert replays it
exact-to-4dp = floor HELD.
