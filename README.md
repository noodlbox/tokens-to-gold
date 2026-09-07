# tokens-to-gold

> **Versions** — TokensToGold benchmark **V1** · harness release **v1-2.3.18** · engine **noodlbox 2.3.18**. Three numbers coexist: the benchmark scope is V1 (the launch-scope doc); the harness release is tagged `v1-2.3.18` (benchmark V1 · engine 2.3.18) — named so no tag reads as a benchmark V2, none exists yet — and carries the reach-split metric-schema change (`reach_at_80` → `whole_list` + `within_32k`); the engine is the 2.3.18 build pinned in `PIN.toml [recert.binary]`.

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

**The `--binary` lines need an engine this project does not supply.** `noodl-eval`
is an internal tool and is not published, so the reproduction path open to a third
party is the FIRST line: `--score-only` over the sha-pinned release reports, plus
offline curve recomputation (`ttg/curve_recompute.py`). That verifies every
published number without the engine. The `--binary` forms re-RUN the arms, which
is a different thing from verifying them, and they are here for whoever holds the
engine. This absence is stated rather than left to be discovered — see
`PIN.toml [recert.released_binary]` for the reason and `BUNDLE.md` row 13.

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

**Running the acceptance suite.** The one supported entry is `./reproduce.sh
verify` — it fetches the pinned v1-2.3.18 release attachments with the repo token,
sha-verifies each, and runs the acceptance suite with `TTG_REPORTS_DIR` pointed
at the fetched dir. It FAILS LOUDLY if the fetch is missing — no skip-if-absent
anywhere. On a fresh clone this is the whole ceremony. To run the suite by hand
against an existing report tree, set the env yourself (the fetched dir is the
published surface — the certified reports, one per arm×corpus):

```sh
./reproduce.sh verify                                        # supported path; a clone runs exactly this
TTG_REPORTS_DIR=<dir-of-reports> python3 -m unittest discover -s acceptance -p 'test_*.py' -t .
```

### Two corpora, two lineages

The two tiers come from **different benchmarks** and are never blended:

- **`ts40`** — 40 tasks from [DataCurve DeepSWE](https://deepswe.datacurve.ai/)
  (per DeepSWE's own task metadata: 35 TypeScript + 5 JavaScript). Its
  reference patch is DeepSWE's **held-out reference solution** — a reference
  implementation DeepSWE's behavioral verifier never grades against, so
  alternate correct implementations are accepted by design.
- **`py_nosphinx`** — 40 Python tasks from **SWE-bench Lite** (17 pytest,
  23 scikit-learn; the source pool's 16 sphinx-doc tasks excluded). Its
  reference patch is SWE-bench's **gold patch**, the historically merged fix.

In both tiers the task's problem statement is the single retrieval query,
verbatim, and gold is the reference patch's touched lines resolved to
code-graph symbol definitions, frozen once per corpus.

### Gold is a reference-patch proxy

Gold is derived from the symbols the **reference patch** touched (per
lineage above). It is *not* human-labelled retrieval ground truth. A symbol
a competent engineer would want to read, but which the reference patch did
not modify, is not gold and is not credited. The proxy caveat is *stronger*
for `ts40`: DeepSWE accepts alternate implementations by design, so valid
solutions may touch different code than the reference.

### What a third party can and cannot reproduce

The eval crate is **closed source** and the `noodl-eval` engine is an internal
tool that is **not published**. What a third party reproduces without it is
**L4 (scoring)**: the sha-pinned release reports re-scored against the shipped
frozen gold, plus the TtG curves recomputed offline from report primitives. That
covers every published number. **L3 (arm runs)** and, with `--rederive-gold`,
**L1 (gold derivation)** require the engine, so they are available to whoever
holds it and not otherwise. This package pins the engine's identity so the
numbers' producer is cross-checkable; it claims neither a buildable source tree
nor a downloadable binary.

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

## Run it on your own repo

The gold model transfers to any **public repository with a merged PR** — the
PR's diff is the reference-patch proxy for "the symbols this change actually
needed", derived by the **same versioned freezer pipeline** as the published
numbers (there is no manual-gold path).

**This path requires the noodlbox CLI**, which analyses the repository and runs
the arms; the corpus-building and scoring steps below are this package's and need
nothing else. No claim is made here about how or when that CLI is obtained:

```sh
# 1) one merged PR becomes a one-instance corpus (title+body = the query)
python3 -m ttg.cli from-pr --repo owner/name --pr 123 --out runs/mine

# 2..3) it prints the exact derive / run / score commands from there:
#    derive+freeze YOUR gold (full index of the pre-change checkout),
#    run the section-5 arms (shipped treatment / levers-off / native floor),
#    score against YOUR frozen gold:
python3 -m ttg.cli score-own --report runs/mine/shipped_treatment.json \
   --gold runs/mine/gold/frozen_gold_own_repo.json
```

Read your readout with the same honesty rules as the published page: the
gold is a reference-patch proxy; a body-less PR is a THIN query (disclosed);
one instance is a coarse, largely binary readout (disclosed) — run several
PRs before reading a trend. Wire ≠ billed tokens; coverage ≠ task success.

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

## go34 — a disclosed exclusion rate

34 tasks; 30 scored. 4 excluded as zero-gold — 11.8 %, above the pre-registered
10 % alarm; all four are new-file-dominated reference patches (50–100 % of
touched files created by the patch), for which the reference-patch proxy has no
pre-existing symbols to score. The alarm fired as designed; the cause is
disclosed here. The `new_file_fraction` column in `corpora/go34.manifest.jsonl`
lets you recompute it.

## Changelog

- **2026-09 re-certification.** Added `ttg/paired_stats.py` (paired bootstrap CI + exact sign test), homed byte-identical from the m23gate harness (sha `4d359404…`). V1 documented this tool as shipped; it was not — the regression report now carries per-metric paired 95% CI + sign test alongside the ±2.75pp floor.

## Commit-message privacy guard

The canonical claim about the held-out corpus is stated once in `BUNDLE.md`
("Held-out corpus (canonical claim)"): **it is not named in any public
artifact** — a mechanical not-named property, enforced by the guards below, not
a secrecy claim. Commit messages ship with a public clone, so the name must
never enter git history. Arm the guards once:

```sh
bash scripts/setup.sh
```

That sets `core.hooksPath` to `scripts/git-hooks` and prints the release gate.
`scripts/git-hooks/commit-msg` then refuses any message that names the corpus
(checked via `ttg.privacy`, so the hook never spells it), reporting the resolved
token *mode* — never the value — and distinguishing a violation from a check that
could not run. Before an internal artifact leaves the machine, run the release gate
`python3 -m ttg.cli scan-binary --path <noodl-eval>` (a byte scan; the eval
binary once carried the name in embedded strings).
