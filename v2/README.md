# TokensToGold V2 Tier A — A1 Graphify publication candidate

This directory is the unpublished candidate package for the deterministic A1
retrieval comparison across four corpora. It contains descriptive point
estimates for a competent native floor, the shipped nbx retrieval response, and
two configurations of Graphify. Four configurations represent three systems.
Results are never pooled across languages.

[`authority.json`](./authority.json) is the sole machine-readable authority for
result tuples, corpus identities, denominators, arm metadata, measurement units,
and gate status. [`RESULTS.md`](./RESULTS.md) and
[`STATUS.md`](./STATUS.md) are generated views. The artifact ledger is
[`provenance.tsv`](./provenance.tsv).

The structured status view is binding. In particular, it keeps publication,
public evidence retrieval, public reproduction, preregistered uncertainty, and
the separate follow-on studies open until their own evidence is accepted.

## Measurement boundaries

The 8K point is a fixed retrieval-output observation budget, not an agent or
task cutoff. It asks how much frozen, edit-relevant reference-patch gold appeared
within the first 8,000 `ttg_wire` tokens of one retrieval response. Tier A has no
agent loop, patch attempt, test execution, turn limit, or model judge.

Gold coverage is observed at exactly 2K, 8K, and 32K `ttg_wire` checkpoints,
tokenized with `o200k_base`. Reach@80 and median-to-80 are different: they scan
the complete delivered response and may exceed 32K wire tokens. Their serialized
field name and rendered table both say `whole_response` so they cannot be read
as within-32K reach.

Graphify's `--budget` is also a different unit. Pinned Graphify 0.9.28 estimates
backend query tokens as approximately three characters per token. The authority
therefore records `backend_query_budget_approx_tokens`, never `ttg_wire`, for its
32K and default 2K configurations. The adapter expands returned node pointers
into source bodies and prices that delivered body stream separately with
`o200k_base`.

Accordingly, this evidence supports descriptive, per-corpus retrieval-efficiency
statements only. It does not establish billed-token savings, dollar savings,
task success, patch correctness, statistical certainty, or an isolated causal
effect of graph structure.

## Frozen measurement contract

- **Query:** each task's problem statement, unchanged across arms.
- **Truth:** gold-derivation version 4, frozen before scoring. Gold is the set of
  symbols touched by a reference patch and is a localization proxy; another
  valid implementation can touch different code.
- **State:** fresh `--reindex` per instance, with repository and base-commit
  identities in the hashed corpus manifests. There is no single reusable box ID.
- **Wire unit:** `ttg_wire`, tokenized with `o200k_base` for every arm.
- **Coverage:** mean per-instance frozen-gold coverage at a named wire checkpoint.
- **Reach@80 whole response:** fraction of the declared denominator that reaches
  80% frozen-gold coverage anywhere in the complete delivered response.
- **Median-to-80 whole response:** median wire position among reachers; it must be
  read beside the whole-response reach fraction.

The native floor uses `rg`/glob discovery plus targeted source spans. The nbx
row uses the shipped default at engine commit
`3723be44085ab470bad55241853276f85568291e`; both were produced by binary
SHA-256 `d02270de07b1f0d786ef49c80e71848fe57df4109a06eb5a3804cb8b68f66151`.
The shared query, truth, tokenizer, and scorer do not make this a same-engine
ablation: implementation, configuration, and host differences are disclosed
conditions, not a basis for isolated causal attribution.

Graphify is pinned to `graphifyy==0.9.28` with `--code-only`. Its wheel and
transitive dependency hashes were not captured, so this arm is version-pinned
rather than hash-pinned. Graphify 0.9.56 was not used; it is reserved for a
separately preregistered sensitivity study.

## Denominators and uncertainty

Python uses frozen-gold N=39, TypeScript N=37, Go N=30, and the Rust native-floor
and nbx rows use frozen-gold N=40. Raw report aggregate fields include successful
rows outside those frozen sets and are retained only as historical raw fields;
they are not a numeric source for this package.

Graphify failed to build all seven `astral-sh/ruff` instances in `rust43`. Six
were gold-bearing and are recorded as exact exclusions in `authority.json`; the
seventh was zero-gold. Rust Graphify is therefore descriptive on an explicitly
nonmatched N=34 failure subset. The matched Rust comparison remains nbx versus
the native floor on N=40. No common-N Graphify sensitivity is claimed.

The preregistered paired per-corpus uncertainty analysis is not present. Its
structured scoring/publication gate remains open in `authority.json` and the
generated status view. Point estimates are not presented as completion of that
requirement, and no paired median inference is made from different reacher sets.

## Evidence, consistency, and reproduction

The provenance ledger gives every retained source table, preregistration,
doctrine file, corpus, frozen-gold file, run header, corpus manifest, report, and
emitted report manifest a digest, safe local audit path, and canonical release
path. Result rows are joined to those artifacts by typed corpus and arm IDs.
Result-bearing evidence must remain `verified`; the verifier rejects state
downgrades, cross-corpus swaps, path traversal, missing digests, and incomplete
checksum membership.

The producer serializes empty ranked lists by omitting both
`retrieved_symbols` and `retrieved_wire_positions`. Offline reconstruction
accepts only that joint absence, then still requires the stored curve to equal
the reconstructed zero-delivery curve. One-sided absence or a nonzero stored
curve rejects.

Clone-contained validation is available now:

```sh
./v2/verify.sh
./v2/verify.sh --self-test
```

That proves consistency among the candidate authority, generated views,
provenance relationships, scoring-code identities, and package checksums. It
does not prove externally anchored authenticity: no accepted immutable public
revision or public raw-evidence locator exists yet.

With the private retained source tree available beneath one audit root, this
separate gate verifies every source byte and actually recomputes all 16 tuples
with `ttg.rollup`:

```sh
./v2/verify.sh --audit-root /path/to/noodlbox
```

The same verified inputs can be assembled into a portable local release
directory and replayed from that directory:

```sh
./v2/verify.sh --audit-root /path/to/noodlbox \
  --prepare-bundle /new/empty/path/ttg-v2-a1-evidence
./v2/verify.sh --bundle-root /path/to/ttg-v2-a1-evidence
```

A local audit or bundle is review evidence, not public reproduction. Public
retrieval and reproduction remain unavailable until the bundle and accepted
immutable revision receive real public locators.

## One correction and restamping workflow

`authority.json` is the only place to correct a tuple or structured status.
Update the affected provenance digest or relationship in the same change, then
regenerate every derived view and the exact checksum membership set:

```sh
python3 v2/verify.py --write-derived
./v2/verify.sh --self-test
./v2/verify.sh --audit-root /path/to/noodlbox
```

The final audit-root command must recompute every result from retained rows.
After review, an external publication decision must anchor the accepted Git
revision and evidence-bundle locators. Checksums alone establish internal byte
consistency; the external revision or release anchor establishes authenticity.

Graphify's missing package hashes and separate per-report manifests remain
disclosed limitations. To report a correction, open an issue after publication;
until then, this candidate is explicitly unpublished.
