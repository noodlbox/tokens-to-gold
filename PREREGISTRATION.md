# Pre-registration

Fixed **before** the reported runs. Anything decided after the numbers were
seen is not in this file.

## Corpora

| Corpus | Language | Instances | Gold-bearing (scoring basis) |
|---|---|---|---|
| `ts40` | TypeScript | 40 | 37 |
| `py_nosphinx` | Python | 40 | 39 |

Instance IDs are pinned in `corpora/*.instances.tsv` with digests. Both are
derived from the public SWE-bench-style deep-swe set.

> **Lineage correction (2026-09-05, pre-publication provenance audit; no
> number, instance list, metric, or criterion changes).** The line above
> blankets two distinct lineages under one internal corpus-family label
> ("deep-swe"). Verified byte-for-byte against the source datasets:
> `ts40` is 40 tasks from **DataCurve DeepSWE** (not SWE-bench; 35 TS + 5 JS
> per DeepSWE task metadata), each `patch` byte-identical to that task's
> held-out `solution/solution.patch` and each `problem_statement` to its
> `instruction.md`. `py_nosphinx` is 40 tasks from **SWE-bench Lite**
> (17 pytest + 23 scikit-learn; the source pool's 16 sphinx-doc tasks
> excluded), fields byte-identical to Lite's records. See `README.md`
> "Two corpora, two lineages". The pinned instance IDs and digests above
> are unchanged — this note corrects the prose attribution only.

A third, **private** corpus is held out and is deliberately absent from this
package — no name, ID, number, or example. The criterion that depends on it
(criterion 4, monorepo behaviour) is reported as **explained-absent** rather
than silently dropped.

## Measured quantities

- `Gold@B_wire` for B ∈ {2k, 8k, 32k}
- `reach@c` for c ∈ {50, 80, 100}
- median `TokensToGold@c` over reachers
- wire clip: 32,000

## Scoring basis (BINDING)

Gold-bearing instances only. Fixed in advance, for the stated reason: an
instance with no gold has no retrieval question to answer. See README for
the measured consequence.

## Match rule

An emitted `file:name` identity matches gold under a two-arm rule:

1. exact `(name, file_path)` equality;
2. same name, path equal after repo-relative normalization (`.` and `//`
   collapsed, trailing `/` dropped, `..` rejected; a single leading `/` is
   allowed on **authored gold only**, never on retrieved paths).

Each gold symbol is claimed at most once, at the first rank that matches it.
Paths that are not repo-relative yield **no verdict** and are counted
separately — a path-domain mismatch is not a retrieval miss.

## Arms

The reported comparison is **`shipped_treatment` vs `levers_off_ablation`**.

- **`shipped_treatment`** — the shipped Implement config, whose curation
  default is `Waterfill{char_budget: 65536}`. Run fresh with `--reindex`.
- **`levers_off_ablation`** — *levers-off base-config*: Implement with
  curation **Off** and the M22 admission levers **Off**. The full base, i.e.
  the honest "what does the whole shipped config buy" ablation. Run against a
  warm store on the scored-only corpus.

Seven further curation arms (`a0_off`, `wf_b1..b3`, `pfc_b1..b3`) form the
sweep behind `--arms all`. `a0_off` is a **curation-only** decomposition and
its numbers are never reported as the levers-off baseline.

## Criteria

| # | Name | Status |
|---|---|---|
| 1 | recall non-inferiority (margin 2.0pp) | public |
| 2 | coverage | public |
| 3 | cost / reach (reach@80, lift ≥ 15pp) | public |
| 4 | monorepo behaviour | **explained-absent** (private held-out corpus) |

Superiority is claimed at `head_only_at_25` (p=0.0078). It is **not** claimed
at py `head_only_at_10` (p=0.125, CI spans 0); the harness annotates that
metric rather than letting it read as a win.

## Gold protocol

Gold is derived **once** per corpus from a `--reindex` pass, frozen, and
stamped into every arm. Arms never score against their own re-derived gold —
that inflated recall by ~9pp when it was allowed. The freeze preserves report
order and **never sorts the symbol lists**; the frozen file is digest-pinned.

Gold is a **reference-patch proxy**, not human-labelled ground truth.
