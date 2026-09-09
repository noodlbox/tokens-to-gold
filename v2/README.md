# TokensToGold V2 Tier A — A1 Graphify slice

This package publishes the deterministic A1 retrieval comparison across four
corpora: a competent native floor, the shipped noodlbox retrieval response, and
Graphify. It is one completed slice of Tier A, not the wider preregistered
competitor matrix.

The exact per-corpus values are in [`results.tsv`](./results.tsv). The readable
view in [`RESULTS.md`](./RESULTS.md) is generated from that file and checked
offline. Results are never pooled across languages.

## What the 8K point means

The 8K point is a fixed retrieval-output observation budget, not an agent or task cutoff.
It asks how much frozen, edit-relevant reference-patch gold appeared within the
first 8,000 `ttg_wire` tokens of one retrieval response. Tier A has no agent
loop, patch attempt, test execution, turn limit, or model judge. Measurements
outside the fixed 2K, 8K, and 32K observation points are outside this
publication.

Accordingly, this evidence supports per-corpus retrieval-efficiency statements
only. It does not establish billed-token savings, dollar savings, task success,
patch correctness, or an isolated causal effect of graph structure.

Tier B whole-agent adaptive retrieval and patch success: **PENDING**.

CodeDB appendix: **PENDING**.

Neither pending study contributes a result to this package.

## Frozen measurement contract

- **Query:** each task's problem statement, unchanged across arms.
- **Truth:** gold-derivation version 4, frozen before scoring. Gold is the set of
  symbols touched by a reference patch and is a localization proxy; another
  valid implementation can touch different code.
- **State:** fresh `--reindex` per instance, with repository and base-commit
  identities in the hashed corpus manifests. There is no single reusable box ID
  to report.
- **Unit:** `ttg_wire`, tokenized with `o200k_base` for every arm.
- **Observation budgets:** 2,000, 8,000, and 32,000 wire tokens.
- **Coverage:** mean per-instance frozen-gold coverage at the named observation
  point.
- **TtG@80 reach:** fraction of the declared denominator reaching 80% frozen-gold
  coverage.
- **TtG@80 median:** median wire position among the instances that reached 80%;
  the reach fraction must be read beside it.

The native floor uses `rg`/glob discovery plus targeted source spans. The nbx
row uses the shipped default at engine commit
`3723be44085ab470bad55241853276f85568291e`; both were produced by one binary
with SHA-256
`d02270de07b1f0d786ef49c80e71848fe57df4109a06eb5a3804cb8b68f66151`.
The shared query, truth, tokenizer, and scorer do not make this a same-engine
ablation: implementation, configuration, and host differences remain disclosed
conditions, not a basis for isolated causal attribution.

Graphify is pinned to `graphifyy==0.9.28` with `--code-only`. Its 32K query and
documented 2K default are separate rows. A returned node is a pointer: the
adapter reads its source body with the native floor's span policy and prices
that body in retrieval order. The Graphify wheel and transitive dependency
hashes were not captured, so this arm is version-pinned rather than hash-pinned.
Graphify 0.9.56 was not used; it is reserved for a separately preregistered
sensitivity study.

The exact arm commands are preserved in the frozen source tables and native/nbx
report manifests listed in [`provenance.tsv`](./provenance.tsv). The Graphify
arm runner did not emit a separate per-report manifest; its source table, report
hash, fixed version, flags, query budget, and scorer identity are all retained.

## Denominators and the Rust exception

Python uses frozen-gold N=39, TypeScript N=37, Go N=30, and the Rust native-floor
and nbx rows use frozen-gold N=40. The post-run denominator audit found that the
raw report-level aggregate fields included successful rows outside those frozen
sets. Those aggregate fields are retained in the raw files for history but are
not a numeric source for this publication. The four denominator-corrected,
hash-pinned source tables are the authority for `results.tsv`.

Graphify failed to build all seven `astral-sh/ruff` instances in `rust43`. Six
were gold-bearing:

```
astral-sh__ruff-15309  astral-sh__ruff-15330  astral-sh__ruff-15356
astral-sh__ruff-15394  astral-sh__ruff-15443  astral-sh__ruff-15543
```

The seventh, `astral-sh__ruff-15626`, was zero-gold. The Rust Graphify rows
therefore use the 34 gold-bearing instances they built. They are explicitly
nonmatched against the native-floor and nbx N=40 rows. No Rust Graphify
comparison is presented as matched; the matched Rust reading is nbx versus the
native floor on N=40.

## Run and audit provenance

Python floor/nbx ran on `golden-hermit` (`n2-standard-32`,
`cbx_551e68e1b7fa`); Python Graphify ran on `harbor-hermit`
(`e2-standard-8`, `cbx_b1746817aab7`). The TypeScript, Go, and Rust arms ran on
`swift-krill` (`n2-standard-32`, `cbx_aaed7ae9b582`). Hardware is run
provenance, not an explanation for observed differences.

[`provenance.tsv`](./provenance.tsv) records SHA-256 identities and audit paths
for the four frozen source tables, corpora, frozen gold, per-instance reports,
run headers, corpus manifests, and native/nbx report manifests. The raw reports
are retained evidence assets rather than duplicated into Git. Their per-instance
rows support offline recomputation; their original aggregate fields are not the
published values.

From this repository:

```sh
./v2/verify.sh
./v2/verify.sh --self-test
```

With the sibling `noodlbox-wiki`, `tokens-to-gold`, and `worktrees` source tree
available beneath one directory, verify every retained source byte too:

```sh
./v2/verify.sh --audit-root /path/to/noodlbox
```

The verifier rejects result-file drift, missing provenance, a Rust denominator
or comparability change, rendered-table drift, absent 8K scope language, and any
claim that Tier B or CodeDB has results.

## Limits and correction path

This slice compares retrieval delivery against a reference-patch proxy. It does
not measure index economics, provider usage, agent behavior, or patch outcomes.
The separate nbx full/progressive row was not run in this slice. Graphify's Rust
build failures and missing package hashes remain disclosed limitations.

To correct a result, first restamp its source table, then update that table's
hash and the exact row in `results.tsv`, regenerate `RESULTS.md`, refresh
`SHA256SUMS`, and rerun both verifier modes. A displayed value cannot be edited
independently of the frozen result file.

Ran your tool wrong? Open an issue on this repository; we will rerun with your
correction and update the published numbers.
