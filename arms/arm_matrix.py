"""The arm matrix, as DATA — with no code path that can omit `--curation`.

THE FOOTGUN THIS MODULE EXISTS TO KILL
--------------------------------------
Post-`ceea4ab0c`, an **absent** `--curation` flag no longer means Off; it now
takes the **Waterfill** treatment. An omitted flag therefore silently turns
the baseline arm INTO a treatment arm, which inflates the baseline and
destroys the lift claim.

This is not a hypothetical. The recorded M23-P4 provenance
(`SWEEP_BINARY_MANIFEST.txt`) still asserts:

    "Flag absent => None => Off => A0 byte-identity."

That was true at `6d3ccaf0`. It is FALSE now. Anyone reproducing from the
recorded manifest reproduces the bug. A comment cannot hold this, so the
defence is structural:

1. `flags_for()` emits `--curation ...` for EVERY arm. There is no branch
   that returns a flag list without it (T3 asserts this over the whole table).
2. The runner echoes the full invocation into each cell's manifest, so the
   recorded provenance carries the ACTUAL flags rather than a prose claim
   about what a default used to mean.

TWO DISTINCT BASELINES — do not conflate (rel2-t2g-code, 2026-08-20)
--------------------------------------------------------------------
The campaign shorthand says "the A0/levers-off arm", but these are two
different flag sets on two different axes, and the M23-P4 sweep ran only the
first:

* `a0_off`     = `--curation off`                        (curation ablation;
                  the 14-cell sweep's A0 cell)
* `levers_off` = `--curation off --m22-levers-off`       (M22 lever-attribution
                  baseline; the section-5 comparison arm)

Both pass `--curation off` explicitly, so both are footgun-safe. They are
kept separate here because collapsing them would silently attribute the M22
levers' contribution to curation. Which one is the PUBLISHED section-5
baseline is a design-owner question, flagged at stop 2.

LANE INVARIANTS (S5-confirmed 2026-08-19)
-----------------------------------------
Every run passes `--intent implement` (file_index + m22-tier relocation ON)
and must NOT pass `--use-packet` — the curation override reaches only the
bare `search_with_context` arm, and `--use-packet` would route to the packet
arm and bypass it entirely. `assert_lane_invariants()` enforces both.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Final

INVARIANT_FLAGS: Final[tuple[str, ...]] = (
    "--graph-gold",
    "--raw-query",
    "--intent",
    "implement",
)
FORBIDDEN_FLAGS: Final[frozenset[str]] = frozenset({"--use-packet"})

PERFILECAPS_SIBLING: Final = 32
PERFILECAPS_MEMBER: Final = 256


class Curation(Enum):
    """How an arm sets its curation policy.

    REFINEMENT (rel2-t2g-code, 2026-08-20): the rule is NOT "never omit
    `--curation`" -- it is "never omit it BY ACCIDENT". The shipped-treatment
    arm measures the SHIPPED DEFAULT, which post-`ceea4ab0c` IS
    `Waterfill{char_budget: 65536}`, so for that arm passing no flag is the
    measurement. Making omission a DECLARED property keeps accidental
    omission unrepresentable while allowing the one arm that means it.
    """

    EXPLICIT = "explicit"
    """The arm passes `--curation ...`; omission would be a bug."""
    SHIPPED_DEFAULT = "shipped-default"
    """The arm passes NO `--curation`; a flag would defeat the measurement."""


class StoreMode(Enum):
    FRESH = "fresh"
    REUSE = "reuse"


@dataclass(frozen=True)
class Arm:
    """One arm: its curation policy AND its run protocol."""

    name: str
    policy: str
    factor: float | None
    label: str
    extra_flags: tuple[str, ...] = ()
    available: bool = True
    """False for an arm whose implementation has not landed yet (R5/B4)."""
    curation: Curation = Curation.EXPLICIT
    store_mode: StoreMode = StoreMode.FRESH
    reindex: bool = False
    scored_only_corpus: bool = False
    """MUST-NOT #2: a REUSE run on a full corpus re-analyses the excluded
    instance via fall-through (belt drift). A reuse arm REQUIRES the
    scored-only corpus, and `assert_corpus_matches_protocol` enforces it."""
    shipped_equivalent: str = ""
    """For a SHIPPED_DEFAULT arm: what the default resolves to, recorded so
    the provenance says it rather than leaving a reader to infer it."""


@dataclass(frozen=True)
class Corpus:
    """One PUBLIC corpus. Private corpora are absent by construction."""

    name: str
    char_budget_20k: int | None
    """Per-corpus 20k-equivalent char budget for waterfill/per-file-caps arms;
    the grid is 2-D (arm x corpus). None for a tier with no MEASURED budget: such
    a tier can run the budget-independent arms (shipped/levers-off/native-floor)
    but a budgeted arm refuses it rather than invent a number."""
    scored_instances: int = 0
    """The frozen gold-bearing count -- the BINDING scoring denominator."""
    corpus_instances: int = 0
    """Full corpus size, including zero-gold and errored instances."""


# --- the table (mirrors run_heldout_sweep.sh ARM_NAME/ARM_STRAT/ARM_FACTOR) ---
ARMS: Final[dict[str, Arm]] = {
    "a0_off": Arm("a0_off", "off", None, "off"),
    "wf_b1": Arm("wf_b1", "waterfill", 1.0, "20k"),
    "wf_b2": Arm("wf_b2", "waterfill", 0.9, "18k"),
    "wf_b3": Arm("wf_b3", "waterfill", 0.8, "16k"),
    "pfc_b1": Arm("pfc_b1", "perfilecaps", 1.0, "20k"),
    "pfc_b2": Arm("pfc_b2", "perfilecaps", 0.9, "18k"),
    "pfc_b3": Arm("pfc_b3", "perfilecaps", 0.8, "16k"),
    # --- the two ACCEPTANCE arms (measurer V1 reference fixture) ---
    # protocol_treatment: --graph-gold --raw-query --intent implement
    #                     --reindex --timeout 400 -f json  (FRESH store, NO --curation)
    "shipped_treatment": Arm(
        "shipped_treatment", "shipped-default", None, "shipped",
        curation=Curation.SHIPPED_DEFAULT,
        store_mode=StoreMode.FRESH,
        reindex=True,
        shipped_equivalent="waterfill:65536",
    ),
    # protocol_ablation: same + --curation off --m22-levers-off,
    #                    REUSE store, NO --reindex, SCORED-ONLY corpora
    # Q4 RULING (design owner, 2026-08-20): THIS is the published section-5
    # baseline -- "levers-off base-config": Implement with curation Off AND
    # the M22 admission levers Off. It is what the measurer actually ran for
    # the pinned reference numbers, and it reproduces the signed S7
    # base-config baseline exactly. `a0_off` stays a SEPARATE sweep cell
    # (curation-only decomposition) and its numbers must NEVER be labelled
    # levers-off.
    "levers_off_ablation": Arm(
        "levers_off_ablation", "off", None, "levers-off base-config",
        extra_flags=("--m22-levers-off",),
        curation=Curation.EXPLICIT,
        store_mode=StoreMode.REUSE,
        reindex=False,
        scored_only_corpus=True,
    ),
    # B4 (LANDED 2026-08-26): the R5 native-floor arm — the in-binary R5
    # Explorer (`--explorer`): deterministic graph-free rg/glob/span retrieval,
    # frozen policy per R5_EXPLORER_PREREG_2026-07-23 (context ±25 lines,
    # whole-file ≤150 lines, ≤24 terms, source-only globs). Scoring is the
    # in-binary span-intersection vs graph-gold line ranges (evaluator
    # `evaluate_explorer`): first covering span per gold, same file + line
    # overlap; a RANGE-LESS gold identity is uncoverable and STAYS in the
    # denominator (pre-registered denominator rule — dropping it would flatter
    # the comparator). Wire == read by design (spans ARE read content), priced
    # by the same walk as every other arm. `--curation off` is EXPLICIT and
    # inert on the explorer path — it satisfies the lane invariant; omission
    # would silently mean the Waterfill treatment on the other paths.
    # Protocol: FRESH store + --reindex on the FULL corpora — the official
    # protocol shape. (PROTOCOL REVISION 2026-08-26: the first wiring ran
    # REUSE + scored-only to save ~15 min; a mid-run disk collapse turned the
    # box-reuse fall-through into failing re-analysis that DELETED catalog
    # rows from the reused store — see the incident note in the preservation
    # tree. REUSE silently depends on a warm checkout cache and a stable
    # disk, neither of which this arm can guarantee; FRESH is self-contained.)
    "native_floor": Arm(
        "native_floor", "off", None, "native-floor",
        extra_flags=("--explorer",),
        curation=Curation.EXPLICIT,
        store_mode=StoreMode.FRESH,
        reindex=True,
        scored_only_corpus=False,
    ),
}

# The 7-arm sweep (`--arms all`), in the order the M23-P4 runner used.
SWEEP_ARMS: Final[tuple[str, ...]] = (
    "a0_off", "wf_b1", "wf_b2", "wf_b3", "pfc_b1", "pfc_b2", "pfc_b3",
)
# Q1 RULING: default to the two headline cells — treatment + A0. Reproducing
# the CLAIM should be cheap; reproducing the SWEEP should be possible.
TREATMENT_ARM: Final = "wf_b3"
DEFAULT_ARMS: Final[tuple[str, ...]] = (TREATMENT_ARM, "a0_off")
# Section 5 of the public write-up: treatment / levers-off / native-floor.
SECTION5_ARMS: Final[tuple[str, ...]] = (
    "shipped_treatment", "levers_off_ablation", "native_floor",
)

CORPORA: Final[dict[str, Corpus]] = {
    "ts40": Corpus("ts40", 90_320, scored_instances=37, corpus_instances=40),
    "py_nosphinx": Corpus("py_nosphinx", 93_000, scored_instances=39, corpus_instances=40),
    # The 2026-09 re-cert tiers. char_budget_20k is None: no waterfill/
    # per-file-caps arm is pre-registered for them (only shipped_treatment /
    # levers_off_ablation / native_floor, none of which reads a budget), so a
    # budgeted arm REFUSES them rather than run on an invented budget, while the
    # `flags` parser still accepts them as valid corpora.
    "go34": Corpus("go34", None, scored_instances=30, corpus_instances=34),
    "rust43": Corpus("rust43", None, scored_instances=40, corpus_instances=43),
}

ACCEPTANCE_ARMS: Final[tuple[str, ...]] = ("shipped_treatment", "levers_off_ablation")


class ArmError(ValueError):
    """An unknown, unavailable, or malformed arm request."""


def char_budget(arm_name: str, corpus_name: str) -> int | None:
    """`char_budget(arm, corpus) = COR_CB20K[corpus] * ARM_FACTOR[arm]`.

    A budgeted arm on a corpus with no measured budget REFUSES rather than
    invents one -- the guard that keeps a waterfill/per-file-caps arm off the
    re-cert tiers (go34/rust43), which carry no base_20k."""
    arm = _arm(arm_name)
    if arm.factor is None:
        return None
    budget = _corpus(corpus_name).char_budget_20k
    if budget is None:
        raise ArmError(
            f"arm {arm_name!r} needs a per-corpus char budget, but {corpus_name!r} "
            "has none (no measured base_20k). Only the budget-independent arms "
            "(shipped_treatment, levers_off_ablation, native_floor) run on it"
        )
    return int(budget * arm.factor)


def _arm(name: str) -> Arm:
    try:
        arm = ARMS[name]
    except KeyError:
        raise ArmError(
            f"unknown arm {name!r}; known: {', '.join(sorted(ARMS))}"
        ) from None
    if not arm.available:
        raise ArmError(
            f"arm {name!r} is registered but not yet implemented (awaiting B4/R5); "
            "the matrix accepts it so the third section-5 arm needs no schema change"
        )
    return arm


def _corpus(name: str) -> Corpus:
    try:
        return CORPORA[name]
    except KeyError:
        raise ArmError(
            f"unknown corpus {name!r}; public corpora: {', '.join(sorted(CORPORA))}"
        ) from None


def curation_flag(arm_name: str, corpus_name: str) -> list[str]:
    """The `--curation ...` pair for this cell. NEVER returns empty.

    Every branch below yields the flag. An arm whose policy is unrecognised
    RAISES rather than falling through to an omission — omission is the bug
    this module exists to prevent.
    """
    arm = _arm(arm_name)
    if arm.curation is Curation.SHIPPED_DEFAULT:
        # DELIBERATE omission: this arm measures the shipped default
        # (= {equiv}). Passing a flag here would defeat the measurement.
        return []
    if arm.policy == "off":
        return ["--curation", "off"]
    budget = char_budget(arm_name, corpus_name)
    if budget is None:
        raise ArmError(f"arm {arm_name!r} has policy {arm.policy!r} but no budget factor")
    if arm.policy == "waterfill":
        return ["--curation", f"waterfill:{budget}"]
    if arm.policy == "perfilecaps":
        return [
            "--curation",
            f"perfilecaps:{PERFILECAPS_SIBLING},{PERFILECAPS_MEMBER},{budget}",
        ]
    raise ArmError(f"arm {arm_name!r} has unknown policy {arm.policy!r}")


def flags_for(arm_name: str, corpus_name: str) -> list[str]:
    """The COMPLETE flag list for one cell: invariants + curation + extras."""
    arm = _arm(arm_name)
    flags = [*INVARIANT_FLAGS, *curation_flag(arm_name, corpus_name), *arm.extra_flags]
    if arm.reindex:
        flags.append("--reindex")
    assert_lane_invariants(flags, arm)
    return flags


def assert_corpus_matches_protocol(
    arm_name: str, corpus_name: str, instances: int
) -> None:
    """MUST-NOT #2: a REUSE arm may only run the SCORED-ONLY corpus.

    Running the full 40-instance corpus against a warm store re-analyses the
    excluded instance through fall-through, which drifts the belt. A reuse
    arm therefore REFUSES any corpus that is not the scored subset.
    """
    arm = _arm(arm_name)
    corpus = _corpus(corpus_name)
    if not arm.scored_only_corpus:
        return
    if instances != corpus.scored_instances:
        raise ArmError(
            f"arm {arm_name!r} is a REUSE arm and requires the SCORED-ONLY "
            f"{corpus_name} corpus ({corpus.scored_instances} instances), but "
            f"was given {instances}. Running the full corpus on a warm store "
            "re-analyses the excluded instance via fall-through (belt drift)"
        )


def assert_lane_invariants(flags: Sequence[str], arm: Arm | None = None) -> None:
    """Fail loudly on an UNDECLARED `--curation` omission or a forbidden flag."""
    declared_default = arm is not None and arm.curation is Curation.SHIPPED_DEFAULT
    if "--curation" not in flags and not declared_default:
        raise ArmError(
            "lane invariant violated: no --curation flag, and no arm declared "
            "Curation.SHIPPED_DEFAULT. An ABSENT flag is NOT 'off' "
            "post-ceea4ab0c — it takes the Waterfill treatment, which "
            "silently converts a baseline into a treatment arm"
        )
    if "--curation" in flags and declared_default:
        raise ArmError(
            f"arm {arm.name!r} declares SHIPPED_DEFAULT but passes --curation; "
            "a flag defeats the measurement of the shipped default"
        )
    forbidden = FORBIDDEN_FLAGS.intersection(flags)
    if forbidden:
        raise ArmError(
            f"lane invariant violated: {sorted(forbidden)} would route to the "
            "packet arm and bypass the curation override entirely"
        )
    if "--intent" not in flags:
        raise ArmError("lane invariant violated: --intent implement is required")


def cells(
    arm_names: Sequence[str], corpus_names: Sequence[str]
) -> list[tuple[str, str, list[str]]]:
    """Every `(arm, corpus, flags)` cell for a requested matrix."""
    return [
        (arm, corpus, flags_for(arm, corpus))
        for arm in arm_names
        for corpus in corpus_names
    ]
