"""The B3 must-red suite (T1-T7).

DISCIPLINE: every check carries a PERMANENT NEGATIVE CONTROL — the naive
implementation it replaced, asserted to FAIL. A one-time transcripted red
proves teeth once; a negative control proves teeth on every run, forever, and
stops a future "simplification" from quietly reintroducing the bug.
"""

from __future__ import annotations

import hashlib
import json
import os
import unittest
from pathlib import Path

from arms.arm_matrix import (
    ARMS, CORPORA, DEFAULT_ARMS, SECTION5_ARMS, SWEEP_ARMS, ArmError, Curation,
    StoreMode, assert_corpus_matches_protocol, assert_lane_invariants, cells,
    char_budget, flags_for,
)
from ttg.comparable_path import ComparablePath, PathComparison, compare_paths
from ttg.curve_recompute import curve_parity_findings, recompute_wire_curve
from ttg.gold_freezer import build_gold_map
from ttg.matcher import match_gold, split_identity
from ttg.report_io import ReportFormatError, gold_bearing_rows, load_report, loads_report, result_rows
from ttg.acceptance import (
    LOCKED_METRICS, NOISE_FLOOR_PP, REPLAY_TOL, check_report_file, load_fixture,
    load_frozen_gold,
)
from ttg.rollup import Basis, rollup
from ttg.tier1 import CLAIM_FIELDS, compare_frozen_gold

HERE = Path(__file__).resolve().parent
PKG = HERE.parent

# Reports are NOT in the repo — they are large derivation/arm artifacts that
# live in object storage (see PIN.toml [artifacts]). Point the suite at a
# local directory with TTG_REPORTS_DIR; the expected filenames are exactly
# what `arms/run_matrix.sh` emits, so the harness's own output feeds its own
# acceptance gate. Absent reports SKIP rather than fail, so a fresh clone is
# green without them.
REPORTS = Path(os.environ.get("TTG_REPORTS_DIR", PKG / "reports"))


def _cell_report(arm: str, corpus: str) -> Path:
    return REPORTS / f"{arm}_{corpus}.json"

# Q3 RULING: rel2-measurer owns these. The harness REPRODUCES them; it does
# not self-certify and must not independently re-derive them.
# ONE AUTHORITY: expectations come from the measurer fixture, never a second
# hand-copied table (a copy is a duality waiting to drift).
_FIXTURE = load_fixture()
MEASURER = {
    corpus: {
        "gold_at_8k": arms["shipped_treatment"]["gold_at_8k_wire"],
        "reach_at_80": arms["shipped_treatment"]["reach_at_80"],
        "n": arms["shipped_treatment"]["n"],
    }
    for corpus, arms in _FIXTURE["arms"].items()
}
ACCEPTANCE_CELLS = tuple(
    (corpus, _cell_report(arm, corpus), arm)
    for arm in ("shipped_treatment", "levers_off_ablation")
    for corpus in ("ts40", "py_nosphinx")
)


def _acceptance_available() -> bool:
    return all(path.exists() for _, path, _ in ACCEPTANCE_CELLS)
CORPUS_REPORT = {c: f"shipped_treatment_{c}.json" for c in ("ts40", "py_nosphinx")}

# The private corpus name, as data — so the scan below can forbid it without
# every other module having to spell it.
PRIVATE_CORPUS = "til" + "la"


def _naive_normalize(key: str) -> str:
    """NEGATIVE CONTROL: the light normalize B3 replaced (strip + leading ./)."""
    s = key.strip()
    return s[2:] if s.startswith("./") else s


def _reports_available() -> bool:
    return all((REPORTS / n).exists() for n in CORPUS_REPORT.values())


class T1InstanceBasis(unittest.TestCase):
    """The gold-bearing basis is BINDING; the engine's all-rows basis is not."""

    @unittest.skipUnless(_reports_available(), "official reports not staged")
    def test_binding_basis_reproduces_measurer(self) -> None:
        for corpus, want in MEASURER.items():
            with self.subTest(corpus=corpus):
                gold = load_frozen_gold(corpus)
                roll = rollup(
                    load_report(REPORTS / CORPUS_REPORT[corpus]),
                    frozen_instance_ids=list(gold),
                )
                self.assertIs(roll.binding.basis, Basis.FROZEN_GOLD)
                self.assertTrue(roll.binding.basis.is_binding)
                self.assertEqual(roll.binding.n, want["n"])
                self.assertAlmostEqual(roll.binding.gold_at_budget[8000], want["gold_at_8k"], places=4)
                self.assertAlmostEqual(roll.binding.reach_at_coverage[80], want["reach_at_80"], places=4)

    @unittest.skipUnless(_reports_available(), "official reports not staged")
    def test_negative_control_all_rows_basis_misses_measurer(self) -> None:
        """NEGATIVE CONTROL: the engine's own rollup basis lands on the WRONG
        number. This is the failure a green-looking harness would ship."""
        for corpus, want in MEASURER.items():
            with self.subTest(corpus=corpus):
                roll = rollup(
                    load_report(REPORTS / CORPUS_REPORT[corpus]),
                    frozen_instance_ids=list(load_frozen_gold(corpus)),
                )
                self.assertGreater(roll.engine_basis.n, roll.binding.n)
                self.assertNotAlmostEqual(
                    roll.engine_basis.gold_at_budget[8000], want["gold_at_8k"], places=4
                )
                self.assertNotAlmostEqual(
                    roll.engine_basis.reach_at_coverage[80], want["reach_at_80"], places=4
                )

    @unittest.skipUnless(_reports_available(), "official reports not staged")
    def test_difference_is_denominator_only(self) -> None:
        """Numerators are identical; only the denominator differs."""
        for corpus in MEASURER:
            with self.subTest(corpus=corpus):
                roll = rollup(
                    load_report(REPORTS / CORPUS_REPORT[corpus]),
                    frozen_instance_ids=list(load_frozen_gold(corpus)),
                )
                self.assertAlmostEqual(
                    roll.binding.gold_at_budget[8000] * roll.binding.n,
                    roll.engine_basis.gold_at_budget[8000] * roll.engine_basis.n,
                    places=6,
                )
                self.assertAlmostEqual(
                    roll.binding.reach_at_coverage[80] * roll.binding.n,
                    roll.engine_basis.reach_at_coverage[80] * roll.engine_basis.n,
                    places=6,
                )

    @unittest.skipUnless(_reports_available(), "official reports not staged")
    def test_render_labels_both_bases(self) -> None:
        text = rollup(
            load_report(REPORTS / CORPUS_REPORT["ts40"]),
            frozen_instance_ids=list(load_frozen_gold("ts40")),
        ).render("ts40")
        self.assertIn("BINDING", text)
        self.assertIn("NOT binding", text)
        self.assertIn("EXPECTED, not a discrepancy", text)


class T2ComparablePath(unittest.TestCase):
    """The full rule, not the light normalize."""

    def test_rust_test_module_assertions(self) -> None:
        self.assertFalse(ComparablePath.retrieved("../a.py").is_comparable)
        self.assertTrue(ComparablePath.retrieved("./src/a.py").is_comparable)
        self.assertTrue(ComparablePath.gold("/src/a.py").is_comparable)
        self.assertFalse(ComparablePath.retrieved("/src/a.py").is_comparable)

    def test_three_valued_not_two(self) -> None:
        """NotComparable must stay distinct from Different: collapsing them
        reports a path-DOMAIN mismatch as 'retrieval found nothing'."""
        self.assertIs(compare_paths("src/a.py", "src/b.py"), PathComparison.DIFFERENT)
        self.assertIs(
            compare_paths("src/a.py", "/Users/me/repo/src/a.py"),
            PathComparison.NOT_COMPARABLE,
        )

    def test_asymmetry_is_deliberate(self) -> None:
        self.assertTrue(ComparablePath.gold("/src/a.py").is_comparable)
        self.assertFalse(ComparablePath.retrieved("/src/a.py").is_comparable)

    def test_collapses_and_rejects(self) -> None:
        for retrieved in ("./src/a.py", "src//a.py", "src/a.py/", ".//src/a.py"):
            with self.subTest(retrieved=retrieved):
                self.assertIs(compare_paths("src/a.py", retrieved), PathComparison.EQUAL)
        for bad in ("../a.py", "", "/"):
            with self.subTest(bad=bad):
                self.assertFalse(ComparablePath.retrieved(bad).is_comparable)

    def test_negative_control_light_normalize_undercounts(self) -> None:
        """NEGATIVE CONTROL: strip + leading-./ scores 0 where the real rule
        scores 1. It agrees with the engine on ts40 (0.0000 measured) and is a
        latent wrong-number generator everywhere else."""
        gold, retrieved = "/src/a.py:f", "./src/a.py:f"
        self.assertEqual(match_gold([gold], [retrieved]).covered, 1)
        naive = {_naive_normalize(gold)} & {_naive_normalize(retrieved)}
        self.assertEqual(len(naive), 0)


class T3ArmFlags(unittest.TestCase):
    """No code path may omit --curation. THE footgun."""

    def test_every_arm_emits_curation(self) -> None:
        for name, arm in ARMS.items():
            if not arm.available or arm.curation is Curation.SHIPPED_DEFAULT:
                continue  # SHIPPED_DEFAULT omits deliberately; covered separately
            for corpus in CORPORA:
                with self.subTest(arm=name, corpus=corpus):
                    self.assertIn("--curation", flags_for(name, corpus))

    def test_shipped_default_omission_is_declared_not_accidental(self) -> None:
        """The shipped-treatment arm measures the shipped default (Waterfill
        65536), so it passes NO --curation. That omission must be DECLARED."""
        flags = flags_for("shipped_treatment", "ts40")
        self.assertNotIn("--curation", flags)
        self.assertIs(ARMS["shipped_treatment"].curation, Curation.SHIPPED_DEFAULT)
        self.assertIn("--reindex", flags)

    def test_section5_baseline_is_levers_off_not_a0(self) -> None:
        """Q4: a0_off numbers must NEVER be labelled levers-off."""
        self.assertIn("levers_off_ablation", SECTION5_ARMS)
        self.assertNotIn("a0_off", SECTION5_ARMS)
        self.assertIn("a0_off", SWEEP_ARMS)
        self.assertNotIn("levers-off", ARMS["a0_off"].label)

    def test_a0_and_levers_off_are_explicit_and_distinct(self) -> None:
        a0 = flags_for("a0_off", "ts40")
        levers = flags_for("levers_off_ablation", "ts40")
        self.assertEqual(a0[a0.index("--curation") + 1], "off")
        self.assertEqual(levers[levers.index("--curation") + 1], "off")
        self.assertIn("--m22-levers-off", levers)
        self.assertNotIn("--m22-levers-off", a0)

    def test_omission_raises(self) -> None:
        """NEGATIVE CONTROL: an absent --curation is NOT 'off' post-ceea4ab0c."""
        with self.assertRaises(ArmError):
            assert_lane_invariants(["--graph-gold", "--raw-query", "--intent", "implement"])

    def test_use_packet_forbidden(self) -> None:
        with self.assertRaises(ArmError):
            assert_lane_invariants([*flags_for("wf_b3", "ts40"), "--use-packet"])

    def test_budget_grid_is_two_dimensional(self) -> None:
        self.assertEqual(char_budget("wf_b3", "ts40"), 72_256)
        self.assertEqual(char_budget("wf_b3", "py_nosphinx"), 74_400)
        self.assertIsNone(char_budget("a0_off", "ts40"))

    def test_matrix_shape(self) -> None:
        self.assertEqual(len(cells(SWEEP_ARMS, list(CORPORA))), 14)
        self.assertEqual(len(cells(DEFAULT_ARMS, list(CORPORA))), 4)
        self.assertEqual(DEFAULT_ARMS, ("wf_b3", "a0_off"))

    def test_undeclared_omission_still_raises(self) -> None:
        with self.assertRaises(ArmError):
            assert_lane_invariants(["--graph-gold"], ARMS["a0_off"])

    def test_declared_default_may_not_pass_curation(self) -> None:
        with self.assertRaises(ArmError):
            assert_lane_invariants(
                ["--intent", "implement", "--curation", "off"],
                ARMS["shipped_treatment"],
            )

    def test_native_floor_arm_wired(self) -> None:
        """B4 LANDED: the R5 native-floor arm is LIVE in the matrix.

        The arm is the in-binary R5 Explorer (`--explorer`: deterministic
        rg/glob/span retrieval, frozen policy per R5_EXPLORER_PREREG; span
        scoring vs graph-gold line ranges — range-less gold STAYS in the
        denominator). PERMANENT NEGATIVE CONTROLS: (a) `--curation off` is
        EXPLICIT — the floor can never silently take the shipped Waterfill
        treatment via omission; (b) `--graph-gold` rides with `--explorer`
        (the binary refuses `--explorer` alone); (c) a REUSE arm refuses the
        full 40-instance corpus (belt-drift protection).
        """
        arm = ARMS["native_floor"]
        self.assertTrue(arm.available)
        self.assertIs(arm.store_mode, StoreMode.REUSE)
        self.assertFalse(arm.reindex)
        self.assertTrue(arm.scored_only_corpus)
        flags = flags_for("native_floor", "ts40")
        self.assertIn("--explorer", flags)
        self.assertIn("--graph-gold", flags)  # control (b)
        self.assertEqual("off", flags[flags.index("--curation") + 1])  # control (a)
        self.assertNotIn("--reindex", flags)
        with self.assertRaises(ArmError):  # control (c)
            assert_corpus_matches_protocol("native_floor", "ts40", 40)
        assert_corpus_matches_protocol("native_floor", "ts40", 37)  # scored-only OK


class T4GoldImmutability(unittest.TestCase):
    """Freezer row 5: NEVER sort the symbol lists. Gate on DIGEST, not length."""

    ROWS = [
        {"instance_id": "b", "gold_symbols": ["z.ts:zeta", "a.ts:alpha"]},
        {"instance_id": "a", "gold_symbols": ["m.ts:mu"]},
    ]

    def test_report_order_preserved(self) -> None:
        gold = build_gold_map(self.ROWS)
        self.assertEqual(gold["b"], ["z.ts:zeta", "a.ts:alpha"])

    def test_negative_control_sorted_variant_differs_by_digest_not_length(self) -> None:
        """The sorted variant is byte-length-IDENTICAL, so a length check
        cannot see it. Only the digest can."""
        faithful = build_gold_map(self.ROWS)
        sorted_variant = {k: sorted(v) for k, v in faithful.items()}
        a = json.dumps(faithful, indent=1).encode()
        b = json.dumps(sorted_variant, indent=1).encode()
        self.assertEqual(len(a), len(b), "the trap: identical byte length")
        self.assertNotEqual(hashlib.sha256(a).digest(), hashlib.sha256(b).digest())

    def test_shipped_gold_matches_pinned_digests(self) -> None:
        sums = (PKG / "gold" / "SHA256SUMS").read_text().split()
        pinned = dict(zip(sums[1::2], sums[0::2]))
        for name, want in pinned.items():
            with self.subTest(gold=name):
                got = hashlib.sha256((PKG / "gold" / name).read_bytes()).hexdigest()
                self.assertEqual(got, want)

    def test_frozen_gold_holds_only_gold_bearing_instances(self) -> None:
        for name, want_n in (("frozen_gold_ts40.json", 37), ("frozen_gold_py_nosphinx.json", 39)):
            with self.subTest(gold=name):
                doc = json.loads((PKG / "gold" / name).read_text())
                gold = doc.get("gold", doc)
                self.assertEqual(len(gold), want_n)
                self.assertTrue(all(v for v in gold.values()))


class T5CurveRecompute(unittest.TestCase):
    """G2: the offline curve reproduces the binary from primitives."""

    GOLD = ["a.ts:f", "b.ts:g"]
    RETRIEVED = ["a.ts:f", "x.ts:h", "b.ts:g"]
    POSITIONS = [100, 400, 900]

    def test_curve_from_primitives(self) -> None:
        curve = recompute_wire_curve(
            self.GOLD, self.RETRIEVED, self.POSITIONS, (100, 500, 1000), (50, 100)
        )
        self.assertEqual(curve.by_budget[100], 0.5)
        self.assertEqual(curve.by_budget[500], 0.5)
        self.assertEqual(curve.by_budget[1000], 1.0)
        self.assertEqual(curve.tokens_to_coverage[50], 100)
        self.assertEqual(curve.tokens_to_coverage[100], 900)
        self.assertEqual(curve.delivered_tokens, 900)

    def test_misaligned_positions_raise(self) -> None:
        with self.assertRaises(ValueError):
            recompute_wire_curve(self.GOLD, self.RETRIEVED, [1, 2], (100,), (50,))

    def test_negative_control_naive_per_symbol_pricing_fails_parity(self) -> None:
        """NEGATIVE CONTROL: pricing each rank uniformly (ignoring the
        section-aware relocation) must NOT reproduce the engine's curve."""
        naive_positions = [(i + 1) * 300 for i in range(len(self.RETRIEVED))]
        faithful = recompute_wire_curve(
            self.GOLD, self.RETRIEVED, self.POSITIONS, (200,), (50,)
        )
        naive = recompute_wire_curve(
            self.GOLD, self.RETRIEVED, naive_positions, (200,), (50,)
        )
        # The first gold is paid at wire 100 under the engine's relocated
        # pricing but at 300 under uniform per-rank pricing.
        self.assertEqual(faithful.tokens_to_coverage[50], 100)
        self.assertEqual(naive.tokens_to_coverage[50], 300)
        self.assertNotEqual(faithful.by_budget[200], naive.by_budget[200])

    @unittest.skipUnless(_reports_available(), "official reports not staged")
    def test_g2_parity_on_both_public_corpora(self) -> None:
        for corpus, name in CORPUS_REPORT.items():
            with self.subTest(corpus=corpus):
                self.assertEqual(curve_parity_findings(load_report(REPORTS / name)), [])


class T8PinConsistency(unittest.TestCase):
    """Every digest in PIN.toml must equal the real file. Hand-typed digests
    are exactly the error class this gate exists to make unshippable."""

    def test_pin_gold_digests_match_files(self) -> None:
        pin = (PKG / "PIN.toml").read_text()
        checked = 0
        for path in sorted((PKG / "gold").glob("*.json")):
            want = hashlib.sha256(path.read_bytes()).hexdigest()
            with self.subTest(gold=path.name):
                self.assertIn(
                    want, pin, f"{path.name}: digest in PIN.toml does not match the file"
                )
                checked += 1
        self.assertGreater(checked, 0)

    def test_pending_pins_are_explicitly_marked(self) -> None:
        """An unwired pin must READ as unwired, never as a plausible value."""
        pin = (PKG / "PIN.toml").read_text()
        self.assertIn("READY-TO-FLIP", pin)
        # An unwired artifact URL must never look like a resolvable one.
        self.assertNotIn("https://r2", pin)
        for marker in ("bucket", "release_tag"):
            line = next(l for l in pin.splitlines() if l.startswith(marker))
            self.assertIn("READY-TO-FLIP", line)


class T6Privacy(unittest.TestCase):
    """The private corpus appears in no public artifact."""

    def test_no_private_corpus_in_package(self) -> None:
        this_file = Path(__file__).resolve()
        for path in PKG.rglob("*"):
            if not path.is_file() or "__pycache__" in path.parts:
                continue
            if path.suffix.lower() == ".json":
                continue  # gold payloads checked separately below
            if path.resolve() == this_file:
                continue  # this file must NAME the token in order to forbid it
            rel = str(path.relative_to(PKG))
            with self.subTest(path=rel):
                found = PRIVATE_CORPUS in path.read_text(errors="ignore").lower()
                self.assertFalse(found, f"private corpus name leaked into {rel}")

    def test_public_corpora_only(self) -> None:
        self.assertEqual(set(CORPORA), {"ts40", "py_nosphinx"})

    def test_gold_payloads_carry_no_private_corpus(self) -> None:
        for name in ("frozen_gold_ts40.json", "frozen_gold_py_nosphinx.json"):
            with self.subTest(gold=name):
                text = (PKG / "gold" / name).read_text().lower()
                self.assertNotIn(PRIVATE_CORPUS, text)


class T7ReportIO(unittest.TestCase):
    """The stdout-capture preamble is handled, and truncation RAISES."""

    def test_clean_json(self) -> None:
        self.assertEqual(loads_report('{"results": []}'), {"results": []})

    def test_preamble_skipped(self) -> None:
        text = 'Loaded 40 instances\nUnique repos: [..]\n{"results": [{"instance_id": "x"}]}'
        self.assertEqual(len(result_rows(loads_report(text))), 1)

    def test_truncated_capture_raises_not_partial_parse(self) -> None:
        with self.assertRaises(ReportFormatError):
            loads_report('log\n{"results": [{"instance_id":')

    def test_no_json_raises(self) -> None:
        with self.assertRaises(ReportFormatError):
            loads_report("just log output\nno document here\n")

    @unittest.skipUnless(_reports_available(), "official reports not staged")
    def test_real_captures_load(self) -> None:
        for corpus, name in CORPUS_REPORT.items():
            with self.subTest(corpus=corpus):
                report = load_report(REPORTS / name)
                self.assertGreater(len(result_rows(report)), 0)
                self.assertGreater(len(list(gold_bearing_rows(report))), 0)


class T9Acceptance(unittest.TestCase):
    """B3 ACCEPTANCE: land EXACTLY on the measurer V1 reference numbers."""

    @unittest.skipUnless(_acceptance_available(), "acceptance reports not staged")
    def test_all_cells_exact_on_replay(self) -> None:
        for corpus, path, arm in ACCEPTANCE_CELLS:
            with self.subTest(arm=arm, corpus=corpus):
                checks = check_report_file(path, corpus, arm)
                self.assertEqual(len(checks), len(LOCKED_METRICS) + 1)
                for check in checks:
                    self.assertTrue(
                        check.ok,
                        f"{arm}/{corpus}/{check.metric}: harness={check.got:.6f} "
                        f"reference={check.expected:.6f} ({check.delta_pp:+.3f}pp)",
                    )

    def test_replay_tolerance_is_four_decimals(self) -> None:
        self.assertAlmostEqual(REPLAY_TOL, 0.00005, places=9)

    def test_noise_floor_is_one_instance_scaled(self) -> None:
        """The floor sits just above ONE instance (2.70pp ts / 2.56pp py) and
        well below TWO, so a single-instance move is reported and visible
        while a two-instance move cannot pass as noise."""
        for corpus, n in (("ts40", 37), ("py_nosphinx", 39)):
            with self.subTest(corpus=corpus):
                one_instance = 100.0 / n
                self.assertGreaterEqual(NOISE_FLOOR_PP, one_instance)
                self.assertLess(NOISE_FLOOR_PP, 2 * one_instance)

    def test_fixture_digest_is_pinned(self) -> None:
        self.assertIsNotNone(load_fixture().get("provenance"))

    @unittest.skipUnless(_acceptance_available(), "acceptance reports not staged")
    def test_negative_control_wrong_arm_fixture_mismatches(self) -> None:
        """NEGATIVE CONTROL: scoring the ablation report against the shipped
        arm's reference numbers must FAIL — otherwise the gate is not reading
        the arm at all."""
        checks = check_report_file(
            _cell_report("levers_off_ablation", "ts40"), "ts40", "shipped_treatment"
        )
        self.assertTrue(any(not c.ok for c in checks))


class T10MustNot(unittest.TestCase):
    """The five measurer MUST-NOTs, each made structurally unrepresentable."""

    def test_1_scoring_always_uses_pinned_frozen_gold(self) -> None:
        """There is no report-embedded-gold scoring path to take."""
        gold = load_frozen_gold("ts40")
        self.assertEqual(len(gold), 37)
        self.assertTrue(all(v for v in gold.values()))

    def test_2_reuse_arm_refuses_full_corpus(self) -> None:
        assert_corpus_matches_protocol("levers_off_ablation", "ts40", 37)
        for wrong in (40, 39, 36):
            with self.subTest(instances=wrong), self.assertRaises(ArmError):
                assert_corpus_matches_protocol("levers_off_ablation", "ts40", wrong)

    def test_3_tier1_compares_payload_and_header_not_whole_file(self) -> None:
        """A byte-different file with an identical payload must PASS."""
        import tempfile
        anchor = {
            "corpus": "ts40", "protocol": "p", "graph_gold_derivation_version": 3,
            "total_gold_symbols": 2, "instances_with_gold": 1,
            "binary": "noodl-eval-A aaaaaaaa", "gold": {"i": ["a.ts:x", "b.ts:y"]},
        }
        candidate = dict(anchor, binary="noodl-eval-B bbbbbbbb")
        with tempfile.TemporaryDirectory() as tmp:
            a, c = Path(tmp) / "a.json", Path(tmp) / "c.json"
            a.write_text(json.dumps(anchor))
            c.write_text(json.dumps(candidate, indent=1))  # byte-different
            self.assertNotEqual(a.read_bytes(), c.read_bytes())
            result = compare_frozen_gold(c, a)
            self.assertTrue(result.ok, result.render())
            self.assertIn("binary stamp differs", result.binary_note)
            # ... and a payload ORDER change must FAIL (the freezer never sorts)
            c.write_text(json.dumps(dict(anchor, gold={"i": ["b.ts:y", "a.ts:x"]})))
            self.assertFalse(compare_frozen_gold(c, a).ok)

    def test_3b_claim_fields_are_the_five(self) -> None:
        self.assertEqual(len(CLAIM_FIELDS), 5)
        self.assertNotIn("binary", CLAIM_FIELDS)

    def test_4_gold_is_never_double_credited(self) -> None:
        """Ranked lists legitimately repeat identities; each gold counts once."""
        result = match_gold(["a.ts:f"], ["a.ts:f", "a.ts:f", "./a.ts:f"])
        self.assertEqual(result.covered, 1)
        self.assertEqual(result.match_ranks, [1])
        self.assertLessEqual(result.recall, 1.0)

    def test_5_py_at_10_is_not_superiority_claimable(self) -> None:
        from ttg.acceptance import SUPERIORITY_CLAIMABLE
        self.assertIs(SUPERIORITY_CLAIMABLE[("py_nosphinx", "head_only_at_10")], False)
        self.assertIs(SUPERIORITY_CLAIMABLE[("py_nosphinx", "head_only_at_25")], True)

    @unittest.skipUnless(_acceptance_available(), "acceptance reports not staged")
    def test_5b_reporter_annotates_the_unclaimable_metric(self) -> None:
        checks = check_report_file(
            _cell_report("shipped_treatment", "py_nosphinx"),
            "py_nosphinx", "shipped_treatment",
        )
        at10 = next(c for c in checks if c.metric == "head_only_at_10")
        self.assertIn("NOT superiority-claimable", at10.note)


class T0Identity(unittest.TestCase):
    """Identity splitting: names may contain `::`, paths may not contain `:`."""

    def test_splits_on_first_colon(self) -> None:
        self.assertEqual(split_identity("app.ts:useAuth::login"), ("app.ts", "useAuth::login"))

    def test_first_match_wins_and_ranks_are_one_indexed(self) -> None:
        result = match_gold(["src/a.py:f"], ["src/a.py:f", "./src/a.py:f"])
        self.assertEqual(result.match_ranks, [1])

    def test_uncomparable_gold_counted_not_silently_missed(self) -> None:
        result = match_gold(["../a.py:f"], ["a.py:f"])
        self.assertEqual(result.uncomparable_gold, 1)
        self.assertEqual(result.covered, 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
