# Pre-registration

> **Versions** — TokensToGold benchmark **V1** · harness release **v1-2.3.18** · engine **noodlbox 2.3.18**. Three numbers coexist: the benchmark scope is V1 (the launch-scope doc); the harness release is tagged `v1-2.3.18` (benchmark V1 · engine 2.3.18) — named so no tag reads as a benchmark V2, none exists yet — and carries the reach-split metric-schema change (`reach_at_80` → `whole_list` + `within_32k`); the engine is the 2.3.18 build pinned in `PIN.toml [recert.binary]`.

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

Code basis (engine at `cece1486`): the floor and the treatment share the
TOKENIZER **and** the PRICING WALK, so the comparison rests on ONE code path, not
on two implementations agreeing. `TokenCosting` holds a single
`Arc<TokenCounter>` (`crates/noodlbox-eval/src/context/evaluator.rs:127`),
constructed once in production (`benchmark_runner.rs:759`; the other two
constructions are `cfg(test)`) and injected at one point (`with_token_costing`,
`:834-839`). `evaluate_explorer` (`:1820-1825`) prices each span as its own text
through that same counter. BOTH arms run the SAME `priced_walk` — the packet path
at `:715` (via `priced_curves`) and the span path at `:1825` — and the engine
comment at `:1816` states why one walk: a second walk would leave an inter-arm
divergence unfalsifiable from the report.

reach@80 is reported as TWO qualified fields: `reach_at_80_whole_list` (the
UNCAPPED whole-list reach — the Waterfill delivery cap is a curation lever, so
this is the floor's unbounded hunt) and `reach_at_80_within_32k` (fraction with
≥ 0.8 gold covered within the 32k wire budget). head-only@k is omitted for the
floor (a span head and a symbol head are not comparable in one row).

The V1 floor reference cells (acceptance fixture, native_floor ts40/py) are
pasted from B5 §5 (within_32k ← L160/L162; whole_list ← L166/L168; Gold@32k is
the coverage decoy). The re-cert floor replays them exact-to-4dp = floor HELD
(explorer policy frozen; the rg fix only made failures loud).

### Addendum — held-out corpus retired to a public one, 2026-09-09 (founder ruling, R20-3)

The earlier private held-out monorepo was retired; the held-out confirm corpus of
record is now the public, pre-registered `payloadcms/payload` (MIT), stated
canonically in `BUNDLE.md` ("Held-out corpus (canonical statement)"). Its name is
no longer a secret, so the name-privacy apparatus (the `ttg.privacy` scrubber, the
commit-message hook, the history-scan and binary scanners, the T6 surface scans)
was deleted with this change — "held-out" is a process property, not a secrecy
one. The prior 2026-09-07 "Option 1 / not-named claim" addendum is superseded.

### Addendum — ts40 engine-vs-frozen drift, 2026-09-07 (disclosed)

Published numbers are on the frozen N=37 anchor; the 2.3.18 engine additionally
derives gold for two instances V1 could not — `effect-sse-httpapi-streaming`,
`query-persist-restored-query-state` — excluded from the published basis until
the next re-freeze. Binding stays on the frozen basis (scoring against
re-derived gold is the own-gold inflation the protocol forbids); the drift is
asserted to be EXACTLY these two (T1 `test_difference_is_exactly_the_known_addendum_drift`;
source: harness commit 47d29d7 + the drift sidecar).

### Addendum — the product arm: price what `nbx search` delivers, 2026-09-29 (before any number)

> Founder GO 2026-09-29, coordinator brief `COORD_TO_L18_TTG_BENCHMARK_FIX_2026-09-29.md`, LEDGER B64.
> Written before any product-arm number exists, and before the builds it measures exist.
> Append-only: every section above stays as recorded. This addendum changes which quantity is the headline and adds one arm. It does not change a corpus, the frozen gold, the matcher or the scoring basis.

**Why.** LEDGER B62: the published Gold@8k (ts40 78.9 %, py 83.3 %) prices `name file` lines of the engine's **untrimmed ranked list**, at about 10 tokens per row, with no JSON envelope and no packer. It does not price what an agent receives from `nbx search`. On the same builds and instances, ts40 Gold@8k is .820 on the ranked list and .352 / .519 on the product path (#1485 / #1514). The README describes `ttg_wire` as "what the response actually carried", and the engine quantity does not meet that description. This addendum makes the harness measure the delivered response.

#### 1. The product arm (`delivered`)

The harness invokes the shipped `nbx` CLI the way an agent does. There is no engine-side reconstruction.

| Row | Command | Budgets B |
|---|---|---|
| `delivered.grep` | `nbx search --intent implement --max-tokens B -- <task text>` (stdout is the default grep surface) | 4000, 8000, 32000 |
| `delivered.json` | `nbx search --intent implement --format json --max-tokens B -- <task text>` | 4000, 8000, 32000 |
| `delivered.default` | `nbx search -- <task text>`: no flags, so Explore intent, grep surface and the default compact budget | the CLI default, recorded from the build |

- `<task text>` is the instance's `problem_statement`, verbatim, as the query. This is the harness's existing raw-query convention.
- **Headline.** The public headline is `delivered.grep` at 8k and 32k: the default output shape an agent receives. `delivered.json` and `delivered.default` are reported next to it, each as its own row. Rows are never merged.
- **Cells.** One fresh cell per gold-bearing instance:
  - a fresh checkout at `base_commit`, with the `._*` files stripped;
  - a fresh `NOODLBOX_DATA_DIR`, telemetry off;
  - identical checkout directory naming across cells (LEDGER B37);
  - one `nbx analyze .`, then every search row of that instance against that one store.
- **Order and execution.** Cells run **sequentially** (EVAL-CLONE-RACE). Within a cell the row order is fixed and recorded.
- **Failures.** A failed analyze or search (rc ≠ 0) is a **failed cell**. It scores 0.0, is listed by instance, and counts against the corpus: with more than 2 failed cells, that corpus row is not publishable. An empty stdout with rc 0 is a legitimate "no hits" result and scores 0.0.

#### 2. Pricing: `ttg_wire` is the delivered bytes

- **`ttg_wire`.** The o200k_base token count of the cell's **stdout bytes, exactly as emitted**. The tokenizer is the engine's `TokenCounter` (`crates/noodlbox-eval/src/token_cost.rs`, `TOKENIZER_ENCODING = "o200k_base"`), invoked through one engine entry point, so the harness and the engine share one tokenizer authority.
- **No reconstruction.** Nothing is re-rendered, re-priced per row or estimated.
- **stderr.** It is priced the same way and reported separately as `ttg_stderr`. It is not added to `ttg_wire`: stderr carries the freshness receipt and the meta footer, which an agent harness may or may not show the model.
- **Reported per row and budget:** median, p90 and max `ttg_wire`, plus the count of cells whose `ttg_wire` exceeds B. That count is reported, never corrected: the product budgets by an estimator, not by o200k.

#### 3. Identity and matching

The matcher is unchanged: `ttg.matcher.match_gold` against the pinned frozen gold, with the two-arm rule and first-rank claiming. Only the list of delivered identities is new.

- **`delivered.json`.** The identities are the `symbols[]` rows with a non-empty `location.file_path` (`file_path:name`), then the `file_index[].rows[]` (`group.file_path:row.name`), in wire order. This is B52's `payload_items`. Nothing else in the payload is an identity. In particular, a name that appears only in a count or a `more_members` total is **not** delivered.
- **`delivered.grep` and `delivered.default`.** A grep line is `path:line:content` and carries no structured name. Its identity comes from an **identity oracle**: one extra `--format json --intent <same intent> --max-tokens 1000000` search in the same cell.
  - The oracle is never priced or scored. It only resolves names.
  - The join key is `(path, 1-based line)`: the oracle's `location.start_line + 1`, or `file_index` `row.line + 1`. Both fields are 0-based on the wire, and the grep renderer adds 1.
  - **Fail-closed.** A grep hit whose key matches no oracle row makes the cell a **failed cell** (§1). An identity is never guessed from the content text.
  - **Ambiguity.** When several oracle names share one key, the hit credits **all** of them. The headline uses that credit. Every row also reports its count of ambiguous hits and a **lower bound** that credits none. If the two differ by more than 0.5 pp on any corpus, the row carries a visible flag.
- **Metrics per row and budget:**
  - Gold@B_delivered: frozen-gold recall over the delivered identities, on the binding basis (gold-bearing instances only);
  - reach@80(B): the fraction of instances with Gold@B_delivered ≥ 0.8;
  - the `ttg_wire` statistics of §2.
  N is carried on every row, and every number is labelled with its bound. Paired comparisons use the existing `ttg.regression.compare_reports` (paired by `instance_id`, bootstrap 95 % CI, exact sign test).

#### 4. Carried over unchanged

- **Corpora:** ts40, py_nosphinx, go34 and rust43, with pinned IDs and digests.
- **Gold:** the frozen gold at the harness pin. It is never re-derived for this arm.
- **Scoring basis:** binding.
- **Cells:** fresh and sequential.
- **Builds:** release-profile `nbx` with default features (the shipped configuration), with `NOODLBOX_GIT_SHA` set to the 40-hex commit. Each binary's sha256 goes into a build receipt that the harness verifies against git history before any cell runs (the `verify-receipt` discipline, extended to `nbx`).
- **Lease:** one class, n2-standard-32. The reranker `model.lock` revision is stamped per cell. Wall times are never compared across leases.

#### 5. The old arm is renamed `ranked_list_ceiling`

- The existing noodl-eval arms (`shipped_treatment` and the rest) are reported as **`ranked_list_ceiling`**, labelled "retrieval ceiling, not delivered": the untrimmed ranked list priced as `name file` lines.
- It stays because it measures retrieval, and the G3 head-only floors are defined on it (CURRENT_GATE §1).
- Every report carries `publishable_as_delivered = false` for it. The harness refuses to render it as a headline or as a "delivered" number.
- It is **never** the public headline again.

#### 6. One definition, one name, in the engine

The engine quantity currently named `ttg_wire` (noodl-eval `evaluator.rs`: `carried_string` / `price_wire` over `flatten_context_results`) prices a reconstruction of the ranked list, not delivered bytes.
- It is **renamed** `ttg_ranked_list` in noodl-eval, and its doc comment states what it prices.
- The name `ttg_wire` then means only the §2 quantity.
- There is no alias and no second definition.

#### 7. Must-reds, before any measured number

1. **Byte sensitivity.** A delivered payload whose stdout bytes change must change `ttg_wire`. The red is a fixture where the scorer is fed a fixed per-row price (the B62 defect shape) and the test catches it.
2. **Ceiling is not publishable as delivered.** Rendering a `ranked_list_ceiling` report as a headline or delivered row must fail. The red shows the renderer accepting it without the guard.
3. **Grep fail-closed.** A grep hit with no oracle row must fail the cell, not score it.

#### 8. What is measured, and when

The builds are fixed by events, and their shas are recorded when each event happens:
- **M:** the first `origin/main` commit containing #1514's merge.
- **P:** #1485's merge commit.

Both builds run all four corpora, every row above. The existing `ranked_list_ceiling` runs on the same builds for the reconciliation table (ceiling vs delivered, per corpus).

#### 9. Publication

- **Package.** New numbers, a methodology diff against V1, and page copy in the locked claims language (`S7_CLAIMS_LANGUAGE_MEMO_LOCKED_2026-08-19`) go to the founder as a package.
- **Publishing** to noodlbox.io is the founder's action. Nothing in this addendum publishes.
- **Wording.** The published numbers describe `nbx search` as delivered. The V1 numbers stay in history, labelled as ranked-list ceiling numbers.

#### 10. What needs a new ruling

Any change to one of the following requires a dated amendment before the affected number:
- the headline row or budget;
- the identity rule (§3), including the oracle budget, if the CLI rejects `--max-tokens 1000000`;
- the failed-cell rule;
- the tokenizer;
- the corpora or the frozen gold.
