# V2 Tier A A1 publication contract

This table applies only to the model-free A1 Graphify retrieval slice. A row is
either filled by a hashed artifact or explains why the artifact does not exist
for this measurement unit.

| # | Artifact | Status | Public evidence or boundary |
|---:|---|---|---|
| 1 | Manifest | FILLED | `provenance.tsv`: benchmark date, source-table hashes, corpus/gold identities, engine commit and binary identity, Graphify version, tokenizer, run hosts, reports, and audit paths |
| 2 | Preregistration | FILLED | The dated V2 preregistration is hash-pinned in `provenance.tsv`; the later denominator correction is preserved in each frozen source table |
| 3 | Gold lineage | FILLED | `../gold/` at ggv 4 plus corpus and gold hashes; `README.md` states the reference-patch-proxy limitation |
| 4 | Conditions | FILLED | `README.md`, `results.tsv`, the hashed source tables, and native/nbx report manifests identify the query, arms, flags, versions, tokenizer, budgets, and treatment differences |
| 5 | State policy | FILLED | Fresh per-instance reindex; repository/base-commit identity is retained in the hashed corpus manifests; a single box ID is explained unavailable |
| 6 | Task definition | FILLED | Hashed corpus JSONL and frozen-gold files define inputs and scored symbols; zero-gold and build-failure handling is explicit |
| 7 | Raw trajectory | EXPLAINED-ABSENT | No agent messages or sessions exist in Tier A. Ordered retrieval results and wire positions are retained in the hashed per-instance reports |
| 8 | Output | FILLED | Hashed reports retain each ranked retrieval output. Final answers and patches do not exist because this slice has no agent loop |
| 9 | Usage ledger | EXPLAINED-ABSENT | `ttg_wire` is retrieval-response accounting, not provider-billed usage; there is no model or dollar ledger |
| 10 | Index ledger | EXPLAINED-ABSENT | Host identity is retained as provenance, but build time, memory, disk, and amortization are outside this slice's endpoint |
| 11 | Scoring | FILLED | Exact per-corpus tuples are in `results.tsv`; `RESULTS.md` is verified from it; the source tables record offline `ttg.rollup` recomputation |
| 12 | Failure publication | FILLED | Rust Graphify's seven ruff build failures, six-gold-bearing denominator loss, N=34 failure subset, and nonmatched status are public |
| 13 | Reproduction | FILLED | `verify.sh` checks the package offline and can hash-audit the retained source tree; source tables record the exact recomputation command |
| 14 | Longitudinal policy | EXPLAINED-ABSENT | Static public corpora, no participants, no telemetry cohort, and no retention or attrition endpoint |
| 15 | Right of reply | FILLED | Exact config/version provenance and a standing issue-based correction invitation appear in `README.md` |

The boundaries are binding: wire tokens are not billed tokens; one retrieval
response is not a task or session; retrieval coverage is not task success;
payload size is not cost; and this model-free comparison is not an isolated
causal attribution study.

Tier B whole-agent work and the CodeDB appendix are pending and have no result
in this package.
