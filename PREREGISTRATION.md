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

### Addendum — rust43 re-certification, 2026-09-06 (before any rust43 number)

Written before any rust43 arm number is read (R-R43-3). rust43's basis changed
between two derives, and the reason is recorded here so the shift is not mistaken
for instability in the corpus.

- **run9 (2026-09-05), binary sha `79c5e9b6…`:** 8/43 carried no gold, decomposed
  as **6 errored** + **2 genuine zero-gold**. The 6 errored were NOT scored, so
  the honest zero-gold rate was 2/(43−6) = 2/37 = 5.4% — the raw "18.6%" was an
  artifact of counting errors as zero-gold (fixed: errored is now a third class,
  `TTG_RECERT_RULING_RUST43_ALARM` item 2). The 6 errored, by cause:
  - **5 — analyzer bug (fixed):** `uutils__coreutils-6377/6575/6682/6690/6731`
    failed the Rust module resolver on coreutils' member-less `[workspace]`.
    Fixed in `module_resolver.rs` (commit `cac984c17`); these now index clean.
  - **1 — nondeterministic race (NOT fixed, did not recur):**
    `astral-sh__ruff-15626`, a graph-manifest publication-authority mismatch. It
    simply did not reappear in run10b; it is an OPEN follow-up
    (`artifacts/FOLLOWUP_ruff15626_publication_authority_race_2026-09-06.md`), not
    a resolved defect.
- **run10b (2026-09-06), fixed binary sha `<recorded in the report header>`:**
  **3/43 zero-gold (7.0%) — within budget, CERTIFIED**, no ruling required. The
  scored basis is N = 43 − 0 errored − 3 zero-gold = **40** (to be confirmed
  against run10b's derived report at retrieval). The two genuine zero-gold from
  run9 (`tokio-rs__axum-1730`, `tokio-rs__tokio-4384`) carry over; the third is
  identified at retrieval.
- **Why N differs from run9's decomposition:** 6 instances that were errored in
  run9 resolved in run10b — 5 by the analyzer fix, 1 by non-recurrence of the
  race. The analyzer-fixed 5 are a genuine correction; the 1 is unobserved, not
  corrected, and remains open.
- **new_file_fraction (R-R43-4):** the genuine zero-gold instances are NOT
  new-file-dominated (unlike go34's) — their reference patches modify existing
  files but touch no resolvable symbol definition. Reported alongside so the
  proxy limit's second shape is visible.


### Addendum — ts40 analyzer improvement observed in re-derivation, 2026-09-06

The run10b drift sidecar re-derived ts40 and found the 37 gold-bearing instances
byte-identical to the frozen anchor (37/37, 0 drifted). It additionally derived
gold for two instances that V1 recorded as **errored**, not zero-gold:
`effect-sse-httpapi-streaming` and `query-persist-restored-query-state` (both
tagged `errored` in `corpora/ts40.instances.tsv`; V1's basis is 37 of 38
non-error rows). The August binary ERRORED on their derivation; the 2.3.18
binary derives them. This is an **analyzer improvement**, not new gold against a
zero-gold record.

How it ships (ruling 2026-09-06):
- (a) ts40's regression numbers stay on the **frozen N=37 anchor** (R2/U2,
  unchanged) — the anchor is not re-frozen.
- (b) the drift report and this addendum state the two as **"errored in V1,
  derivable now"**, with their new gold sizes (from the run10b derived report at
  retrieval).
- (c) **No page note.** The page's scored N stays 37 and the exclusions line
  stays as V1 wrote it; the improvement is a harness/README fact, not a headline.
- (d) whether a FUTURE re-freeze at N=39 is warranted is a **separate ruling
  after the arms**, not this run.

### Addendum — native_floor pricing basis, 2026-09-07 (before any floor number is pinned)

The native_floor (rg + targeted reads) comparator delivers SPANS, not symbols. A
span is read content, so its wire price IS its source-text token count under the
SAME shared tokenizer as the curated wire path (`TokenCosting.counter`, one
`Arc<TokenCounter>`, evaluator.rs:127) — wire ≡ read for spans. The floor is
therefore genuinely wire-priced: its coverage@budget and cost-to-coverage are
real wire values, never a measured zero, and it is the same R5 Explorer control
as V1 (`B5_PAGE_SKELETON_2026-08-20.md` §5, L154; stamp L156, 2026-08-26 pinned
official binary).

reach@80 is reported as TWO qualified fields: `reach_at_80_whole_list` (the
UNCAPPED whole-list reach — the Waterfill delivery cap is a curation lever, so
this is the floor's unbounded hunt) and `reach_at_80_within_32k` (fraction with
≥ 0.8 gold covered within the 32k wire budget). head-only@k is omitted for the
floor (a span head and a symbol head are not comparable in one row).

The V1 floor reference cells (acceptance fixture, native_floor ts40/py) are
pasted from B5 §5 (within_32k ← L160/L162; whole_list ← L166/L168; Gold@32k is
the coverage decoy). The re-cert floor replays them exact-to-4dp = floor HELD
(explorer policy frozen; the rg fix only made failures loud).

### Addendum — held-out corpus claim, 2026-09-07 (founder decision, Option 1)

The single canonical claim about the held-out corpus lives in `BUNDLE.md`
("Held-out corpus (canonical claim)"); this pre-registration references it rather
than restating it, so the four copies cannot drift. The claim is literal absence
— a mechanical "not named" property, never confidentiality and never
non-derivability (the corpus is itself a private repo, so the derivability of its
name grants nothing). Because the claim is that narrow, the T6 privacy scan, the
commit-message hook, and the history-scan CLI (R18b) are its SOLE evidence, not a
defence in depth — the narrow claim raises the load on those guards. The harness
keeps its in-module name fragments and the explicit-mode resolver is unchanged
(Option 1, final).

### Addendum — ts40 engine-vs-frozen drift, 2026-09-07 (disclosed)

Published numbers are on the frozen N=37 anchor; the 2.3.18 engine additionally
derives gold for two instances V1 could not — `effect-sse-httpapi-streaming`,
`query-persist-restored-query-state` — excluded from the published basis until
the next re-freeze. Binding stays on the frozen basis (scoring against
re-derived gold is the own-gold inflation the protocol forbids); the drift is
asserted to be EXACTLY these two (T1 `test_difference_is_exactly_the_known_addendum_drift`;
source: harness commit 47d29d7 + the drift sidecar).
