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
from ttg import privacy as _privacy
from ttg.own_repo import (
    OWN_REPO_ARMS, OwnRepoError, build_instance, own_repo_flags,
)
from ttg.comparable_path import ComparablePath, PathComparison, compare_paths
from ttg.curve_recompute import curve_parity_findings, recompute_wire_curve
from ttg.gold_freezer import build_gold_map
from ttg.matcher import match_gold, split_identity
from ttg.report_io import ReportFormatError, gold_bearing_rows, load_report, loads_report, result_rows
from ttg.acceptance import (
    FIXTURE_PATH, LOCKED_METRICS, NOISE_FLOOR_PP, REPLAY_TOL, AcceptanceError,
    _pinned_digest, check_report_file, load_fixture, load_frozen_gold,
)
from ttg.pins import gold_pin_mismatches, load_pins
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
        "reach_at_80_whole_list": arms["shipped_treatment"]["reach_at_80_whole_list"],
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
PRIVATE_CORPUS = _privacy.PRIVATE_CORPUS


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
                self.assertAlmostEqual(roll.binding.reach_at_coverage[80], want["reach_at_80_whole_list"], places=4)

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
                    roll.engine_basis.reach_at_coverage[80], want["reach_at_80_whole_list"], places=4
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
            for corpus_name, corpus in CORPORA.items():
                # A budgeted arm (factor set) refuses a corpus with no measured
                # base_20k (the re-cert tiers) -- skip those cells; they are
                # guarded by test_a_budgeted_arm_on_a_new_tier_raises_armerror.
                if arm.factor is not None and corpus.char_budget_20k is None:
                    continue
                with self.subTest(arm=name, corpus=corpus_name):
                    self.assertIn("--curation", flags_for(name, corpus_name))

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
        # SWEEP/DEFAULT arms are the budgeted V1 sweep; they resolve only over
        # the two corpora that carry a base_20k (the re-cert tiers have none).
        budgeted = [c for c, cor in CORPORA.items() if cor.char_budget_20k is not None]
        self.assertEqual(budgeted, ["ts40", "py_nosphinx"])
        self.assertEqual(len(cells(SWEEP_ARMS, budgeted)), 14)
        self.assertEqual(len(cells(DEFAULT_ARMS, budgeted)), 4)
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
        denominator). PROTOCOL (revised 2026-08-26 after the reuse-store
        incident): FRESH store + `--reindex` on the FULL corpus — the arm is
        self-contained and never depends on a reusable store's health.
        PERMANENT NEGATIVE CONTROLS: (a) `--curation off` is EXPLICIT — the
        floor can never silently take the shipped Waterfill treatment via
        omission; (b) `--graph-gold` rides with `--explorer` (the binary
        refuses `--explorer` alone); (c) as a FRESH arm it accepts the full
        corpus (a REUSE floor was the incident — asserting FRESH here is the
        control that stops it silently coming back).
        """
        arm = ARMS["native_floor"]
        self.assertTrue(arm.available)
        self.assertIs(arm.store_mode, StoreMode.FRESH)  # control (c)
        self.assertTrue(arm.reindex)
        self.assertFalse(arm.scored_only_corpus)
        flags = flags_for("native_floor", "ts40")
        self.assertIn("--explorer", flags)
        self.assertIn("--graph-gold", flags)  # control (b)
        self.assertEqual("off", flags[flags.index("--curation") + 1])  # control (a)
        self.assertIn("--reindex", flags)
        assert_corpus_matches_protocol("native_floor", "ts40", 40)  # full corpus OK


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
        # FINDING A: per-KEY, not substring-anywhere. Each [gold] pin must equal
        # the digest of the file it NAMES, so a digest pinned under the wrong key
        # (a transposition) is caught — the earlier `assertIn(digest, pin_text)`
        # only asked whether the value existed somewhere, blind to which key.
        gold_pins = load_pins().get("gold", {})
        file_digests = {
            p.stem: hashlib.sha256(p.read_bytes()).hexdigest()
            for p in (PKG / "gold").glob("*.json")
        }
        problems = gold_pin_mismatches(gold_pins, file_digests)
        self.assertEqual(problems, [], problems)
        self.assertGreater(len(gold_pins), 0, "no gold pins in PIN.toml [gold]")

    def test_tracked_gold_files_are_pinned(self) -> None:
        # Completeness, scoped to TRACKED gold: a committed gold file must have a
        # [gold] pin. Untracked tiers (go34/rust43 before the A4 gold commit) are
        # out of scope here — they join when they are committed and pinned.
        import subprocess

        gold_pins = load_pins().get("gold", {})
        tracked = subprocess.run(
            ["git", "ls-files", "-z", "gold"],
            cwd=PKG, capture_output=True, text=True, check=True,
        ).stdout.split("\0")
        checked = 0
        for rel in tracked:
            if not (rel.startswith("gold/frozen_gold_") and rel.endswith(".json")):
                continue
            with self.subTest(gold=rel):
                self.assertIn(
                    Path(rel).stem, gold_pins, f"tracked {rel} not pinned in [gold]"
                )
            checked += 1
        self.assertGreater(checked, 0, "no tracked gold files")

    def test_transposed_gold_pin_is_caught(self) -> None:
        # MUST-RED / permanent negative control (Finding A), from raw strings: a
        # transposition — each real digest pinned under the OTHER key.
        a, b = "a" * 64, "b" * 64
        pins = {"frozen_gold_ts40": b, "frozen_gold_py_nosphinx": a}  # swapped
        files = {"frozen_gold_ts40": a, "frozen_gold_py_nosphinx": b}  # real
        self.assertEqual(len(gold_pin_mismatches(pins, files)), 2)
        # NEGATIVE CONTROL: the earlier substring-anywhere check MISSES it — both
        # digests are present in the serialized pin text, just under wrong keys.
        pin_text = f'frozen_gold_ts40 = "{b}"\nfrozen_gold_py_nosphinx = "{a}"\n'
        self.assertIn(a, pin_text)
        self.assertIn(b, pin_text)

    def test_pending_pins_are_explicitly_marked(self) -> None:
        """An unwired pin must READ as unwired, never as a plausible value.

        POST-WIRING (2026-08-26): every artifact pin is now a real value
        (release attachments on this repo). The ONE remaining pending item is
        the visibility flip, and it must still read as pending — while no pin
        VALUE may be a placeholder that could be mistaken for a location.
        """
        pin = (PKG / "PIN.toml").read_text()
        # The one pending item — the public flip — still reads as pending:
        self.assertIn('visibility = "private"', pin)
        self.assertIn("READY-TO-FLIP", pin)
        # No pin VALUE is a placeholder (markers live in comments only), and
        # nothing pretends to be an R2 URL:
        self.assertNotIn("<READY-TO-FLIP", pin)
        self.assertNotIn("https://r2", pin)
        # Every value-bearing pin line is concrete:
        for key in ("release_tag", "asset_name", "sha256", "url", "clone_url"):
            for line in pin.splitlines():
                if line.startswith(key):
                    self.assertNotIn(
                        "READY-TO-FLIP", line, f"{key} still carries a placeholder"
                    )


class T6Privacy(unittest.TestCase):
    """The held-out corpus appears nowhere on the PUBLISHED surface.

    The surface is three things and all three ship: the TRACKED files (what a
    clone gets), the CERTIFIED artifact tree (published as release attachments,
    per PIN.toml), and the GIT HISTORY (commit messages ride in every clone).
    Every file is scanned as TEXT -- .json INCLUDED, because the gold payloads,
    the acceptance fixture, and the certified reports are all JSON and the
    earlier scan skipped every .json, leaving the hole exactly where the gold
    lives (measured: 3 tracked .json existed, 0 were scanned). The check is the
    contiguous-token detector `ttg.privacy.contains_private`, so a fragment-
    built holder (`ttg.privacy` itself) is safe by construction and needs no
    self-exclusion. Scope is the published surface, NOT `rglob('*')`: untracked
    scratch and non-certified run intermediates never ship, so scanning them
    would raise false leaks while missing the history that does ship."""

    CERTIFIED = PKG / "runs" / "recert-2026-09" / "certified"

    @classmethod
    def _published_files(cls) -> tuple[list[Path], bool]:
        """The published surface AND whether the certified tree was present.

        Returns the flag so the caller can REPORT it (fold F): the earlier
        `if certified.is_dir()` silently shrank the surface (73/17 -> 55/3) when
        the certified tree was absent, passing a smaller scan as if complete."""
        import subprocess

        tracked = subprocess.run(
            ["git", "ls-files", "-z"],
            cwd=PKG, capture_output=True, text=True, check=True,
        ).stdout.split("\0")
        files = {PKG / p for p in tracked if p}
        cert_present = cls.CERTIFIED.is_dir()
        if cert_present:
            # The certified tree ships as release attachments (PIN.toml).
            files.update(cls.CERTIFIED.rglob("*"))
        surface = sorted(
            f for f in files if f.is_file() and "__pycache__" not in f.parts
        )
        return surface, cert_present

    @staticmethod
    def _scan(files: list[Path]) -> list[str]:
        """Offenders: files whose TEXT carries the contiguous private token. No
        .json skip -- a JSON payload is text like any other file."""
        return [
            str(p)
            for p in files
            if _privacy.contains_private(p.read_text(errors="ignore"))
        ]

    def test_no_private_corpus_on_published_surface(self) -> None:
        surface, cert_present = self._published_files()
        json_count = sum(1 for f in surface if f.suffix.lower() == ".json")
        # REPORT the scope with the environment (fold F) — never a silent scan.
        print(
            f"\nT6 surface: {len(surface)} files, {json_count} .json, "
            f"certified_tree_present={cert_present}"
        )
        # NEVER no-op on a missing certified dir: the certified artifacts are part
        # of the published surface, so their absence FAILS LOUD rather than
        # shrinking the scan silently. (A5 moves this scan to the fetch-first
        # acceptance suite so a clone fetches, then scans, rather than skipping.)
        self.assertTrue(
            cert_present,
            "certified tree absent — the published surface would silently shrink "
            "(73/17 -> 55/3); run reproduce.sh verify (fetch-artifacts). This "
            "scan does not no-op.",
        )
        offenders = self._scan(surface)
        self.assertEqual(offenders, [], f"private corpus leaked into: {offenders}")

    def test_surface_includes_json_and_certified_when_present(self) -> None:
        # Fold H: a surface-side invariant, so a bug in _published_files (which
        # Finding C was) cannot leave the .json/certified plant test green while
        # the real scan misses those files.
        surface, cert_present = self._published_files()
        self.assertGreaterEqual(
            sum(1 for f in surface if f.suffix.lower() == ".json"),
            1,
            "published surface has no .json — the scan would miss gold/fixture JSON",
        )
        if cert_present:
            self.assertTrue(
                any(self.CERTIFIED in f.parents for f in surface),
                "certified tree present but absent from the scanned surface",
            )

    def test_git_history_carries_no_private_corpus(self) -> None:
        import subprocess

        # Every commit message ships in the history of every clone.
        log = subprocess.run(
            ["git", "log", "--format=%B"],
            cwd=PKG, capture_output=True, text=True, check=True,
        ).stdout
        self.assertFalse(
            _privacy.contains_private(log), "private corpus in commit history"
        )

    def test_public_corpora_only(self) -> None:
        # V1 shipped two; the 2026-09 re-cert added the go34/rust43 tiers. The
        # held-out corpus must still never appear.
        self.assertEqual(set(CORPORA), {"ts40", "py_nosphinx", "go34", "rust43"})

    def test_gold_payloads_carry_no_private_corpus(self) -> None:
        # DERIVED from CORPORA, never a hardcoded pair: a newly-added tier's gold
        # is scanned automatically, so a tier cannot silently escape the check.
        checked = 0
        for corpus in CORPORA:
            gold = PKG / "gold" / f"frozen_gold_{corpus}.json"
            if not gold.is_file():
                continue
            with self.subTest(gold=gold.name):
                self.assertFalse(_privacy.contains_private(gold.read_text()))
            checked += 1
        self.assertGreater(checked, 0, "no tier gold scanned")

    def test_json_leak_is_scanned_not_skipped(self) -> None:
        # PERMANENT NEGATIVE CONTROL (Finding C): the earlier scan skipped every
        # .json, so a token planted in a gold / fixture / certified-report JSON
        # was invisible. A planted .json on the scanned surface MUST be flagged.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            leak = Path(tmp) / "frozen_gold_go34.json"
            leak.write_text(
                json.dumps({"gold": {"i": [f"{PRIVATE_CORPUS}/pkg.go:fn"]}})
            )
            self.assertEqual(leak.suffix.lower(), ".json")
            self.assertEqual(self._scan([leak]), [str(leak)])


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

    def test_absent_pin_raises_not_fail_open(self) -> None:
        # FINDING B: an absent pin must THROW, never silently load unverified
        # bytes. RED before the fix (`if pinned and got != pinned` skipped the
        # check entirely for a missing pin and returned the fixture); GREEN after.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / FIXTURE_PATH.name
            fixture.write_text('{"provenance": {}}')
            sums = Path(tmp) / "SHA256SUMS"
            sums.write_text("deadbeef  some_other_file.json\n")  # fixture NOT pinned
            with self.assertRaises(AcceptanceError):
                load_fixture(fixture_path=fixture, sums_path=sums)

    def test_present_pin_verifies_and_loads(self) -> None:
        # Positive control: a correctly-pinned fixture loads through the seam.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            fixture = Path(tmp) / FIXTURE_PATH.name
            body = b'{"provenance": {"ok": true}}'
            fixture.write_bytes(body)
            sums = Path(tmp) / "SHA256SUMS"
            sums.write_text(f"{hashlib.sha256(body).hexdigest()}  {fixture.name}\n")
            self.assertIsNotNone(load_fixture(fixture, sums).get("provenance"))

    def test_pinned_digest_helper_raises_on_absent(self) -> None:
        # The predicate in isolation, from raw text: absent name RAISES, present
        # name returns its digest.
        with self.assertRaises(AcceptanceError):
            _pinned_digest("abc123  other.json\n", FIXTURE_PATH.name)
        self.assertEqual(_pinned_digest("abc123  wanted.json\n", "wanted.json"), "abc123")

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


class T9OwnRepo(unittest.TestCase):
    """B7: the bring-your-own-merged-PR flow (the freezer path, ruled)."""

    PR = {
        "merged_at": "2026-08-01T00:00:00Z",
        "merge_commit_sha": "m" * 40,
        "title": "Fix the widget resolver",
        "body": "The resolver drops nested widgets.",
    }
    MERGE_COMMIT = {"parents": [{"sha": "p" * 40}]}
    PATCH = "diff --git a/w.ts b/w.ts\n--- a/w.ts\n+++ b/w.ts\n@@ -1 +1 @@\n-x\n+y\n"

    def test_instance_built_from_merged_pr(self) -> None:
        inst = build_instance("acme/widgets", 7, self.PR, self.MERGE_COMMIT, self.PATCH)
        self.assertEqual("acme-widgets-pr7", inst.instance_id)
        self.assertEqual("p" * 40, inst.base_commit)  # FIRST PARENT, not base.sha
        self.assertIn("Fix the widget resolver", inst.problem_statement)
        self.assertIn("nested widgets", inst.problem_statement)
        row = json.loads(inst.to_jsonl_row())
        self.assertEqual(
            {"instance_id", "repo", "base_commit", "problem_statement", "patch"},
            set(row),
        )

    def test_unmerged_pr_refused(self) -> None:
        """NEGATIVE CONTROL: an unmerged PR has no landed patch — no gold."""
        pr = dict(self.PR, merged_at=None)
        with self.assertRaises(OwnRepoError):
            build_instance("acme/widgets", 7, pr, self.MERGE_COMMIT, self.PATCH)

    def test_empty_patch_refused(self) -> None:
        """NEGATIVE CONTROL: an empty diff means nothing landed."""
        with self.assertRaises(OwnRepoError):
            build_instance("acme/widgets", 7, self.PR, self.MERGE_COMMIT, "   ")

    def test_thin_statement_is_disclosed_not_refused(self) -> None:
        """A body-less PR runs, but the thin query is DISCLOSED with the readout."""
        pr = dict(self.PR, body="")
        inst = build_instance("acme/widgets", 7, pr, self.MERGE_COMMIT, self.PATCH)
        self.assertTrue(any("THIN" in d for d in inst.disclosures))

    def test_own_repo_flags_reuse_the_lane_invariants(self) -> None:
        """The section-5 arms compose; omission stays unrepresentable."""
        for arm in OWN_REPO_ARMS:
            flags = own_repo_flags(arm)
            self.assertIn("--graph-gold", flags)
            if arm == "shipped_treatment":
                self.assertNotIn("--curation", flags)  # measures the default
            else:
                self.assertEqual("off", flags[flags.index("--curation") + 1])
        self.assertIn("--explorer", own_repo_flags("native_floor"))

    def test_budgeted_sweep_arm_refused(self) -> None:
        """NEGATIVE CONTROL: a char budget is a property of a FROZEN corpus;
        an own-repo run has none, so a budgeted arm must fail loudly."""
        with self.assertRaises(ArmError):
            own_repo_flags("wf_b3")


class T10DeriveGoldScript(unittest.TestCase):
    """The L1 script actually RUNS end-to-end (the slow path rots silently:
    its freezer invocation shipped broken because nothing executed it — caught
    by the 2026-08-26 own-repo smoke, fixed, and pinned here with a stub
    binary so it can never ship broken again)."""

    def test_derive_gold_runs_with_a_stub_binary(self) -> None:
        import subprocess
        import tempfile

        with tempfile.TemporaryDirectory() as td:
            tmp = Path(td)
            report = {
                "dataset": "stub", "k": 25, "total_instances": 1,
                "evaluated_instances": 1, "failed_instances": 0,
                "gold_arm": "graph_gold", "graph_gold_derivation_version": 4,
                "aggregate_semantics_version": 2, "total_time_secs": 0.1,
                "results": [{
                    "instance_id": "stub-1",
                    "repo": "acme/stub",
                    "gold_symbol_count": 2,
                    "gold_symbols": ["b.ts:beta", "a.ts:alpha"],
                    "retrieved_symbols": [],
                }],
                "aggregate": {},
            }
            stub = tmp / "stub-binary"
            stub.write_text(
                "#!/bin/sh\ncat <<'EOF'\n" + json.dumps(report) + "\nEOF\n"
            )
            stub.chmod(0o755)
            jsonl = tmp / "instance.jsonl"
            jsonl.write_text(
                json.dumps({"instance_id": "stub-1", "repo": "acme/stub",
                            "base_commit": "x", "problem_statement": "p",
                            "patch": "d"}) + "\n"
            )
            proc = subprocess.run(
                [str(PKG / "ttg" / "derive_gold.sh"),
                 "--corpus", "stub_corpus", "--binary", str(stub),
                 "--corpus-jsonl", str(jsonl), "--store", str(tmp / "store"),
                 "--outdir", str(tmp / "gold")],
                capture_output=True, text=True, cwd=PKG,
            )
            self.assertEqual(0, proc.returncode, proc.stdout + proc.stderr)
            frozen = tmp / "gold" / "frozen_gold_stub_corpus.json"
            self.assertTrue(frozen.exists(), proc.stdout)
            doc = json.loads(frozen.read_text())
            # freezer row 5: report order preserved, never sorted
            self.assertEqual(["b.ts:beta", "a.ts:alpha"], doc["gold"]["stub-1"])
            # an own/unknown corpus skips Tier-1 EXPLICITLY, never crashes on
            # the missing shipped-gold file
            self.assertIn("Tier-1 n/a", proc.stdout)

