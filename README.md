# tokens-to-gold

A reproducible benchmark for **retrieval efficiency**: how many tokens must
reach a coding agent's context before the symbols it actually needs are in
there.

Two curves are measured per instance:

| Curve | Meaning |
|---|---|
| `ttg_read` | the read-everything ceiling — what it costs to just read the files |
| `ttg_wire` | what the response actually carried |

## The one command

```sh
./reproduce.sh --score-only --report-dir <dir-of-reports>          # score existing reports
./reproduce.sh --binary <noodl-eval> --corpus-dir <dir> --store <dir>   # run + score
./reproduce.sh ... --arms all          # the full 7-arm sweep (14 cells)
./reproduce.sh ... --rederive-gold     # also re-derive the frozen gold (slow)
```

Stages: **verify → (derive) → run → score → report.**

## Read this before quoting a number

### The scoring basis is BINDING

There are three candidate denominators per corpus and all three sound
defensible:

| Corpus | corpus instances | non-error results | **gold-bearing (BINDING)** |
|---|---|---|---|
| `ts40` | 40 | 38 | **37** |
| `py_nosphinx` | 40 | 40 | **39** |

**The denominator is the gold-bearing count.** An instance whose reference
patch touched no resolvable symbol has no gold; scoring it as 0.0 measures
the *corpus*, not the engine.

This matters because **the engine's own rollup averages over every non-error
row**, so a number read off a report header is on the wrong basis:

| | binding (n=37 / 39) | report basis (n=38 / 40) |
|---|---|---|
| `ts40` Gold@8k_wire | **0.7891** | 0.7684 |
| `ts40` reach@80 | **0.7838** | 0.7632 |
| `py` Gold@8k_wire | **0.8333** | 0.8125 |
| `py` reach@80 | **0.8974** | 0.8750 |

The **numerators are identical** on both corpora and both quantities — the
entire difference is the denominator. `reproduce.sh` therefore always prints
both columns with the basis labelled, so a difference cannot be mistaken for
a discrepancy.

The binding denominator comes from the **pinned frozen gold file**, never
from the report's own embedded gold. On a fresh `--reindex` run the two
coincide; on a **reuse** run they do not — the py ablation report embedded
gold for only 26 of 39 instances, and scoring on that basis inflates
`Gold@8k` by **+19.23pp**.

### Acceptance

`acceptance/MEASURER_V1_REFERENCE_NUMBERS_2026-08-20.json` is the
authoritative record: two arms x two corpora x six locked metrics. Replay
must land **exactly to four decimals** — scoring is deterministic set-match
against a frozen denominator, so there is no noise to absorb. Only a fresh
`--rederive-gold` run may move, and then only within the pre-registered
2.75pp floor.

```sh
python3 -m ttg.cli accept --report <r> --corpus ts40 --arm shipped_treatment
```

### Gold is a reference-patch proxy

Gold is derived from the symbols the SWE-bench **reference patch** touched.
It is *not* human-labelled retrieval ground truth. A symbol a competent
engineer would want to read, but which the reference patch did not modify,
is not gold and is not credited.

### What a third party can and cannot reproduce

The eval crate is **closed source**. You reproduce **L3 (arm runs) → L4
(scoring)** from a **released binary** plus the shipped frozen gold, and — with
`--rederive-gold` — **L1 (gold derivation)** from that same released binary.
This package pins the binary's identity; it does not claim a buildable source
tree.

**Binary SHA is not a reproduction target.** `OUT_DIR` bakes the absolute
build path into the binary, so its SHA is a function of where it was built.
The reproduction target is the **frozen-gold payload plus the claim-bearing
header fields**, which `verify-gold` and `--rederive-gold` check.

## The arm matrix

Seven curation arms × two corpora = 14 cells. The default is the two headline
cells (treatment + A0): reproducing the *claim* should be cheap, reproducing
the *sweep* should be possible.

**The published baseline is `levers_off_ablation`** — *levers-off
base-config*: Implement with curation **Off** and the M22 admission levers
**Off**. That is the full base config, and it is what produced the pinned
reference numbers. `a0_off` is a separate sweep cell (curation-only
decomposition); **its numbers are never labelled levers-off.**

`shipped_treatment` passes **no** `--curation` flag on purpose: it measures
the shipped default, which *is* `Waterfill{char_budget: 65536}`. That
omission is declared in the arm table (`Curation.SHIPPED_DEFAULT`), so an
*accidental* omission remains impossible.

| Arm | Policy | Budget | Flags |
|---|---|---|---|
| `shipped_treatment` | shipped default | 65536 | *(none — declared)* `--reindex` |
| `levers_off_ablation` | off | — | `--curation off --m22-levers-off` |
| `a0_off` | off | — | `--curation off` |
| `wf_b1/b2/b3` | waterfill | 20k/18k/16k | `--curation waterfill:<chars>` |
| `pfc_b1/b2/b3` | perfilecaps | 20k/18k/16k | `--curation perfilecaps:32,256,<chars>` |

`char_budget(arm, corpus) = base_20k[corpus] × factor[arm]`, so the grid is
2-D (`ts40` base 90320, `py_nosphinx` base 93000).

> **Do not invoke an arm by omitting `--curation`.** An absent flag does *not*
> mean "off" — it takes the Waterfill treatment, which silently converts the
> baseline into a treatment arm and destroys the lift claim. Historical
> provenance from before this changed still asserts the opposite. The harness
> makes omission structurally impossible: every arm's flags come from
> `arms/arm_matrix.py`, and `run_arm.sh` records the full invocation.

## Layout

```
reproduce.sh        the one command
ttg/                scoring: comparable_path, matcher, rollup, curve_recompute,
                    report_io, gold_freezer, derive_gold.sh, cli
arms/               arm_matrix (data) + run_arm.sh + run_matrix.sh
corpora/            pinned instance manifests + digests
gold/               frozen gold + digests
tests/              the must-red suite (negative controls; run with unittest)
PIN.toml            artifact pins (populated at packaging)
BUNDLE.md           the 14-row publication contract: every row filled or
                    explained-absent — what ships with every public number
```

```sh
python3 -m unittest discover -s tests -t .
```
