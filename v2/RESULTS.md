# V2 Tier A — A1 Graphify results

> Exact values from `results.tsv`. Each corpus remains separate; no pooled result is reported.

## Python (`py_nosphinx`)

| Arm | N | Basis | Matched to nbx N? | Gold@2K_wire | Gold@8K_wire | Gold@32K_wire | TtG@80 reach_wire | TtG@80 median_wire |
|---|---:|---|---|---:|---:|---:|---:|---:|
| native floor | 39 | `frozen_gold` | yes | 0.025641026 | 0.141025641 | 0.504273504 | 0.871794872 | 26150 |
| nbx shipped | 39 | `frozen_gold` | yes | 0.735042735 | 0.833333333 | 0.910256410 | 0.897435897 | 1121 |
| Graphify · 32K query | 39 | `frozen_gold` | yes | 0.128205128 | 0.141025641 | 0.371794872 | 0.897435897 | 96025 |
| Graphify · default 2K query | 39 | `frozen_gold` | yes | 0.128205128 | 0.141025641 | 0.371794872 | 0.435897436 | 20516 |

## TypeScript (`ts40`)

| Arm | N | Basis | Matched to nbx N? | Gold@2K_wire | Gold@8K_wire | Gold@32K_wire | TtG@80 reach_wire | TtG@80 median_wire |
|---|---:|---|---|---:|---:|---:|---:|---:|
| native floor | 37 | `frozen_gold` | yes | 0.101544402 | 0.186057486 | 0.315986116 | 0.648648649 | 65250 |
| nbx shipped | 37 | `frozen_gold` | yes | 0.490199290 | 0.789118014 | 0.889274014 | 0.783783784 | 3051 |
| Graphify · 32K query | 37 | `frozen_gold` | yes | 0.081490581 | 0.189818065 | 0.426323076 | 0.378378378 | 52933 |
| Graphify · default 2K query | 37 | `frozen_gold` | yes | 0.081490581 | 0.189818065 | 0.417314067 | 0.243243243 | 18788 |

## Go (`go34`)

| Arm | N | Basis | Matched to nbx N? | Gold@2K_wire | Gold@8K_wire | Gold@32K_wire | TtG@80 reach_wire | TtG@80 median_wire |
|---|---:|---|---|---:|---:|---:|---:|---:|
| native floor | 30 | `frozen_gold` | yes | 0.038888889 | 0.083413776 | 0.264716895 | 0.566666667 | 161511 |
| nbx shipped | 30 | `frozen_gold` | yes | 0.313023295 | 0.692971103 | 0.855956451 | 0.733333333 | 5314 |
| Graphify · 32K query | 30 | `frozen_gold` | yes | 0.020000000 | 0.115535325 | 0.321935885 | 0.300000000 | 26728 |
| Graphify · default 2K query | 30 | `frozen_gold` | yes | 0.020000000 | 0.115535325 | 0.321935885 | 0.200000000 | 11097 |

## Rust (`rust43`)

| Arm | N | Basis | Matched to nbx N? | Gold@2K_wire | Gold@8K_wire | Gold@32K_wire | TtG@80 reach_wire | TtG@80 median_wire |
|---|---:|---|---|---:|---:|---:|---:|---:|
| native floor | 40 | `frozen_gold` | yes | 0.054166667 | 0.178571429 | 0.338988095 | 0.775000000 | 70457 |
| nbx shipped | 40 | `frozen_gold` | yes | 0.372980859 | 0.532189542 | 0.774501050 | 0.700000000 | 5448 |
| Graphify · 32K query | 34 | `graphify_failure_subset` | **no — failure subset** | 0.062091503 | 0.119493876 | 0.257390701 | 0.529411765 | 54679 |
| Graphify · default 2K query | 34 | `graphify_failure_subset` | **no — failure subset** | 0.062091503 | 0.119493876 | 0.257390701 | 0.352941176 | 27054 |

The Rust Graphify rows are an explicitly nonmatched N=34 failure subset; compare the Rust nbx and native-floor rows only on their shared frozen N=40 basis.
