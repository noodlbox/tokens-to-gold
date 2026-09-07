"""PIN.toml access and the re-certification pin gate (A4).

The re-cert pins are prepared BEFORE the lease run so the re-pin is a fill-in
rather than a rewrite. That only works if a half-filled pin cannot be used:
`validate_recert` refuses the `PENDING-RUN` sentinel AND refuses a blank or
missing field, because a silently-empty binary identity — a number published
with no traceable producer — is exactly the failure the sentinel exists to
prevent. There is no "assume it's fine" path.
"""

from __future__ import annotations

import re
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

PKG = Path(__file__).resolve().parent.parent
# Two DISTINCT sentinels for two DISTINCT lifecycles, never conflated:
#   PENDING-RUN     — the measurement identity awaits the lease run (validate_recert)
#   PENDING-RELEASE — the RELEASE binary is not yet built + published (validate_released_binary)
# The measuring binary is deliberately never the released binary, so the two
# gates are independent: the measurement can be complete (numbers publishable)
# while the release binary is still pending (R17). One shared sentinel would
# make a filled measurement silently satisfy the flip gate.
PENDING = "PENDING-RUN"
PENDING_RELEASE = "PENDING-RELEASE"
NOT_PUBLISHED = "not-published"
"""The release binary is ruled OUT of publication, not awaiting it.

Three markers, three different claims, deliberately distinct strings:
`PENDING-RUN` (the measurement has not happened), `PENDING-RELEASE` (publication
has not happened YET), `not-published` (publication will not happen). Collapsing
any two would let filling one silently satisfy another -- and would turn a
decision into a wait.

A `not-published` state MUST carry a `reason`. The artifact contract permits an
absence that is publicly EXPLAINED and forbids a silent one, so an unexplained
`not-published` is refused exactly like a blank field: it is a silent absence
with a label on it."""
_SHA256 = re.compile(r"\A[0-9a-f]{64}\Z")
_COMMIT = re.compile(r"\A[0-9a-f]{7,40}\Z")

# Fields the lease run must fill before any re-cert number is publishable.
_REQUIRED_BINARY_FIELDS = ("build_commit", "sha256", "eval_features")
# Fields the R17 release step must fill before the public flip.
_RELEASED_BINARY_FIELDS = ("release_tag", "asset_name", "sha256")


class PinError(ValueError):
    """A pin is missing, blank, or still a PENDING-RUN placeholder."""


def load_pins(path: Path | None = None) -> Mapping[str, object]:
    return tomllib.loads((path or PKG / "PIN.toml").read_text())


def _section(doc: Mapping[str, object], *names: str) -> Mapping[str, object]:
    # Editing PIN.toml by TEXT: match a section header at LINE START, never as a
    # substring. "[recert.released_binary]" also appears inside [recert.binary]'s
    # comment, so a `partition`/`index` on that string rewrites PROSE and leaves
    # the real section untouched — a scratch pin that silently still says
    # PENDING-RELEASE, i.e. a must-red that cannot go red. This has now bitten
    # twice (S313's pin test, and the not-published edit); the note lives here
    # because this is where a reader comes looking for how sections are found.
    node: object = doc
    for name in names:
        if not isinstance(node, Mapping) or name not in node:
            raise PinError(f"PIN.toml: missing section [{'.'.join(names)}]")
        node = node[name]
    if not isinstance(node, Mapping):
        raise PinError(f"PIN.toml: [{'.'.join(names)}] is not a table")
    return node


def gold_pin_mismatches(
    gold_pins: Mapping[str, object], file_digests: Mapping[str, str]
) -> list[str]:
    """Per-KEY comparison of PIN.toml [gold] against the real gold-file digests.

    `gold_pins` is the [gold] table ({frozen_gold_<corpus>: sha256}); each value
    must equal the sha256 of `gold/<key>.json`, keyed BY NAME. This is
    transposition-proof: a digest pinned under the WRONG key is a mismatch even
    though its value appears somewhere in the file — the failure a substring-
    anywhere check (`digest in pin_text`) cannot see, because it only asks
    whether the value exists, never whether it is under the right key. Returns
    one description per offending key (empty == every pin matches its named
    file)."""
    problems: list[str] = []
    for key, pinned in gold_pins.items():
        actual = file_digests.get(key)
        if actual is None:
            problems.append(f"[gold].{key} is pinned but gold/{key}.json is absent")
        elif str(pinned) != actual:
            problems.append(
                f"[gold].{key}: pin {str(pinned)[:12]} != file {actual[:12]}"
            )
    return problems


@dataclass(frozen=True)
class ArtifactTarget:
    """One pinned release attachment: filename, expected sha256, release tag."""

    name: str
    sha256: str
    release_tag: str


def artifact_targets(doc: Mapping[str, object]) -> list[ArtifactTarget]:
    """The pinned release attachments named in PIN.toml that `fetch-artifacts`
    downloads and sha-verifies: every `[[artifacts.files]]` entry (its own
    `release_tag` overriding the `[artifacts].release_tag` default). The frozen
    gold is committed in-repo, so it is not fetched.

    NO binary is a fetch target. The reproducible target is the artifact (the
    gold payload + scored curves) and the pinned committed source, NEVER a binary
    file digest — the build path bakes into the binary (BUNDLE.md publication
    contract, row 13), so downloading 213 MB to sha-check a non-repro number buys
    nothing. The `[binary]` and `[recert.binary]` sections remain as measurement
    IDENTITY, not as attachments to pull."""
    targets: list[ArtifactTarget] = []
    artifacts = doc.get("artifacts")
    if isinstance(artifacts, Mapping):
        default_tag = artifacts.get("release_tag")
        files = artifacts.get("files")
        if isinstance(files, list):
            for entry in files:
                if not (isinstance(entry, Mapping) and "name" in entry and "sha256" in entry):
                    continue
                tag = entry.get("release_tag", default_tag)
                if isinstance(tag, str):
                    targets.append(ArtifactTarget(str(entry["name"]), str(entry["sha256"]), tag))
    return targets


def is_pending(doc: Mapping[str, object]) -> bool:
    """True while the re-cert pins still await the lease run."""
    recert = _section(doc, "recert")
    if recert.get("status") == PENDING:
        return True
    binary = _section(doc, "recert", "binary")
    return any(binary.get(f) == PENDING for f in _REQUIRED_BINARY_FIELDS)


def validate_recert(doc: Mapping[str, object]) -> None:
    """Raise unless every re-cert identity field is filled with a real value.

    Refuses, in this order: a PENDING-RUN sentinel, a missing field, a blank
    field, and a malformed digest/commit. Passing this is the precondition for
    treating re-cert numbers as publishable."""
    recert = _section(doc, "recert")
    if recert.get("status") == PENDING:
        raise PinError(
            "PIN.toml [recert].status is still PENDING-RUN — the lease run has "
            "not filled the re-certification pins."
        )

    binary = _section(doc, "recert", "binary")
    for field in _REQUIRED_BINARY_FIELDS:
        value = binary.get(field)
        if value == PENDING:
            raise PinError(f"PIN.toml [recert.binary].{field} is still {PENDING}")
        if not isinstance(value, str) or not value.strip():
            raise PinError(
                f"PIN.toml [recert.binary].{field} is missing or blank — a "
                "binary identity is never allowed to be silently empty"
            )
    if not _COMMIT.fullmatch(str(binary["build_commit"])):
        raise PinError("PIN.toml [recert.binary].build_commit is not a hex commit")
    if not _SHA256.fullmatch(str(binary["sha256"])):
        raise PinError("PIN.toml [recert.binary].sha256 is not a sha256 digest")

    artifact = _section(doc, "recert", "cli_artifact")
    if not _SHA256.fullmatch(str(artifact.get("sha256", ""))):
        raise PinError("PIN.toml [recert.cli_artifact].sha256 is not a sha256 digest")


def is_release_pending(doc: Mapping[str, object]) -> bool:
    """True only while `[recert.released_binary]` still holds the PENDING-RELEASE
    sentinel — i.e. publication is an open question.

    False both when a published identity is named AND when the position is
    declared `not-published`, because neither is *pending*. Callers that need to
    tell those two apart use `released_binary_state`, not this. Orthogonal to
    `is_pending`, which is about the measurement."""
    released = _section(doc, "recert", "released_binary")
    return any(released.get(f) == PENDING_RELEASE for f in _RELEASED_BINARY_FIELDS)


def validate_released_binary(doc: Mapping[str, object]) -> None:
    """The FLIP gate: raise unless `[recert.released_binary]` states a resolved
    position on the release binary -- either a real published identity, or an
    explicit `not-published` state carrying its reason.

    What it refuses, and why each is a distinct failure:

    * `PENDING-RELEASE` -- publication has not happened yet. A go-live cannot
      proceed on a wait; the state has to be resolved one way or the other.
    * `not-published` with no reason, or a blank one -- the artifact contract
      permits an EXPLAINED absence and forbids a silent one. A state with no
      reason is a silent absence with a label on it, which is worse than the
      sentinel because it looks decided.
    * a half-filled or malformed published identity -- unchanged from before.

    The founder ruled the re-certification eval binary is an internal tool that
    is not published,
    so `not-published` is the shipped state; the publishing path stays accepted
    because it is a real state this file may hold again, not because anything
    plans to."""
    released = _section(doc, "recert", "released_binary")

    state = released.get("state")
    if state == NOT_PUBLISHED:
        reason = released.get("reason")
        if not isinstance(reason, str) or not reason.strip():
            raise PinError(
                f"PIN.toml [recert.released_binary].state is {NOT_PUBLISHED!r} but "
                "carries no reason. The artifact contract permits an absence that "
                "is publicly explained and forbids a silent one -- state the "
                "reason on one line, or the absence is unexplained"
            )
        return
    if isinstance(state, str) and state.strip():
        raise PinError(
            f"PIN.toml [recert.released_binary].state is {state!r}; the only "
            f"declared state is {NOT_PUBLISHED!r} (otherwise name a real "
            "published identity, or leave the PENDING-RELEASE sentinel)"
        )

    for field in _RELEASED_BINARY_FIELDS:
        value = released.get(field)
        if value == PENDING_RELEASE:
            raise PinError(
                f"PIN.toml [recert.released_binary].{field} is still "
                f"{PENDING_RELEASE} -- publication has not happened yet. Either "
                f"name the published binary, or declare state = {NOT_PUBLISHED!r} "
                "with a reason if it will not be published"
            )
        if not isinstance(value, str) or not value.strip():
            raise PinError(
                f"PIN.toml [recert.released_binary].{field} is missing or blank "
                "-- a released-binary identity is never allowed to be silently empty"
            )
    if not _SHA256.fullmatch(str(released["sha256"])):
        raise PinError(
            "PIN.toml [recert.released_binary].sha256 is not a sha256 digest"
        )


def released_binary_sha(doc: Mapping[str, object]) -> str | None:
    """The published binary's sha256, or `None` when there is not one.

    `None` covers both open states -- `PENDING-RELEASE` (not yet) and
    `not-published` (ruled out) -- because neither has a digest. Callers render
    the DISTINCTION honestly from `released_binary_state`; this function answers
    only "is there a published digest to quote"."""
    released = _section(doc, "recert", "released_binary")
    if released.get("state") == NOT_PUBLISHED or is_release_pending(doc):
        return None
    sha = released.get("sha256")
    return str(sha) if isinstance(sha, str) else None


def released_binary_state(doc: Mapping[str, object]) -> tuple[str, str | None]:
    """`(state, detail)` for rendering: `("not-published", reason)`,
    `("pending-release", None)`, or `("published", sha256)`.

    A single typed answer so a renderer cannot confuse "no digest yet" with "no
    digest ever" -- the two absences read identically through a bare `None`."""
    released = _section(doc, "recert", "released_binary")
    if released.get("state") == NOT_PUBLISHED:
        reason = released.get("reason")
        return NOT_PUBLISHED, str(reason) if isinstance(reason, str) else None
    if is_release_pending(doc):
        return "pending-release", None
    return "published", released_binary_sha(doc)
