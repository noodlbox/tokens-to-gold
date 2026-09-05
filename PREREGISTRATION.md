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

## Re-certification + Go/Rust tiers — 2026-09

> ACKED — rel2-t2g, 2026-09-05 18:30. Fixed before any derive/arm run.
> Append-only: the V1 section above (its corpora, numbers, metrics, criteria) is
> unchanged. This section pre-registers (a) re-certifying the shipped CLI at a
> new version and (b) two new language tiers.

**Certification binary.** `noodl-eval` built from the **v2.3.18** tag (tag +
commit + binary sha256 recorded in every report header, alongside
`eval features = rust-analysis`). Rust analysis is **ON**, matching the shipped
product's default (`nbx` `default = ["rust-analysis"]`) — the certified numbers
must describe the config users run. "As shipped" is the headline framing.

**New corpora** (single lineage each; instance IDs + digests pinned; the private
JSONLs stay in the project's `corpora/`, the public package ships instance lists
+ digests only):

| Corpus | Language | Source | Instances | Gold-bearing (scoring basis) |
|---|---|---|---|---|
| `go34` | Go | DataCurve DeepSWE (`language = "go"`) | 34 | confirmed on derive |
| `rust43` | Rust | SWE-bench Multilingual (test split) | 43 | confirmed on derive |

Digests: `go34.jsonl` sha256 `3f221cee…`, `rust43.jsonl` sha256 `32661b0c…`.
N and any per-instance exclusions (errored / zero-gold) are recorded here as a
dated addendum **before** the numbers exist. A tier is NO-GO for launch if its
zero-gold rate exceeds the pre-registered `ZERO_GOLD_ALARM_RATE = 10%`; that
escalates (whitelist vs version-bump vs language-scope), it does not silently
publish. `is_definition_kind` (the gold-kind whitelist) is **unchanged** —
extending it bumps `DERIVATION_VERSION` and retires the signed TS/Py numbers.

**Regression axis (ts40, py_nosphinx).** The comparable quantity is the new
binary's arms scored against the **existing frozen gold** with the shipped
scorer — gold held fixed, not re-derived. A fresh `--reindex` re-derivation runs
as a **sidecar**, per-instance SET-MATCH vs the frozen gold; derivation drift is
a reported finding, never silently re-frozen. Regression floor is the
pre-registered `NOISE_FLOOR = 2.75pp`.

**Comparability is decided by measurement, not assumption.** The provisioning
manifest records `rs_file_count` per checkout (`.rs` files on disk, excluding
nothing — vendored included). If every ts40 + py_nosphinx checkout is `0`, the
rust-ON certification binary is discovery-equivalent to a rust-OFF build for
those corpora and one binary certifies the regression. If any is `> 0`, a
rust-OFF (`--no-default-features`) build is ALSO run for ts40/py: its numbers
are the Aug-20-comparable **regression** numbers, the rust-ON numbers are the
**as-shipped** numbers, reported separately and never merged (a
must-remain-separate row: "same-config vs as-shipped"). go34/rust43 have no
Aug-20 anchor → rust-ON only.

**Metrics / arms / claims language** are the V1 set, unchanged: `Gold@{8k,32k}_wire`,
head-only `@k`, `TokensToGold@80` (reach + median among reachers), per-language,
N-carried, bound-labelled; whole-list recall stays internal. Arms: shipped
treatment, levers-off ablation, native floor. Gold protocol as above (derive
once, freeze, never sort, digest-pinned; reference-patch proxy).

### Addendum — go34 zero-gold alarm, 2026-09-05 (before any go34 number)

Written BEFORE any go34 arm number was read, per the alarm's own escalation
rule. The tier's derivation fired the pre-registered alarm and was adjudicated:

- **Rate:** 4 of 34 instances derived zero gold = **11.8 %**, above the
  pre-registered `ZERO_GOLD_ALARM_RATE = 10 %`.
- **The four:** `dasel-html-document-format`, `etree-xml-diff-patch`,
  `go-critic-doc-link-checker`, `wazero-multi-module-snapshots`.
- **Cause (measured, not asserted):** all four are *new-file-dominated*
  reference patches — 4/4, 6/8, 2/4 and 13/14 of the files they touch are
  created by the patch, against a 0.32 mean new-file fraction across the 30
  instances that do carry gold. Gold resolves a patch's changed lines to symbol
  definitions in the **pre-change** checkout, so a file the patch creates has no
  pre-existing definition to score. Zero gold is the *correct* derivation for
  such an instance.
- **Not an analysis defect:** the same binary derived 207 gold symbols across
  the other 30 Go instances, and reports `go` and `rust` among its analysis
  languages.
- **Ruling:** certify go34 at **N = 30** with the rate and cause disclosed —
  `artifacts/TTG_RECERT_RULING_GO34_ALARM_2026-09-05.md`. The gold-kind
  whitelist is **unchanged**; extending it would bump `DERIVATION_VERSION`,
  retire the signed TS/Py numbers, and could not help, since these symbols do
  not exist at `base_commit` under any whitelist.
- **Scoring basis:** N = 30 gold-bearing instances, exactly as N = 37 / 39 are
  for ts40 / py_nosphinx. The four are excluded as zero-gold, not scored 0.0.

Every corpus's public manifest now carries a `new_file_fraction` column, so a
third party can recompute this explanation from the reference patches alone.
