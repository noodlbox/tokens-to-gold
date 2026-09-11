# V2 repo remediation freeze witness

Candidate frozen on 2026-09-10 for independent re-review. This is an
uncommitted local candidate above HEAD
`d94c1d6aa5796851d280e8f1201f756a65b9e989` (tree
`f9a11597b551d3cc61c62ecd5913b65887a0ae42`) on
`docs/ttg-v2-publish`. It is not acceptance, publication, public reproduction,
or runtime authority.

## Frozen package identities

- authority schema: `ttg-v2-tier-a-a1-authority/v2`
- `v2/authority.json`: `3c3c5f2c231bab1480e524b3048b4aa325fd5e2f8b224e357b8968f8bded763d`
- `v2/SHA256SUMS`: `60b92cdb9dcbb45d5eaf03e77eca320351fbc7eb726b1fa9c3be97194a18dec8`
- `v2/provenance.tsv`: `0c84edc35c596ff49eb2093fce36e39d214116020faf9ab9d7b2edcdb801b972`
- `v2/verify.py`: `bef67b06dfd92183aeb006ee9f829fd65b9cb775554049c9151f66eed2f19216`
- `ttg/curve_recompute.py`: `df655aabb724d26cd909df8f83ea9970671225250bb403dc8219a2c7d6f8dbd3`

Frozen source-table identities remain:

- Python: `9ae7cb3e4fb6200b614a6e51e1138d5094c1d1c9bb4e429fe808adcff514b8b3`
- TypeScript: `7b82fd99601966cd6cc284a7ef66e50a26afcad57d754eed2a6756c113d22782`
- Go: `b3e2bcdce55660d55a831a71919199db292e4d1a08dc2133a9a2f184829bcf0c`
- Rust: `95b3620f903a8f6ca905c14d871bf945b4d41570f85c48f2d9786c2446c5910a`

The exact changed-path membership and member hashes, excluding only the
manifest itself, are in `CANDIDATE_CLOSURE.tsv`; the handoff reports that
manifest's digest and completes the closure without a self-hash.

## RR-01 through RR-09 dispositions

| Finding | Frozen disposition |
|---|---|
| RR-01 | Frozen-gold symbols/ranges plus retained ranked identities/positions reconstruct every selected curve using the existing symbol or span matcher. Complete stored-curve fields/grids must match before `ttg.rollup` aggregation. The five-file scorer closure is digest-pinned. |
| RR-02 | Required preregistration, doctrine, tokenizer, run-header, and producer roles have closed cardinalities and typed references. Native/nbx identities require their available digest; Graphify 0.9.28 remains explicitly declared-only because wheel/dependency hashes were not retained. |
| RR-03 | Structured evidence records all seven Rust Graphify build failures and exact available raw error. Six gold-bearing failures alone define the nonmatched N=34 exclusions; both reports must retain all seven failures. |
| RR-04 | `authority.json` owns current status. `STATUS.md`, `RESULTS.md`, and V2 `BUNDLE.md` are generated. Future legal transitions require typed evidence; public revision and evidence-release fields bind their provenance records. Current gates did not advance. |
| RR-05 | Recursive V2 membership is exactly eight payload files plus `SHA256SUMS`; extra, missing, duplicate, unknown, noncanonical, or symlink members reject. Review witnesses stay outside `v2/`. |
| RR-06 | Median is a strictly positive integer; both JSON booleans reject. |
| RR-07 | Clone CI runs the V2 self-test and the pinned Ruff command includes `v2/verify.py`. |
| RR-08 | Bundle assembly uses an owned temporary sibling, validates before an exclusive atomic rename, never replaces a target, and removes only its unpublished staging directory after failure. Copy/manifest/validation/retry/race controls pass. |
| RR-09 | Repo/package/evidence roots are explicit through validation and bundle helpers. Corruption fixtures carry the complete scorer closure and validate against their fixture root. |

The retained-empty-vector investigation and exact row inventory are in
`RED_WITNESS.md`. Joint absence is accepted only as the frozen producer's
serialized empty ranked list and must parity-check as zero delivery; it did not
change raw bytes or any tuple.

## Green verification witness

All commands were run offline from the owned worktree with
`PYTHONDONTWRITEBYTECODE=1` where Python bytecode could otherwise enter the
strict package.

```sh
ruff check ttg/ tests/ acceptance/ arms/ v2/verify.py
```

Result: exit `0`, `All checks passed!` using installed Ruff 0.15.5.

```sh
PYTHONDONTWRITEBYTECODE=1 python3 -m unittest discover -s tests
```

Result: exit `0`; 205 tests ran, four skipped, `OK`. The skips are the existing
dependency/report-availability skips, not V2 remediation controls.

```sh
PYTHONDONTWRITEBYTECODE=1 ./v2/verify.sh \
  --audit-root /Users/youssefkhalil/Desktop/Youssef/noodlbox --self-test
```

Result: exit `0`. Clone controls caught metric-range, evidence-free promotion,
missing role, producer downgrade/version drift, tokenizer mismatch,
report-relation/state/path, generated-view drift, package membership/symlink,
boolean median, fixture scorer, checksum membership, atomic failure/retry, and
concurrent-target mutations. Fixture-only future publication and bound
retrieval/reproduction states passed. Raw controls rejected a restamped stored
curve corruption and removal of zero-gold Rust failure `ruff-15626`. All 16
accepted tuples reconstructed from retained primitives and matched authority.

```sh
ttg_remediation_tmp=$(mktemp -d /tmp/ttg-v2-remediation.XXXXXX)
trap 'rm -rf -- "$ttg_remediation_tmp"' EXIT
PYTHONDONTWRITEBYTECODE=1 ./v2/verify.sh \
  --audit-root /Users/youssefkhalil/Desktop/Youssef/noodlbox \
  --prepare-bundle "$ttg_remediation_tmp/bundle"
PYTHONDONTWRITEBYTECODE=1 ./v2/verify.sh \
  --bundle-root "$ttg_remediation_tmp/bundle"
```

Result: both commands exited `0`; the owned temporary was removed afterward.

```sh
bash -n v2/verify.sh
python3 -c "import json; json.load(open('v2/authority.json'))"
git diff --check
```

Result: all exited `0` with no output.

Historical red results and exact pre-fix input hashes are preserved in
`RED_WITNESS.md` and guarded by `pre_fix_probe.py`.

## Claim and lifecycle boundaries

- The 8K value is a fixed retrieval-output observation budget, never an agent,
  turn, task, or completion cutoff.
- Reach@80 and median-to-80 measure the complete delivered response, which may
  exceed 32K wire tokens. No uncapped/max-coverage result is claimed.
- Graphify's backend budget is its native approximate-token unit; wire
  checkpoints and expanded body delivery remain separate.
- Graphify is pinned to 0.9.28. Version 0.9.56 is sensitivity-only and produced
  none of these results.
- Rust Graphify is descriptive on a nonmatched N=34 failure subset. It is never
  pooled or presented as matched to native/nbx N=40.
- These are descriptive retrieval observations, not billed cost, task success,
  patch correctness, statistical certainty, or isolated causal attribution.
- Tier B whole-agent adaptive retrieval/patch success, the CodeDB appendix, and
  preregistered paired per-corpus uncertainty remain pending with no results.
- Public evidence retrieval and public tuple reproduction remain unavailable.
- The Rust native-floor completion/exit/report-size-at-completion witness is
  absent; its immutable manifest proves command and binary identity only.

No benchmark/model/runtime call, source mutation, dependency install, network
fetch, credential access, lease, commit, push, PR, merge, deployment, or
publication occurred in this remediation increment.
