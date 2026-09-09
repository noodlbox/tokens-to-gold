#!/usr/bin/env bash
# Offline integrity and claim-boundary checks for the V2 Tier A A1 package.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PACKAGE_ROOT="${TTG_V2_PACKAGE_ROOT:-$SCRIPT_DIR}"
REPO_ROOT="${TTG_V2_REPO_ROOT:-$(cd "$PACKAGE_ROOT/.." && pwd)}"
EXPECTED_RESULTS_SHA256="09684122f3903b3ecc3fb73f56b506bda17972a72f429e46137807089c80486e"
AUDIT_ROOT=""
SELF_TEST=0

fail() {
  local code="$1"
  shift
  printf 'V2 verification failed [%s]: %s\n' "$code" "$*" >&2
  exit 1
}

hash_file() {
  local path="$1"
  if command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | awk '{print $1}'
  elif command -v shasum >/dev/null 2>&1; then
    LC_ALL=C shasum -a 256 "$path" | awk '{print $1}'
  else
    fail E_HASH_TOOL "sha256sum or shasum is required"
  fi
}

require_file() {
  local path="$1"
  [ -f "$path" ] || fail E_MISSING_FILE "missing ${path#$REPO_ROOT/}"
}

require_text() {
  local path="$1"
  local text="$2"
  local code="$3"
  grep -Fq "$text" "$path" || fail "$code" "${path#$REPO_ROOT/} lacks required text: $text"
}

provenance_has() {
  local kind="$1"
  local id="$2"
  awk -F '\t' -v kind="$kind" -v id="$id" '
    NR > 1 && $1 == kind && $2 == id { found = 1 }
    END { exit(found ? 0 : 1) }
  ' "$PACKAGE_ROOT/provenance.tsv"
}

provenance_sha() {
  local kind="$1"
  local id="$2"
  awk -F '\t' -v kind="$kind" -v id="$id" '
    NR > 1 && $1 == kind && $2 == id { print $4; found = 1 }
    END { exit(found ? 0 : 1) }
  ' "$PACKAGE_ROOT/provenance.tsv"
}

assert_provenance_sha() {
  local id="$1"
  local expected="$2"
  local actual
  actual="$(provenance_sha source_table "$id")" ||
    fail E_SOURCE_ANCHOR "missing frozen source table $id"
  [ "$actual" = "$expected" ] ||
    fail E_SOURCE_ANCHOR "$id has $actual, expected $expected"
}

render_results() {
  printf '%s\n\n' '# V2 Tier A — A1 Graphify results'
  printf '%s\n\n' \
    '> Exact values from `results.tsv`. Each corpus remains separate; no pooled result is reported.'
  awk -F '\t' '
    function arm_label(arm) {
      if (arm == "native_floor") return "native floor"
      if (arm == "nbx_shipped") return "nbx shipped"
      if (arm == "graphify_32k") return "Graphify · 32K query"
      if (arm == "graphify_default") return "Graphify · default 2K query"
      return arm
    }
    NR == 1 { next }
    $1 != corpus {
      if (corpus != "") print ""
      corpus = $1
      print "## " $2 " (`" $1 "`)"
      print ""
      print "| Arm | N | Basis | Matched to nbx N? | Gold@2K_wire | Gold@8K_wire | Gold@32K_wire | TtG@80 reach_wire | TtG@80 median_wire |"
      print "|---|---:|---|---|---:|---:|---:|---:|---:|"
    }
    {
      matched = ($9 == "yes" ? "yes" : "**no — failure subset**")
      printf "| %s | %s | `%s` | %s | %s | %s | %s | %s | %s |\n", \
        arm_label($4), $7, $8, matched, $10, $11, $12, $13, $14
    }
  ' "$PACKAGE_ROOT/results.tsv"
  printf '\n%s\n' \
    'The Rust Graphify rows are an explicitly nonmatched N=34 failure subset; compare the Rust nbx and native-floor rows only on their shared frozen N=40 basis.'
}

verify_docs() {
  local top_readme="$REPO_ROOT/README.md"
  local top_bundle="$REPO_ROOT/BUNDLE.md"
  local readme="$PACKAGE_ROOT/README.md"
  local results_md="$PACKAGE_ROOT/RESULTS.md"
  local bundle="$PACKAGE_ROOT/BUNDLE.md"

  require_file "$top_readme"
  require_file "$top_bundle"
  require_text "$top_readme" "V2 Tier A — A1 Graphify slice" E_TOPLEVEL
  require_text "$top_readme" "v2/README.md" E_TOPLEVEL
  require_text "$top_readme" "success are pending" E_TOPLEVEL
  require_text "$top_readme" "CodeDB appendix is pending" E_TOPLEVEL
  require_text "$top_bundle" "V2 Tier A — A1 Graphify slice" E_TOPLEVEL
  require_text "$top_bundle" \
    "Tier B whole-agent work and the CodeDB appendix are pending and are not results." \
    E_TOPLEVEL
  require_text "$readme" \
    "The 8K point is a fixed retrieval-output observation budget, not an agent or task cutoff." \
    E_8K_BOUNDARY
  require_text "$readme" \
    "Tier B whole-agent adaptive retrieval and patch success: **PENDING**." \
    E_TIER_B_BOUNDARY
  require_text "$readme" "CodeDB appendix: **PENDING**." E_CODEDB_BOUNDARY
  require_text "$readme" "graphifyy==0.9.28" E_GRAPHIFY_PIN
  require_text "$readme" "0.9.56 was not used" E_GRAPHIFY_PIN
  require_text "$results_md" \
    "Rust Graphify rows are an explicitly nonmatched N=34 failure subset" \
    E_RUST_BASIS
  require_text "$bundle" "Raw trajectory" E_BUNDLE_CONTRACT

  if grep -Eqi 'Tier B (is |was )?(complete|completed|done)|Tier B results? (are )?(complete|available|published)' \
    "$top_readme" "$top_bundle" "$readme" "$results_md" "$bundle"; then
    fail E_TIER_B_BOUNDARY "Tier B is described as complete or result-bearing"
  fi
  if grep -Eqi 'CodeDB (appendix )?(is |was )?(complete|completed|done)|CodeDB results? (are )?(available|published)' \
    "$top_readme" "$top_bundle" "$readme" "$results_md" "$bundle"; then
    fail E_CODEDB_BOUNDARY "CodeDB is described as complete or result-bearing"
  fi
  if grep -Eqi 'uncapped|max(imum)?[- ]coverage|whole-list' "$readme" "$results_md" "$bundle"; then
    fail E_SCOPE_BOUNDARY "a prohibited maximum-coverage claim appears in V2 public copy"
  fi
  if grep -Eqi '\b(proves?|causes?|guarantees?)\b' "$readme" "$results_md" "$bundle"; then
    fail E_CAUSAL_LANGUAGE "causal or proof language appears in V2 public copy"
  fi
}

verify_results() {
  local results="$PACKAGE_ROOT/results.tsv"
  local expected_header actual_header actual_sha
  expected_header=$'corpus\tlanguage\tsource_table_id\tarm\tconfig\tquery_budget_wire\tn\tbasis\tmatched_comparison\tgold_at_2k_wire\tgold_at_8k_wire\tgold_at_32k_wire\tttg_at_80_reach_wire\tttg_at_80_median_wire\tproducer_id\treport_id\treport_manifest_id'
  actual_header="$(sed -n '1p' "$results")"
  [ "$actual_header" = "$expected_header" ] ||
    fail E_RESULTS_SCHEMA "results.tsv header does not match the frozen schema"

  awk -F '\t' '
    BEGIN {
      expected_n["py_nosphinx"] = 39
      expected_n["ts40"] = 37
      expected_n["go34"] = 30
      expected_n["rust43"] = 40
    }
    NR == 1 { next }
    NF != 17 { print "row " NR " has " NF " fields" > "/dev/stderr"; exit 1 }
    !($1 in expected_n) { print "unexpected corpus " $1 > "/dev/stderr"; exit 1 }
    $4 != "native_floor" && $4 != "nbx_shipped" &&
      $4 != "graphify_32k" && $4 != "graphify_default" {
      print "unexpected arm " $4 > "/dev/stderr"; exit 1
    }
    seen[$1 SUBSEP $4]++ { print "duplicate corpus/arm " $1 "/" $4 > "/dev/stderr"; exit 1 }
    $10 !~ /^(0|1)\.[0-9]{9}$/ || $11 !~ /^(0|1)\.[0-9]{9}$/ ||
      $12 !~ /^(0|1)\.[0-9]{9}$/ || $13 !~ /^(0|1)\.[0-9]{9}$/ {
      print "non-canonical metric precision on row " NR > "/dev/stderr"; exit 1
    }
    $14 !~ /^[1-9][0-9]*$/ { print "invalid median on row " NR > "/dev/stderr"; exit 1 }
    $4 == "graphify_32k" && $6 != "32000" { print "Graphify 32K budget mismatch" > "/dev/stderr"; exit 1 }
    $4 == "graphify_default" && $6 != "2000" { print "Graphify default budget mismatch" > "/dev/stderr"; exit 1 }
    $4 !~ /^graphify_/ && $6 != "not_applicable" { print "unexpected query budget" > "/dev/stderr"; exit 1 }
    $1 == "rust43" && $4 ~ /^graphify_/ {
      if ($7 != 34 || $8 != "graphify_failure_subset" || $9 != "no") {
        print "Rust Graphify must remain a nonmatched N=34 failure subset" > "/dev/stderr"; exit 1
      }
      next
    }
    $7 != expected_n[$1] || $8 != "frozen_gold" || $9 != "yes" {
      print "frozen basis mismatch on " $1 "/" $4 > "/dev/stderr"; exit 1
    }
    END {
      if (NR != 17) { print "expected 16 result rows, found " NR - 1 > "/dev/stderr"; exit 1 }
      for (corpus in expected_n) {
        count = 0
        for (key in seen) {
          split(key, parts, SUBSEP)
          if (parts[1] == corpus) count++
        }
        if (count != 4) { print corpus " has " count " arms" > "/dev/stderr"; exit 1 }
      }
    }
  ' "$results" || fail E_RESULTS_SCHEMA "result rows violate corpus, arm, budget, or denominator rules"

  actual_sha="$(hash_file "$results")"
  [ "$actual_sha" = "$EXPECTED_RESULTS_SHA256" ] ||
    fail E_RESULTS_DIGEST "results.tsv is $actual_sha, expected $EXPECTED_RESULTS_SHA256"
}

verify_provenance() {
  local provenance="$PACKAGE_ROOT/provenance.tsv"
  local expected_header actual_header
  expected_header=$'kind\tid\tversion\tsha256\taudit_path\tstate\tnote'
  actual_header="$(sed -n '1p' "$provenance")"
  [ "$actual_header" = "$expected_header" ] ||
    fail E_PROVENANCE_SCHEMA "provenance.tsv header does not match the frozen schema"

  awk -F '\t' '
    NR == 1 { next }
    NF != 7 { print "row " NR " has " NF " fields" > "/dev/stderr"; exit 1 }
    $1 == "" || $2 == "" || $3 == "" || $4 == "" || $5 == "" || $6 == "" || $7 == "" {
      print "blank provenance field on row " NR > "/dev/stderr"; exit 1
    }
    seen[$1 SUBSEP $2]++ { print "duplicate provenance id " $1 "/" $2 > "/dev/stderr"; exit 1 }
    $6 == "verified" && $4 !~ /^[0-9a-f]{64}$/ {
      print "verified row lacks sha256 on row " NR > "/dev/stderr"; exit 1
    }
    $6 != "verified" && $4 != "-" && $4 !~ /^[0-9a-f]{64}$/ {
      print "invalid explained hash on row " NR > "/dev/stderr"; exit 1
    }
  ' "$provenance" || fail E_PROVENANCE_SCHEMA "provenance rows are incomplete or malformed"

  assert_provenance_sha py \
    9ae7cb3e4fb6200b614a6e51e1138d5094c1d1c9bb4e429fe808adcff514b8b3
  assert_provenance_sha ts \
    7b82fd99601966cd6cc284a7ef66e50a26afcad57d754eed2a6756c113d22782
  assert_provenance_sha go \
    b3e2bcdce55660d55a831a71919199db292e4d1a08dc2133a9a2f184829bcf0c
  assert_provenance_sha rust \
    95b3620f903a8f6ca905c14d871bf945b4d41570f85c48f2d9786c2446c5910a
  require_text "$provenance" \
    $'corpus\trust43\tSWE-bench-Multilingual\t32661b0c77aff0e5cdbad9e82c21be6a0ef493a7945a0923174629fc8f36ce03' \
    E_SOURCE_LABEL

  while IFS=$'\t' read -r corpus _language source_table _arm _config _budget _n \
    _basis _matched _g2 _g8 _g32 _reach _median producer report report_manifest; do
    [ "$corpus" = "corpus" ] && continue
    provenance_has source_table "$source_table" ||
      fail E_PROVENANCE_REFERENCE "missing source_table/$source_table"
    provenance_has corpus "$corpus" ||
      fail E_PROVENANCE_REFERENCE "missing corpus/$corpus"
    provenance_has frozen_gold "$corpus" ||
      fail E_PROVENANCE_REFERENCE "missing frozen_gold/$corpus"
    provenance_has producer "$producer" ||
      fail E_PROVENANCE_REFERENCE "missing producer/$producer"
    provenance_has report "$report" ||
      fail E_PROVENANCE_REFERENCE "missing report/$report"
    if [ "$report_manifest" != "not_emitted" ]; then
      provenance_has report_manifest "$report_manifest" ||
        fail E_PROVENANCE_REFERENCE "missing report_manifest/$report_manifest"
    fi
  done < "$PACKAGE_ROOT/results.tsv"
}

verify_rendered_results() {
  local rendered
  rendered="$(mktemp "${TMPDIR:-/tmp}/ttg-v2-render.XXXXXX")"
  render_results > "$rendered"
  if ! cmp -s "$rendered" "$PACKAGE_ROOT/RESULTS.md"; then
    rm -f "$rendered"
    fail E_RENDERED_RESULTS "RESULTS.md does not match results.tsv"
  fi
  rm -f "$rendered"
}

verify_package_hashes() {
  local sums="$PACKAGE_ROOT/SHA256SUMS"
  local expected path actual
  while read -r expected path; do
    [ -n "${expected:-}" ] || continue
    require_file "$PACKAGE_ROOT/$path"
    actual="$(hash_file "$PACKAGE_ROOT/$path")"
    [ "$actual" = "$expected" ] ||
      fail E_PACKAGE_DIGEST "$path is $actual, expected $expected"
  done < "$sums"
}

verify_audit_tree() {
  local expected path actual
  [ -d "$AUDIT_ROOT" ] || fail E_AUDIT_ROOT "not a directory: $AUDIT_ROOT"
  while IFS=$'\t' read -r _kind _id _version expected path state _note; do
    [ "$state" = "verified" ] || continue
    require_file "$AUDIT_ROOT/$path"
    actual="$(hash_file "$AUDIT_ROOT/$path")"
    [ "$actual" = "$expected" ] ||
      fail E_AUDIT_DIGEST "$path is $actual, expected $expected"
  done < <(sed -n '2,$p' "$PACKAGE_ROOT/provenance.tsv")
}

verify_once() {
  require_file "$REPO_ROOT/README.md"
  require_file "$REPO_ROOT/BUNDLE.md"
  require_text "$REPO_ROOT/README.md" "V2 Tier A — A1 Graphify slice" E_TOPLEVEL
  require_text "$REPO_ROOT/BUNDLE.md" "V2 Tier A — A1 Graphify slice" E_TOPLEVEL
  require_file "$PACKAGE_ROOT/README.md"
  require_file "$PACKAGE_ROOT/BUNDLE.md"
  require_file "$PACKAGE_ROOT/RESULTS.md"
  require_file "$PACKAGE_ROOT/results.tsv"
  require_file "$PACKAGE_ROOT/provenance.tsv"
  require_file "$PACKAGE_ROOT/SHA256SUMS"
  verify_docs
  verify_results
  verify_provenance
  verify_rendered_results
  verify_package_hashes
  if [ -n "$AUDIT_ROOT" ]; then
    verify_audit_tree
  fi
}

expect_failure() {
  local root="$1"
  local expected_code="$2"
  local output
  if output="$(TTG_V2_PACKAGE_ROOT="$root/v2" TTG_V2_REPO_ROOT="$root" \
    bash "$root/v2/verify.sh" 2>&1)"; then
    fail E_SELF_TEST "$expected_code mutation unexpectedly passed"
  fi
  case "$output" in
    *"[$expected_code]"*) printf 'RED control caught: %s\n' "$expected_code" ;;
    *) fail E_SELF_TEST "$expected_code mutation failed for the wrong reason: $output" ;;
  esac
}

self_test() {
  local temporary clean numeric provenance tier_b
  temporary="$(mktemp -d "${TMPDIR:-/tmp}/ttg-v2-selftest.XXXXXX")"
  trap 'if [ -n "${temporary:-}" ] && [ -d "$temporary" ]; then rm -rf -- "$temporary"; fi' EXIT
  clean="$temporary/clean"
  mkdir -p "$clean"
  cp "$REPO_ROOT/README.md" "$REPO_ROOT/BUNDLE.md" "$clean/"
  cp -R "$PACKAGE_ROOT" "$clean/v2"

  numeric="$temporary/numeric"
  cp -R "$clean" "$numeric"
  sed -i.bak 's/0\.833333333/0.833333334/' "$numeric/v2/results.tsv"
  rm -f "$numeric/v2/results.tsv.bak"
  expect_failure "$numeric" E_RESULTS_DIGEST

  provenance="$temporary/provenance"
  cp -R "$clean" "$provenance"
  sed -i.bak '/^report[[:space:]]py-native-floor[[:space:]]/d' "$provenance/v2/provenance.tsv"
  rm -f "$provenance/v2/provenance.tsv.bak"
  expect_failure "$provenance" E_PROVENANCE_REFERENCE

  tier_b="$temporary/tier-b"
  cp -R "$clean" "$tier_b"
  sed -i.bak 's/Tier B whole-agent adaptive retrieval and patch success: \*\*PENDING\*\*\./Tier B is complete./' \
    "$tier_b/v2/README.md"
  rm -f "$tier_b/v2/README.md.bak"
  expect_failure "$tier_b" E_TIER_B_BOUNDARY

  printf '%s\n' 'All V2 negative controls passed.'
}

while [ "$#" -gt 0 ]; do
  case "$1" in
    --audit-root)
      [ "$#" -ge 2 ] || fail E_USAGE "--audit-root requires a path"
      AUDIT_ROOT="$2"
      shift 2
      ;;
    --self-test)
      SELF_TEST=1
      shift
      ;;
    *)
      fail E_USAGE "unknown argument: $1"
      ;;
  esac
done

verify_once
if [ "$SELF_TEST" -eq 1 ]; then
  self_test
fi
printf '%s\n' 'V2 Tier A A1 publication verification passed.'
