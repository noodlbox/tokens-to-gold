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
    """True while `[recert.released_binary]` still holds the PENDING-RELEASE
    sentinel — the state R16 ships in. The measuring binary ([recert.binary]) is
    NOT the released binary: the released binary is a distinct, later artifact
    built + published at R17. This is orthogonal to `is_pending` (measurement)."""
    released = _section(doc, "recert", "released_binary")
    return any(released.get(f) == PENDING_RELEASE for f in _RELEASED_BINARY_FIELDS)


def validate_released_binary(doc: Mapping[str, object]) -> None:
    """The FLIP gate (R17): raise unless `[recert.released_binary]` names a real,
    published binary. It FAILS by design while R16 stands — the measuring binary
    is deliberately never published, so the release identity is the PENDING-RELEASE
    sentinel until the public binary is built and uploaded. `validate-pins --flip`
    runs this so a go-live cannot proceed on the measurement sentinel; it is a
    SEPARATE gate from `validate_recert`, which only asserts the measurement
    identity is complete."""
    released = _section(doc, "recert", "released_binary")
    for field in _RELEASED_BINARY_FIELDS:
        value = released.get(field)
        if value == PENDING_RELEASE:
            raise PinError(
                f"PIN.toml [recert.released_binary].{field} is still "
                f"{PENDING_RELEASE} — the release binary has not been built and "
                "published (R17); the measuring binary is never the released one"
            )
        if not isinstance(value, str) or not value.strip():
            raise PinError(
                f"PIN.toml [recert.released_binary].{field} is missing or blank "
                "— a released-binary identity is never allowed to be silently empty"
            )
    if not _SHA256.fullmatch(str(released["sha256"])):
        raise PinError(
            "PIN.toml [recert.released_binary].sha256 is not a sha256 digest"
        )


def released_binary_sha(doc: Mapping[str, object]) -> str | None:
    """The PUBLIC binary's sha256 once R17 has filled `[recert.released_binary]`,
    else None while it is still the PENDING-RELEASE sentinel. Callers render this
    honestly (pending vs published), never refuse on the pending state."""
    if is_release_pending(doc):
        return None
    sha = _section(doc, "recert", "released_binary").get("sha256")
    return str(sha) if isinstance(sha, str) else None
