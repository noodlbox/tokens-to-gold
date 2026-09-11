"""Validate and reproduce the TokensToGold V2 Tier A A1 publication package."""

from __future__ import annotations

import argparse
import csv
import ctypes
import errno
import hashlib
import json
import os
import re
import shutil
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from decimal import Decimal, InvalidOperation
from pathlib import Path, PurePosixPath
from typing import Any, Final

PACKAGE_ROOT: Final = Path(__file__).resolve().parent
REPO_ROOT: Final = PACKAGE_ROOT.parent
AUTHORITY_PATH: Final = PACKAGE_ROOT / "authority.json"
PROVENANCE_PATH: Final = PACKAGE_ROOT / "provenance.tsv"
CHECKSUM_PATH: Final = PACKAGE_ROOT / "SHA256SUMS"
SCHEMA_VERSION: Final = "ttg-v2-tier-a-a1-authority/v2"

AUTHORITY_KEYS: Final = {
    "schema_version",
    "package",
    "gates",
    "evidence_roles",
    "measurement",
    "systems",
    "arms",
    "corpora",
    "denominators",
    "failure_sets",
    "execution_witnesses",
    "results",
    "scoring_implementation",
    "evidence_bundle",
}
PROVENANCE_FIELDS: Final = [
    "kind",
    "id",
    "version",
    "sha256",
    "local_audit_path",
    "release_path",
    "public_locator",
    "state",
    "corpus_id",
    "arm_id",
    "system_id",
    "note",
]
PACKAGE_PAYLOAD_MEMBERS: Final = {
    "BUNDLE.md",
    "README.md",
    "RESULTS.md",
    "STATUS.md",
    "authority.json",
    "provenance.tsv",
    "verify.py",
    "verify.sh",
}
PACKAGE_FILES: Final = PACKAGE_PAYLOAD_MEMBERS | {"SHA256SUMS"}
DIGEST_RE: Final = re.compile(r"[0-9a-f]{64}")
FRACTION_RE: Final = re.compile(r"(?:0\.[0-9]{9}|1\.000000000)")
PACKAGE_SUM_RE: Final = re.compile(r"([0-9a-f]{64})  ([A-Za-z0-9_.-]+)")
KIND_STATES: Final = {
    "source_table": {"verified"},
    "preregistration": {"verified"},
    "doctrine": {"verified"},
    "corpus": {"verified"},
    "frozen_gold": {"verified"},
    "producer": {"identity-only", "declared-only"},
    "tokenizer": {"declared-only"},
    "run_header": {"verified"},
    "corpus_manifest": {"verified"},
    "report": {"verified"},
    "report_manifest": {"verified"},
    "publication_anchor": {"public-verified"},
    "evidence_release": {"public-verified"},
    "paired_uncertainty": {"verified", "public-verified"},
    "tier_b_result": {"public-verified"},
    "codedb_result": {"public-verified"},
}
FILE_STATES: Final = {"verified", "public-verified"}
GATE_LIFECYCLES: Final = {
    "publication": {
        "pending_review": (False, frozenset()),
        "published": (True, frozenset({"publication_anchor"})),
    },
    "public_evidence_retrieval": {
        "unavailable": (False, frozenset()),
        "available": (True, frozenset({"evidence_release"})),
    },
    "public_reproduction": {
        "unavailable": (False, frozenset()),
        "available": (True, frozenset({"evidence_release"})),
    },
    "paired_uncertainty": {
        "required_pending": (False, frozenset()),
        "available": (True, frozenset({"paired_uncertainty"})),
    },
    "tier_b_whole_agent": {
        "pending": (False, frozenset()),
        "available": (True, frozenset({"tier_b_result"})),
    },
    "codedb_appendix": {
        "pending": (False, frozenset()),
        "available": (True, frozenset({"codedb_result"})),
    },
}
EXPECTED_CORPORA: Final = {
    "py_nosphinx": ("Python", "SWE-bench Lite", "py_nosphinx_frozen_gold"),
    "ts40": ("TypeScript", "DataCurve DeepSWE", "ts40_frozen_gold"),
    "go34": ("Go", "DataCurve DeepSWE", "go34_frozen_gold"),
    "rust43": (
        "Rust",
        "SWE-bench Multilingual test split",
        "rust43_frozen_gold",
    ),
}
EXPECTED_DENOMINATORS: Final = {
    "py_nosphinx_frozen_gold": ("py_nosphinx", "frozen_gold", 39, True),
    "ts40_frozen_gold": ("ts40", "frozen_gold", 37, True),
    "go34_frozen_gold": ("go34", "frozen_gold", 30, True),
    "rust43_frozen_gold": ("rust43", "frozen_gold", 40, True),
    "rust43_graphify_failure_subset": (
        "rust43",
        "frozen_gold_minus_explicit_failures",
        34,
        False,
    ),
}
RUST_GRAPHIFY_EXCLUSIONS: Final = {
    "astral-sh__ruff-15309",
    "astral-sh__ruff-15330",
    "astral-sh__ruff-15356",
    "astral-sh__ruff-15394",
    "astral-sh__ruff-15443",
    "astral-sh__ruff-15543",
}
RUST_GRAPHIFY_FAILURE_IDS: Final = RUST_GRAPHIFY_EXCLUSIONS | {
    "astral-sh__ruff-15626"
}
RUST_GRAPHIFY_RAW_ERROR: Final = (
    "graphify build failed on /home/crabbox/ttg/gfy-checkouts/astral-sh__ruff"
)
EXPECTED_PRODUCERS: Final = {
    "noodl-eval-native-floor": (
        "git:3723be44085ab470bad55241853276f85568291e",
        "d02270de07b1f0d786ef49c80e71848fe57df4109a06eb5a3804cb8b68f66151",
        "identity-only",
        "native",
        "native_floor",
    ),
    "noodl-eval-nbx-shipped": (
        "git:3723be44085ab470bad55241853276f85568291e",
        "d02270de07b1f0d786ef49c80e71848fe57df4109a06eb5a3804cb8b68f66151",
        "identity-only",
        "nbx",
        "nbx_shipped",
    ),
    "graphifyy-0.9.28": (
        "graphifyy==0.9.28",
        "-",
        "declared-only",
        "graphify",
        "-",
    ),
}
SCORER_PATHS: Final = {
    "ttg/comparable_path.py",
    "ttg/curve_recompute.py",
    "ttg/matcher.py",
    "ttg/report_io.py",
    "ttg/rollup.py",
}

if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))


class PublicationError(ValueError):
    """A package invariant failed with a stable machine-readable code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def fail(code: str, message: str) -> None:
    """Raise a validation error with a stable code."""
    raise PublicationError(code, message)


def sha256(path: Path) -> str:
    """Return the SHA-256 digest of a regular file."""
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require_mapping(value: object, context: str) -> dict[str, Any]:
    """Return a JSON mapping or fail with context."""
    if not isinstance(value, dict):
        fail("E_AUTHORITY_SCHEMA", f"{context} must be an object")
    return value


def require_list(value: object, context: str) -> list[Any]:
    """Return a JSON list or fail with context."""
    if not isinstance(value, list):
        fail("E_AUTHORITY_SCHEMA", f"{context} must be an array")
    return value


def require_exact_keys(
    value: dict[str, Any], expected: set[str], context: str
) -> None:
    """Reject missing and unknown JSON fields."""
    actual = set(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unknown = sorted(actual - expected)
        fail(
            "E_AUTHORITY_SCHEMA",
            f"{context} keys differ; missing={missing}, unknown={unknown}",
        )


def load_json(path: Path) -> dict[str, Any]:
    """Load a UTF-8 JSON object with a useful package error."""
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail("E_AUTHORITY_PARSE", f"cannot read {path}: {exc}")
    return require_mapping(value, str(path))


def canonical_relative_path(value: str, context: str) -> str:
    """Validate a normalized, non-traversing POSIX relative path."""
    if not value or value == "-" or "\\" in value:
        fail("E_PROVENANCE_PATH", f"{context} is not a canonical relative path")
    path = PurePosixPath(value)
    if path.is_absolute() or ".." in path.parts or str(path) != value:
        fail("E_PROVENANCE_PATH", f"{context} is not a canonical relative path")
    return value


def path_beneath(root: Path, relative: str, context: str) -> Path:
    """Resolve a validated path and reject symlink escape from its root."""
    canonical_relative_path(relative, context)
    resolved_root = root.resolve()
    resolved_path = (resolved_root / relative).resolve()
    if not resolved_path.is_relative_to(resolved_root):
        fail("E_PROVENANCE_PATH", f"{context} escapes its evidence root")
    return resolved_path


def load_provenance(path: Path) -> list[dict[str, str]]:
    """Load the typed provenance ledger and validate its closed vocabulary."""
    try:
        with path.open(encoding="utf-8", newline="") as stream:
            reader = csv.DictReader(stream, delimiter="\t")
            if reader.fieldnames != PROVENANCE_FIELDS:
                fail(
                    "E_PROVENANCE_SCHEMA",
                    f"unexpected provenance header: {reader.fieldnames}",
                )
            rows = list(reader)
    except OSError as exc:
        fail("E_PROVENANCE_SCHEMA", f"cannot read {path}: {exc}")

    seen_ids: set[tuple[str, str]] = set()
    seen_release_paths: set[str] = set()
    for row_number, row in enumerate(rows, start=2):
        if set(row) != set(PROVENANCE_FIELDS) or any(
            row[field] == "" for field in PROVENANCE_FIELDS
        ):
            fail("E_PROVENANCE_SCHEMA", f"incomplete provenance row {row_number}")
        kind = row["kind"]
        state = row["state"]
        if kind not in KIND_STATES or state not in KIND_STATES[kind]:
            fail(
                "E_PROVENANCE_STATE",
                f"invalid kind/state {kind}/{state} on row {row_number}",
            )
        identity = (kind, row["id"])
        if identity in seen_ids:
            fail("E_PROVENANCE_SCHEMA", f"duplicate provenance identity {identity}")
        seen_ids.add(identity)

        if state in FILE_STATES:
            if not DIGEST_RE.fullmatch(row["sha256"]):
                fail("E_PROVENANCE_DIGEST", f"{identity} lacks a SHA-256 digest")
            canonical_relative_path(
                row["local_audit_path"], f"{identity} local_audit_path"
            )
            release_path = canonical_relative_path(
                row["release_path"], f"{identity} release_path"
            )
            if release_path in seen_release_paths:
                fail(
                    "E_PROVENANCE_PATH",
                    f"duplicate release path {release_path}",
                )
            seen_release_paths.add(release_path)
            if state == "verified" and row["public_locator"] != "-":
                fail(
                    "E_PUBLICATION_STATE",
                    "public locators must remain absent while the package is unpublished",
                )
            if state == "public-verified" and row["public_locator"] == "-":
                fail(
                    "E_PROVENANCE_STATE",
                    f"public-verified {identity} lacks a public locator",
                )
        elif state == "identity-only":
            if not DIGEST_RE.fullmatch(row["sha256"]):
                fail("E_PROVENANCE_DIGEST", f"{identity} lacks an identity digest")
            if any(
                row[field] != "-"
                for field in ("local_audit_path", "release_path", "public_locator")
            ):
                fail(
                    "E_PROVENANCE_STATE",
                    f"identity-only {identity} cannot claim an auditable file",
                )
        elif any(
            row[field] != "-"
            for field in (
                "sha256",
                "local_audit_path",
                "release_path",
                "public_locator",
            )
        ):
            fail(
                "E_PROVENANCE_STATE",
                f"declared-only {identity} must use explicit absent markers",
            )
    return rows


def provenance_index(rows: list[dict[str, str]]) -> dict[tuple[str, str], dict[str, str]]:
    """Index validated provenance rows by kind and ID."""
    return {(row["kind"], row["id"]): row for row in rows}


def require_artifact(
    index: dict[tuple[str, str], dict[str, str]], kind: str, artifact_id: str
) -> dict[str, str]:
    """Resolve an artifact that must exist in a verified state."""
    row = index.get((kind, artifact_id))
    if row is None:
        fail("E_RESULT_EVIDENCE", f"missing {kind}/{artifact_id}")
    if row["state"] not in FILE_STATES:
        fail("E_RESULT_EVIDENCE", f"{kind}/{artifact_id} is not verified")
    return row


def validate_evidence_ref(
    value: object,
    context: str,
    provenance: dict[tuple[str, str], dict[str, str]],
    *,
    expected_kind: str | None = None,
) -> dict[str, str]:
    """Resolve one typed authority reference to a provenance row."""
    reference = require_mapping(value, context)
    require_exact_keys(reference, {"kind", "id"}, context)
    kind = reference["kind"]
    artifact_id = reference["id"]
    if not isinstance(kind, str) or not isinstance(artifact_id, str):
        fail("E_EVIDENCE_ROLE", f"{context} must contain string kind/id")
    if expected_kind is not None and kind != expected_kind:
        fail("E_EVIDENCE_ROLE", f"{context} must reference kind {expected_kind}")
    row = provenance.get((kind, artifact_id))
    if row is None:
        fail("E_EVIDENCE_ROLE", f"{context} references absent {kind}/{artifact_id}")
    return row


def validate_gates(
    authority: dict[str, Any],
    provenance: dict[tuple[str, str], dict[str, str]],
) -> None:
    """Validate the closed evidence-conditioned publication lifecycle."""
    gates = require_mapping(authority["gates"], "gates")
    if set(gates) != set(GATE_LIFECYCLES):
        fail("E_GATE_STATUS", "gate membership differs from the frozen contract")
    for gate_id, legal_states in GATE_LIFECYCLES.items():
        gate = require_mapping(gates[gate_id], f"gates.{gate_id}")
        require_exact_keys(
            gate,
            {"status", "results_available", "evidence_refs", "reason"},
            f"gates.{gate_id}",
        )
        status = gate["status"]
        if status not in legal_states:
            fail("E_GATE_STATUS", f"illegal {gate_id} state: {status}")
        expected_available, required_kinds = legal_states[status]
        if gate["results_available"] is not expected_available:
            fail(
                "E_GATE_STATUS",
                f"{gate_id}/{status} has inconsistent results availability",
            )
        refs = require_list(gate["evidence_refs"], f"gates.{gate_id}.evidence_refs")
        referenced_kinds: set[str] = set()
        for position, ref in enumerate(refs):
            row = validate_evidence_ref(
                ref,
                f"gates.{gate_id}.evidence_refs[{position}]",
                provenance,
            )
            if row["kind"] in referenced_kinds:
                fail("E_GATE_PREREQUISITE", f"{gate_id} repeats an evidence kind")
            referenced_kinds.add(row["kind"])
            if row["state"] not in FILE_STATES:
                fail(
                    "E_GATE_PREREQUISITE",
                    f"{gate_id} evidence {row['kind']}/{row['id']} is not verified",
                )
        if referenced_kinds != set(required_kinds):
            fail(
                "E_GATE_PREREQUISITE",
                f"{gate_id}/{status} requires evidence kinds {sorted(required_kinds)}",
            )
        if not isinstance(gate["reason"], str) or not gate["reason"].strip():
            fail("E_GATE_STATUS", f"{gate_id} needs a nonempty reason")

    if (
        gates["public_reproduction"]["status"] == "available"
        and gates["public_evidence_retrieval"]["status"] != "available"
    ):
        fail(
            "E_GATE_PREREQUISITE",
            "public reproduction requires public evidence retrieval",
        )


def validate_fraction(value: object, context: str) -> str:
    """Validate a canonical nine-decimal fraction in the closed [0, 1] range."""
    if not isinstance(value, str) or not FRACTION_RE.fullmatch(value):
        fail("E_METRIC_RANGE", f"{context} is not a canonical [0,1] fraction")
    try:
        parsed = Decimal(value)
    except InvalidOperation as exc:
        fail("E_METRIC_RANGE", f"{context} is not decimal: {exc}")
    if not Decimal(0) <= parsed <= Decimal(1):
        fail("E_METRIC_RANGE", f"{context} is outside [0,1]")
    return value


def validate_authority(
    authority: dict[str, Any],
    provenance: list[dict[str, str]],
    repo_root: Path,
) -> dict[str, dict[str, Any]]:
    """Validate the sole structured result and status authority."""
    require_exact_keys(authority, AUTHORITY_KEYS, "authority")
    if authority["schema_version"] != SCHEMA_VERSION:
        fail("E_AUTHORITY_SCHEMA", "unknown authority schema_version")

    package = require_mapping(authority["package"], "package")
    require_exact_keys(
        package, {"id", "measured_on", "status", "public_revision"}, "package"
    )
    if package["id"] != "tokens-to-gold-v2-tier-a-a1-graphify" or package[
        "measured_on"
    ] != "2026-09-09":
        fail("E_PUBLICATION_STATE", "package identity changed")
    if package["status"] == "draft_unpublished":
        if package["public_revision"] is not None:
            fail("E_PUBLICATION_STATE", "draft package cannot name a public revision")
    elif package["status"] == "published":
        revision = package["public_revision"]
        if not isinstance(revision, str) or re.fullmatch(r"[0-9a-f]{40}", revision) is None:
            fail("E_PUBLICATION_STATE", "published package needs an immutable revision")
    else:
        fail("E_PUBLICATION_STATE", f"illegal package status: {package['status']}")

    provenance_by_id = provenance_index(provenance)
    evidence_roles = require_mapping(authority["evidence_roles"], "evidence_roles")
    require_exact_keys(
        evidence_roles, {"preregistration_ref", "doctrine_refs"}, "evidence_roles"
    )
    preregistration = validate_evidence_ref(
        evidence_roles["preregistration_ref"],
        "evidence_roles.preregistration_ref",
        provenance_by_id,
        expected_kind="preregistration",
    )
    if preregistration["id"] != "v2" or preregistration["state"] != "verified":
        fail("E_EVIDENCE_ROLE", "the frozen preregistration role changed")
    doctrine_refs = require_list(
        evidence_roles["doctrine_refs"], "evidence_roles.doctrine_refs"
    )
    doctrine_ids: set[str] = set()
    for position, ref in enumerate(doctrine_refs):
        doctrine = validate_evidence_ref(
            ref,
            f"evidence_roles.doctrine_refs[{position}]",
            provenance_by_id,
            expected_kind="doctrine",
        )
        if doctrine["state"] != "verified" or doctrine["id"] in doctrine_ids:
            fail("E_EVIDENCE_ROLE", "doctrine roles must be unique and verified")
        doctrine_ids.add(doctrine["id"])
    if doctrine_ids != {"benchmark-map", "claims-language"}:
        fail("E_EVIDENCE_ROLE", "required doctrine roles changed")
    role_cardinalities = {
        "preregistration": {"v2"},
        "doctrine": {"benchmark-map", "claims-language"},
        "tokenizer": {"o200k_base"},
        "run_header": {"py-run", "tgr-run"},
        "producer": set(EXPECTED_PRODUCERS),
    }
    for kind, expected_ids in role_cardinalities.items():
        actual_ids = {row["id"] for row in provenance if row["kind"] == kind}
        if actual_ids != expected_ids:
            fail(
                "E_EVIDENCE_ROLE",
                f"{kind} role membership changed; expected {sorted(expected_ids)}",
            )
    validate_gates(authority, provenance_by_id)
    publication_status = authority["gates"]["publication"]["status"]
    expected_package_status = (
        "published" if publication_status == "published" else "draft_unpublished"
    )
    if package["status"] != expected_package_status:
        fail("E_PUBLICATION_STATE", "package status disagrees with publication gate")
    if publication_status == "published":
        publication_ref = authority["gates"]["publication"]["evidence_refs"][0]
        publication_anchor = validate_evidence_ref(
            publication_ref,
            "gates.publication.evidence_refs[0]",
            provenance_by_id,
            expected_kind="publication_anchor",
        )
        if publication_anchor["version"] != f"git:{package['public_revision']}":
            fail(
                "E_GATE_PREREQUISITE",
                "publication anchor version must bind the immutable public revision",
            )

    measurement = require_mapping(authority["measurement"], "measurement")
    require_exact_keys(
        measurement,
        {
            "study_id",
            "wire_tokenizer_ref",
            "coverage_observation_budgets_wire_tokens",
            "backend_query_budget_unit",
            "ttg_at_80_scope",
            "gold_derivation_version",
        },
        "measurement",
    )
    tokenizer = validate_evidence_ref(
        measurement["wire_tokenizer_ref"],
        "measurement.wire_tokenizer_ref",
        provenance_by_id,
        expected_kind="tokenizer",
    )
    if (
        tokenizer["id"] != "o200k_base"
        or tokenizer["version"] != "o200k_base"
        or tokenizer["state"] != "declared-only"
        or tokenizer["sha256"] != "-"
    ):
        fail("E_EVIDENCE_ROLE", "wire tokenizer identity changed")
    measurement_without_ref = {
        key: value for key, value in measurement.items() if key != "wire_tokenizer_ref"
    }
    if measurement_without_ref != {
        "study_id": "tier_a_a1",
        "coverage_observation_budgets_wire_tokens": [2000, 8000, 32000],
        "backend_query_budget_unit": "graphify_approx_tokens_3_chars_per_token",
        "ttg_at_80_scope": "complete_delivered_response_may_exceed_32000_wire_tokens",
        "gold_derivation_version": 4,
    }:
        fail("E_MEASUREMENT_CONTRACT", "measurement units or scope changed")

    systems = require_list(authority["systems"], "systems")
    system_index: dict[str, dict[str, Any]] = {}
    for system in systems:
        item = require_mapping(system, "systems[]")
        system_id = item.get("id")
        if not isinstance(system_id, str) or system_id in system_index:
            fail("E_AUTHORITY_SCHEMA", "system IDs must be unique strings")
        system_index[system_id] = item
    if set(system_index) != {"native", "nbx", "graphify"}:
        fail("E_AUTHORITY_SCHEMA", "exactly three systems are required")
    for system_id in ("native", "nbx"):
        require_exact_keys(system_index[system_id], {"id", "label"}, f"systems.{system_id}")
    if system_index["native"]["label"] != "native floor" or system_index["nbx"][
        "label"
    ] != "nbx shipped":
        fail("E_AUTHORITY_SCHEMA", "system labels changed")
    graphify = system_index["graphify"]
    require_exact_keys(
        graphify,
        {"id", "label", "version", "sensitivity_only_version"},
        "systems.graphify",
    )
    if graphify["version"] != "0.9.28" or graphify["sensitivity_only_version"] != "0.9.56":
        fail("E_GRAPHIFY_VERSION", "Graphify version roles changed")
    if graphify["label"] != "Graphify":
        fail("E_AUTHORITY_SCHEMA", "Graphify label changed")

    arms = require_list(authority["arms"], "arms")
    arm_index: dict[str, dict[str, Any]] = {}
    expected_arm_budgets = {
        "native_floor": None,
        "nbx_shipped": None,
        "graphify_32k": 32000,
        "graphify_default": 2000,
    }
    expected_arm_metadata = {
        "native_floor": (
            "native",
            "native floor",
            "explorer",
            "noodl-eval-native-floor",
            "span",
        ),
        "nbx_shipped": (
            "nbx",
            "nbx shipped",
            "shipped_default",
            "noodl-eval-nbx-shipped",
            "symbol",
        ),
        "graphify_32k": (
            "graphify",
            "Graphify · 32K backend query",
            "code_only",
            "graphifyy-0.9.28",
            "span",
        ),
        "graphify_default": (
            "graphify",
            "Graphify · default 2K backend query",
            "code_only",
            "graphifyy-0.9.28",
            "span",
        ),
    }
    for arm in arms:
        item = require_mapping(arm, "arms[]")
        require_exact_keys(
            item,
            {
                "id",
                "system_id",
                "label",
                "config",
                "producer_ref",
                "retrieval_identity_kind",
                "backend_query_budget_approx_tokens",
            },
            "arms[]",
        )
        arm_id = item["id"]
        if arm_id in arm_index:
            fail("E_AUTHORITY_SCHEMA", f"duplicate arm {arm_id}")
        arm_index[arm_id] = item
        if item["system_id"] not in system_index:
            fail("E_RESULT_RELATION", f"arm {arm_id} has unknown system")
        producer = validate_evidence_ref(
            item["producer_ref"],
            f"arms.{arm_id}.producer_ref",
            provenance_by_id,
            expected_kind="producer",
        )
        actual_metadata = (
            item["system_id"],
            item["label"],
            item["config"],
            producer["id"],
            item["retrieval_identity_kind"],
        )
        if expected_arm_metadata.get(arm_id) != actual_metadata:
            fail("E_RESULT_RELATION", f"arm metadata changed for {arm_id}")
        expected_producer = EXPECTED_PRODUCERS.get(producer["id"])
        actual_producer = (
            producer["version"],
            producer["sha256"],
            producer["state"],
            producer["system_id"],
            producer["arm_id"],
        )
        if (
            expected_producer != actual_producer
            or producer["system_id"] != item["system_id"]
            or (
                producer["arm_id"] not in {"-", arm_id}
            )
        ):
            fail("E_RESULT_RELATION", f"arm {arm_id} has the wrong producer")
    if set(arm_index) != set(expected_arm_budgets):
        fail("E_AUTHORITY_SCHEMA", "exactly four configurations are required")
    for arm_id, expected_budget in expected_arm_budgets.items():
        if arm_index[arm_id]["backend_query_budget_approx_tokens"] != expected_budget:
            fail("E_BACKEND_BUDGET", f"{arm_id} backend budget changed")

    corpora = require_list(authority["corpora"], "corpora")
    corpus_index: dict[str, dict[str, Any]] = {}
    for corpus in corpora:
        item = require_mapping(corpus, "corpora[]")
        require_exact_keys(
            item,
            {
                "id",
                "language",
                "source_identity",
                "run_header_ref",
                "denominator_id",
            },
            "corpora[]",
        )
        corpus_id = item["id"]
        if corpus_id in corpus_index:
            fail("E_AUTHORITY_SCHEMA", f"duplicate corpus {corpus_id}")
        corpus_index[corpus_id] = item
        expected = EXPECTED_CORPORA.get(corpus_id)
        actual = (item["language"], item["source_identity"], item["denominator_id"])
        if expected != actual:
            fail("E_CORPUS_IDENTITY", f"corpus identity changed for {corpus_id}")
        run_header = validate_evidence_ref(
            item["run_header_ref"],
            f"corpora.{corpus_id}.run_header_ref",
            provenance_by_id,
            expected_kind="run_header",
        )
        expected_header = "py-run" if corpus_id == "py_nosphinx" else "tgr-run"
        if run_header["id"] != expected_header or run_header["state"] != "verified":
            fail("E_EVIDENCE_ROLE", f"run-header role changed for {corpus_id}")
        if corpus_id == "py_nosphinx":
            if run_header["corpus_id"] != corpus_id:
                fail("E_RESULT_RELATION", "Python run header has wrong corpus scope")
        elif run_header["corpus_id"] != "-":
            fail("E_RESULT_RELATION", "shared TGR run header must have shared scope")
        corpus_row = require_artifact(provenance_by_id, "corpus", corpus_id)
        if corpus_row["corpus_id"] != corpus_id:
            fail("E_RESULT_RELATION", f"corpus artifact mismatch for {corpus_id}")
        gold_row = require_artifact(provenance_by_id, "frozen_gold", corpus_id)
        if gold_row["corpus_id"] != corpus_id:
            fail("E_RESULT_RELATION", f"gold artifact mismatch for {corpus_id}")
        corpus_manifest = require_artifact(
            provenance_by_id, "corpus_manifest", corpus_id
        )
        if corpus_manifest["corpus_id"] != corpus_id:
            fail("E_RESULT_RELATION", f"corpus manifest mismatch for {corpus_id}")
    if set(corpus_index) != set(EXPECTED_CORPORA):
        fail("E_AUTHORITY_SCHEMA", "corpus membership changed")

    denominators = require_list(authority["denominators"], "denominators")
    denominator_index: dict[str, dict[str, Any]] = {}
    for denominator in denominators:
        item = require_mapping(denominator, "denominators[]")
        require_exact_keys(
            item,
            {
                "id",
                "corpus_id",
                "selection",
                "n",
                "matched_to_nbx",
                "excluded_instance_ids",
            },
            "denominators[]",
        )
        denominator_id = item["id"]
        if denominator_id in denominator_index:
            fail("E_AUTHORITY_SCHEMA", f"duplicate denominator {denominator_id}")
        denominator_index[denominator_id] = item
        actual = (
            item["corpus_id"],
            item["selection"],
            item["n"],
            item["matched_to_nbx"],
        )
        if EXPECTED_DENOMINATORS.get(denominator_id) != actual:
            fail("E_DENOMINATOR", f"denominator changed for {denominator_id}")
        exclusions = require_list(
            item["excluded_instance_ids"],
            f"denominators.{denominator_id}.excluded_instance_ids",
        )
        if denominator_id == "rust43_graphify_failure_subset":
            if set(exclusions) != RUST_GRAPHIFY_EXCLUSIONS or len(exclusions) != 6:
                fail("E_DENOMINATOR", "Rust Graphify exclusions changed")
        elif exclusions:
            fail("E_DENOMINATOR", f"unexpected exclusions for {denominator_id}")
    if set(denominator_index) != set(EXPECTED_DENOMINATORS):
        fail("E_DENOMINATOR", "denominator membership changed")

    failure_sets = require_list(authority["failure_sets"], "failure_sets")
    if len(failure_sets) != 1:
        fail("E_FAILURE_SET", "exactly one Rust Graphify failure set is required")
    failure_set = require_mapping(failure_sets[0], "failure_sets[0]")
    require_exact_keys(
        failure_set,
        {"id", "corpus_id", "arm_ids", "report_ids", "failures"},
        "failure_sets[0]",
    )
    if (
        failure_set["id"] != "rust43_graphify_build_failures"
        or failure_set["corpus_id"] != "rust43"
        or failure_set["arm_ids"] != ["graphify_32k", "graphify_default"]
        or failure_set["report_ids"] != ["rust-graphify-32k", "rust-graphify-2k"]
    ):
        fail("E_FAILURE_SET", "Rust Graphify failure-set relationships changed")
    failures = require_list(failure_set["failures"], "failure_sets[0].failures")
    failure_index: dict[str, dict[str, Any]] = {}
    for failure in failures:
        item = require_mapping(failure, "failure_sets[0].failures[]")
        require_exact_keys(
            item,
            {"instance_id", "category", "raw_error", "gold_bearing"},
            "failure_sets[0].failures[]",
        )
        instance_id = item["instance_id"]
        if not isinstance(instance_id, str) or instance_id in failure_index:
            fail("E_FAILURE_SET", "failure instance IDs must be unique strings")
        if (
            item["category"] != "graphify_build_failed"
            or item["raw_error"] != RUST_GRAPHIFY_RAW_ERROR
            or item["gold_bearing"] is not (instance_id in RUST_GRAPHIFY_EXCLUSIONS)
        ):
            fail("E_FAILURE_SET", f"failure disclosure changed for {instance_id}")
        failure_index[instance_id] = item
    if set(failure_index) != RUST_GRAPHIFY_FAILURE_IDS:
        fail("E_FAILURE_SET", "Rust Graphify must disclose all seven failures")
    if {
        instance_id
        for instance_id, failure in failure_index.items()
        if failure["gold_bearing"]
    } != RUST_GRAPHIFY_EXCLUSIONS:
        fail("E_DENOMINATOR", "failure disclosure and denominator exclusions disagree")

    execution_witnesses = require_list(
        authority["execution_witnesses"], "execution_witnesses"
    )
    if len(execution_witnesses) != 1:
        fail("E_EXECUTION_WITNESS", "Rust native-floor witness disclosure is required")
    witness = require_mapping(execution_witnesses[0], "execution_witnesses[0]")
    require_exact_keys(
        witness,
        {
            "id",
            "corpus_id",
            "arm_id",
            "report_id",
            "report_manifest_id",
            "manifest_scope",
            "completion",
        },
        "execution_witnesses[0]",
    )
    if (
        witness["id"] != "rust-native-floor-completion"
        or witness["corpus_id"] != "rust43"
        or witness["arm_id"] != "native_floor"
        or witness["report_id"] != "rust-native-floor"
        or witness["report_manifest_id"] != "rust-native-floor-manifest"
        or witness["manifest_scope"] != "command_and_binary_identity_only"
    ):
        fail("E_EXECUTION_WITNESS", "Rust native-floor witness relationship changed")
    completion = require_mapping(witness["completion"], "execution_witnesses[0].completion")
    require_exact_keys(
        completion,
        {
            "state",
            "exit_status",
            "report_size_at_completion_bytes",
            "evidence_ref",
            "reason",
        },
        "execution_witnesses[0].completion",
    )
    if (
        completion["state"] != "absent"
        or completion["exit_status"] is not None
        or completion["report_size_at_completion_bytes"] is not None
        or completion["evidence_ref"] is not None
        or not isinstance(completion["reason"], str)
        or not completion["reason"].strip()
    ):
        fail(
            "E_EXECUTION_WITNESS",
            "Rust native-floor completion gap must remain explicit and unsynthesized",
        )

    results = require_list(authority["results"], "results")
    result_keys: set[tuple[str, str]] = set()
    for result in results:
        item = require_mapping(result, "results[]")
        require_exact_keys(
            item,
            {
                "corpus_id",
                "arm_id",
                "denominator_id",
                "source_table_id",
                "report_id",
                "report_manifest_id",
                "metrics",
            },
            "results[]",
        )
        corpus_id = item["corpus_id"]
        arm_id = item["arm_id"]
        result_key = (corpus_id, arm_id)
        if result_key in result_keys:
            fail("E_AUTHORITY_SCHEMA", f"duplicate result {result_key}")
        result_keys.add(result_key)
        if corpus_id not in corpus_index or arm_id not in arm_index:
            fail("E_RESULT_RELATION", f"unknown corpus/arm {result_key}")
        denominator = denominator_index.get(item["denominator_id"])
        if denominator is None or denominator["corpus_id"] != corpus_id:
            fail("E_RESULT_RELATION", f"wrong denominator for {result_key}")
        if arm_id.startswith("graphify_") and corpus_id == "rust43":
            if item["denominator_id"] != "rust43_graphify_failure_subset":
                fail("E_DENOMINATOR", "Rust Graphify must remain nonmatched N=34")
        elif item["denominator_id"] != corpus_index[corpus_id]["denominator_id"]:
            fail("E_DENOMINATOR", f"wrong frozen denominator for {result_key}")

        source_table = require_artifact(
            provenance_by_id, "source_table", item["source_table_id"]
        )
        if source_table["corpus_id"] != corpus_id:
            fail("E_RESULT_RELATION", f"wrong source table for {result_key}")
        report = require_artifact(provenance_by_id, "report", item["report_id"])
        arm = arm_index[arm_id]
        if (
            report["corpus_id"] != corpus_id
            or report["arm_id"] != arm_id
            or report["system_id"] != arm["system_id"]
        ):
            fail("E_RESULT_RELATION", f"wrong report relation for {result_key}")
        manifest_id = item["report_manifest_id"]
        if arm_id in {"native_floor", "nbx_shipped"}:
            if not isinstance(manifest_id, str):
                fail("E_RESULT_EVIDENCE", f"missing report manifest for {result_key}")
            manifest = require_artifact(
                provenance_by_id, "report_manifest", manifest_id
            )
            if (
                manifest["corpus_id"] != corpus_id
                or manifest["arm_id"] != arm_id
                or manifest["system_id"] != arm["system_id"]
            ):
                fail("E_RESULT_RELATION", f"wrong report manifest for {result_key}")
        elif manifest_id is not None:
            fail("E_RESULT_RELATION", f"unexpected Graphify manifest for {result_key}")

        metrics = require_mapping(item["metrics"], f"metrics {result_key}")
        require_exact_keys(
            metrics,
            {"gold_at_wire_budget", "ttg_at_80_whole_response"},
            f"metrics {result_key}",
        )
        gold = require_mapping(
            metrics["gold_at_wire_budget"], f"gold_at_wire_budget {result_key}"
        )
        require_exact_keys(gold, {"2000", "8000", "32000"}, f"gold {result_key}")
        for budget, fraction in gold.items():
            validate_fraction(fraction, f"{result_key} Gold@{budget}")
        ttg = require_mapping(
            metrics["ttg_at_80_whole_response"], f"ttg_at_80 {result_key}"
        )
        require_exact_keys(ttg, {"reach", "median_wire_tokens"}, f"ttg {result_key}")
        validate_fraction(ttg["reach"], f"{result_key} reach@80")
        if type(ttg["median_wire_tokens"]) is not int or ttg["median_wire_tokens"] <= 0:
            fail("E_METRIC_RANGE", f"{result_key} median must be a positive integer")
    expected_result_keys = {
        (corpus_id, arm_id)
        for corpus_id in EXPECTED_CORPORA
        for arm_id in expected_arm_budgets
    }
    if result_keys != expected_result_keys:
        fail("E_AUTHORITY_SCHEMA", "the authority must contain exactly 16 results")

    scoring = require_list(authority["scoring_implementation"], "scoring_implementation")
    if len(scoring) != len(SCORER_PATHS):
        fail("E_SCORER_IDENTITY", "primitive scorer closure membership changed")
    scoring_paths: set[str] = set()
    for entry in scoring:
        item = require_mapping(entry, "scoring_implementation[]")
        require_exact_keys(item, {"path", "sha256"}, "scoring_implementation[]")
        path = canonical_relative_path(item["path"], "scoring implementation path")
        if path in scoring_paths or not DIGEST_RE.fullmatch(item["sha256"]):
            fail("E_SCORER_IDENTITY", "invalid or duplicate scorer identity")
        scoring_paths.add(path)
        scorer_path = path_beneath(repo_root, path, "scoring implementation path")
        if not scorer_path.is_file() or sha256(scorer_path) != item["sha256"]:
            fail("E_SCORER_IDENTITY", f"scoring implementation drift: {path}")
    if scoring_paths != SCORER_PATHS:
        fail("E_SCORER_IDENTITY", "primitive scorer closure membership changed")

    bundle = require_mapping(authority["evidence_bundle"], "evidence_bundle")
    require_exact_keys(
        bundle,
        {"manifest", "status", "public_locator", "sha256"},
        "evidence_bundle",
    )
    retrieval_available = (
        authority["gates"]["public_evidence_retrieval"]["status"] == "available"
    )
    if retrieval_available:
        release_ref = authority["gates"]["public_evidence_retrieval"][
            "evidence_refs"
        ][0]
        release = validate_evidence_ref(
            release_ref,
            "gates.public_evidence_retrieval.evidence_refs[0]",
            provenance_by_id,
            expected_kind="evidence_release",
        )
        if (
            bundle["manifest"] != "provenance.tsv"
            or bundle["status"] != "published"
            or bundle["public_locator"] != release["public_locator"]
            or bundle["sha256"] != release["sha256"]
        ):
            fail("E_GATE_PREREQUISITE", "available evidence needs a published bundle")
    elif bundle != {
        "manifest": "provenance.tsv",
        "status": "local_preparation_available_public_assets_unavailable",
        "public_locator": None,
        "sha256": None,
    }:
        fail("E_PUBLICATION_STATE", "unpublished evidence-bundle state is inconsistent")

    reproduction_gate = authority["gates"]["public_reproduction"]
    if reproduction_gate["status"] == "available":
        reproduction_ref = reproduction_gate["evidence_refs"][0]
        retrieval_ref = authority["gates"]["public_evidence_retrieval"][
            "evidence_refs"
        ][0]
        if reproduction_ref != retrieval_ref:
            fail(
                "E_GATE_PREREQUISITE",
                "public reproduction and retrieval must bind the same evidence release",
            )

    return {
        "systems": system_index,
        "arms": arm_index,
        "corpora": corpus_index,
        "denominators": denominator_index,
    }


def render_status(authority: dict[str, Any]) -> str:
    """Render the structured publication gates as Markdown."""
    labels = {
        "publication": "Package publication",
        "public_evidence_retrieval": "Public evidence retrieval",
        "public_reproduction": "Public tuple reproduction",
        "paired_uncertainty": "Paired per-corpus uncertainty",
        "tier_b_whole_agent": "Tier B whole-agent patch success",
        "codedb_appendix": "CodeDB appendix",
    }
    lines = [
        "# V2 publication status",
        "",
        "> Generated from `authority.json`; edit the structured gate, not this file.",
        "",
        "| Gate | Status | Results available? | Evidence refs | Boundary |",
        "|---|---|---|---|---|",
    ]
    gates = authority["gates"]
    for gate_id in GATE_LIFECYCLES:
        gate = gates[gate_id]
        available = "yes" if gate["results_available"] else "no"
        references = ", ".join(
            f"`{ref['kind']}/{ref['id']}`" for ref in gate["evidence_refs"]
        ) or "none"
        lines.append(
            f"| {labels[gate_id]} | `{gate['status']}` | {available} | "
            f"{references} | {gate['reason']} |"
        )
    lines.extend(
        [
            "",
            "A local audit-root or locally prepared evidence bundle is private review",
            "evidence. It is not public retrieval or public reproduction.",
            "",
            "## Execution-witness gap",
            "",
            authority["execution_witnesses"][0]["completion"]["reason"],
            "The Rust native-floor manifest is scoped to command and binary identity;",
            "no exit status or report-size-at-completion value is inferred from the report.",
            "",
        ]
    )
    return "\n".join(lines)


def render_bundle(authority: dict[str, Any]) -> str:
    """Render the status-bearing artifact contract from structured authority."""
    gates = authority["gates"]
    lines = [
        "# V2 Tier A A1 candidate artifact contract",
        "",
        "> Generated from `authority.json`; edit structured evidence or gate state, not this file.",
        "",
        "This contract applies only to the model-free A1 Graphify retrieval slice.",
        "Legal lifecycle transitions are schema-defined and evidence-conditioned; validation",
        "does not constitute external review, release approval, or proof that a public locator",
        "is retrievable.",
        "",
        "| # | Artifact | Current structured state | Candidate evidence or boundary |",
        "|---:|---|---|---|",
        "| 1 | Authority | `draft_unpublished` | Sole tuple, unit, denominator, arm, corpus, evidence-reference, failure, and gate authority |",
        "| 2 | Preregistration | `verified` locally | Typed digest and canonical release path; no public locator |",
        "| 3 | Gold lineage | `verified` locally | Frozen ggv 4 corpus and gold assets; no public locator |",
        "| 4 | Conditions | filled | Typed query, systems, configurations, producers, tokenizer, backend budget unit, and wire checkpoints |",
        "| 5 | State policy | `verified` locally | Fresh per-instance reindex and repository/base-commit identities retained in corpus manifests |",
        "| 6 | Task definition | `verified` locally | Hashed corpus and frozen-gold assets define inputs and scored symbols |",
        "| 7 | Raw trajectory | explained absent | Tier A has no agent messages; ordered retrieval identities and aligned wire positions are retained, with jointly absent vectors encoding an empty ranked list |",
        "| 8 | Output | `verified` locally | Hashed reports retain ranked retrieval output; no final answers or patches exist |",
        "| 9 | Usage ledger | explained absent | `ttg_wire` is retrieval-response accounting, not provider-billed usage |",
        "| 10 | Index ledger | explained absent | Build time, memory, disk, and amortization are outside this endpoint |",
        f"| 11 | Scoring | `{gates['paired_uncertainty']['status']}` | Point estimates are primitive-reconstructed; preregistered paired uncertainty has not advanced |",
        "| 12 | Failure publication | filled | Seven Rust Graphify failures are structured; six gold-bearing failures define the nonmatched N=34 subset |",
        f"| 13 | Public reproduction | `{gates['public_reproduction']['status']}` | Clone checks and private replay do not establish public reproduction |",
        "| 14 | Rust native-floor completion | `absent` | Manifest proves command/binary identity only; completion, exit, and report-size-at-completion witnesses are absent |",
        f"| 15 | Publication | `{gates['publication']['status']}` | External accepted-byte/release approval remains required |",
        "",
        "Wire observation checkpoints are not backend query budgets, a retrieval response",
        "is not a task or session, retrieval coverage is not patch success, payload size",
        "is not billed cost, and this is not an isolated causal attribution study.",
        "",
    ]
    return "\n".join(lines)


def render_results(
    authority: dict[str, Any], context: dict[str, dict[str, Any]]
) -> str:
    """Render the human result table from the sole tuple authority."""
    arms = context["arms"]
    corpora = context["corpora"]
    denominators = context["denominators"]
    by_key = {
        (result["corpus_id"], result["arm_id"]): result
        for result in authority["results"]
    }
    lines = [
        "# V2 Tier A — A1 Graphify point estimates",
        "",
        "> Generated from `authority.json`. Corpora remain separate; no pooled result is reported.",
        "",
        "The paired per-corpus uncertainty gate remains `required_pending`; these are",
        "descriptive point estimates, not a completed uncertainty analysis.",
    ]
    for corpus_id in EXPECTED_CORPORA:
        corpus = corpora[corpus_id]
        lines.extend(
            [
                "",
                f"## {corpus['language']} (`{corpus_id}`)",
                "",
                "| Arm | Backend query budget | N | Basis | Matched to nbx N? | Gold@2K_wire | Gold@8K_wire | Gold@32K_wire | Reach@80 whole response | Median-to-80 whole response (wire tokens) |",
                "|---|---:|---:|---|---|---:|---:|---:|---:|---:|",
            ]
        )
        for arm_id in ("native_floor", "nbx_shipped", "graphify_32k", "graphify_default"):
            result = by_key[(corpus_id, arm_id)]
            arm = arms[arm_id]
            denominator = denominators[result["denominator_id"]]
            budget = arm["backend_query_budget_approx_tokens"]
            budget_text = "n/a" if budget is None else f"{budget} approx tokens"
            matched = "yes" if denominator["matched_to_nbx"] else "**no — failure subset**"
            gold = result["metrics"]["gold_at_wire_budget"]
            ttg = result["metrics"]["ttg_at_80_whole_response"]
            lines.append(
                f"| {arm['label']} | {budget_text} | {denominator['n']} | "
                f"`{denominator['selection']}` | {matched} | {gold['2000']} | "
                f"{gold['8000']} | {gold['32000']} | {ttg['reach']} | "
                f"{ttg['median_wire_tokens']} |"
            )
    lines.extend(
        [
            "",
            "Coverage is observed only at the three fixed wire checkpoints. Reach@80 and",
            "median-to-80 scan the complete delivered response and may exceed 32K wire tokens.",
            "The Rust Graphify rows are an explicitly nonmatched N=34 failure subset; the",
            "matched Rust comparison is nbx versus native floor on frozen N=40.",
            "",
        ]
    )
    return "\n".join(lines)


def validate_generated_file(path: Path, expected: str, code: str) -> None:
    """Require a generated file to match its structured authority byte-for-byte."""
    try:
        actual = path.read_text(encoding="utf-8")
    except OSError as exc:
        fail(code, f"cannot read generated file {path}: {exc}")
    if actual != expected:
        fail(code, f"{path.name} does not match authority.json")


def validate_docs(
    repo_root: Path,
    package_root: Path,
    authority: dict[str, Any],
    context: dict[str, dict[str, Any]],
) -> None:
    """Validate generated views and the minimum top-level package pointers."""
    validate_generated_file(package_root / "STATUS.md", render_status(authority), "E_STATUS_RENDER")
    validate_generated_file(
        package_root / "RESULTS.md",
        render_results(authority, context),
        "E_RESULTS_RENDER",
    )
    validate_generated_file(
        package_root / "BUNDLE.md", render_bundle(authority), "E_BUNDLE_RENDER"
    )
    required = {
        repo_root / "README.md": ("v2/authority.json", "v2/STATUS.md"),
        repo_root / "BUNDLE.md": ("v2/authority.json", "v2/STATUS.md"),
        package_root / "README.md": (
            "fixed retrieval-output observation budget",
            "complete delivered response and may exceed 32K",
            "authority.json",
            "STATUS.md",
        ),
        package_root / "BUNDLE.md": ("authority.json", "structured state"),
    }
    for path, phrases in required.items():
        text = path.read_text(encoding="utf-8")
        for phrase in phrases:
            if phrase not in text:
                fail("E_DOCUMENTATION", f"{path} lacks required phrase: {phrase}")
    if (package_root / "results.tsv").exists():
        fail("E_DUPLICATE_AUTHORITY", "results.tsv duplicates the JSON tuple authority")
    for path in (
        package_root / "authority.json",
        package_root / "README.md",
        package_root / "BUNDLE.md",
        package_root / "RESULTS.md",
        package_root / "STATUS.md",
    ):
        if "query_budget_wire" in path.read_text(encoding="utf-8"):
            fail("E_BACKEND_BUDGET", f"obsolete query_budget_wire label in {path.name}")


def load_checksums(path: Path) -> dict[str, str]:
    """Load an exact, unique checksum membership set."""
    entries: dict[str, str] = {}
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        fail("E_PACKAGE_MEMBERSHIP", f"cannot read checksum manifest: {exc}")
    for line_number, line in enumerate(lines, start=1):
        match = PACKAGE_SUM_RE.fullmatch(line)
        if match is None:
            fail("E_PACKAGE_MEMBERSHIP", f"noncanonical checksum line {line_number}")
        digest, member = match.groups()
        canonical_relative_path(member, f"checksum member {member}")
        if member in entries:
            fail("E_PACKAGE_MEMBERSHIP", f"duplicate checksum member {member}")
        entries[member] = digest
    if set(entries) != PACKAGE_PAYLOAD_MEMBERS:
        missing = sorted(PACKAGE_PAYLOAD_MEMBERS - set(entries))
        unknown = sorted(set(entries) - PACKAGE_PAYLOAD_MEMBERS)
        fail(
            "E_PACKAGE_MEMBERSHIP",
            f"checksum membership differs; missing={missing}, unknown={unknown}",
        )
    return entries


def validate_package_boundary(package_root: Path) -> None:
    """Require the recursive v2 package to contain only declared regular files."""
    if not package_root.is_dir() or package_root.is_symlink():
        fail("E_PACKAGE_MEMBERSHIP", f"invalid package root: {package_root}")
    actual_files: set[str] = set()
    for path in package_root.rglob("*"):
        relative = path.relative_to(package_root).as_posix()
        if path.is_symlink():
            fail("E_PACKAGE_MEMBERSHIP", f"unapproved package symlink: {relative}")
        if path.is_dir():
            continue
        if not path.is_file():
            fail("E_PACKAGE_MEMBERSHIP", f"non-regular package entry: {relative}")
        actual_files.add(relative)
    if actual_files != PACKAGE_FILES:
        fail(
            "E_PACKAGE_MEMBERSHIP",
            "package file membership differs; "
            f"missing={sorted(PACKAGE_FILES - actual_files)}, "
            f"unknown={sorted(actual_files - PACKAGE_FILES)}",
        )


def validate_checksums(package_root: Path) -> None:
    """Verify every expected package member and no others."""
    validate_package_boundary(package_root)
    entries = load_checksums(package_root / "SHA256SUMS")
    for member, expected in entries.items():
        path = package_root / member
        if not path.is_file():
            fail("E_PACKAGE_DIGEST", f"missing package member {member}")
        actual = sha256(path)
        if actual != expected:
            fail(
                "E_PACKAGE_DIGEST",
                f"{member} digest is {actual}, expected {expected}",
            )


def load_and_validate(
    repo_root: Path = REPO_ROOT, package_root: Path = PACKAGE_ROOT
) -> tuple[dict[str, Any], list[dict[str, str]], dict[str, dict[str, Any]]]:
    """Validate the clone-contained publication package."""
    validate_package_boundary(package_root)
    authority = load_json(package_root / "authority.json")
    provenance = load_provenance(package_root / "provenance.tsv")
    context = validate_authority(authority, provenance, repo_root)
    validate_docs(repo_root, package_root, authority, context)
    validate_checksums(package_root)
    return authority, provenance, context


def evidence_path(root: Path, row: dict[str, str], field: str) -> Path:
    """Resolve one verified artifact under a local audit or release root."""
    path = path_beneath(root, row[field], f"{row['kind']}/{row['id']} {field}")
    if not path.is_file():
        fail("E_EVIDENCE_MISSING", f"missing {row[field]}")
    return path


def audit_evidence(root: Path, provenance: list[dict[str, str]], field: str) -> None:
    """Hash every verified evidence artifact under the selected root."""
    if not root.is_dir():
        fail("E_EVIDENCE_ROOT", f"not a directory: {root}")
    for row in provenance:
        if row["state"] not in FILE_STATES:
            continue
        path = evidence_path(root, row, field)
        actual = sha256(path)
        if actual != row["sha256"]:
            fail(
                "E_EVIDENCE_DIGEST",
                f"{row[field]} digest is {actual}, expected {row['sha256']}",
            )


def validate_evidence_manifest(
    root: Path,
    provenance: list[dict[str, str]],
    package_root: Path,
) -> None:
    """Validate exact checksum membership for a prepared evidence directory."""
    expected = {
        row["release_path"]: row["sha256"]
        for row in provenance
        if row["state"] in FILE_STATES
    }
    expected["publication/authority.json"] = sha256(package_root / "authority.json")
    expected["publication/provenance.tsv"] = sha256(package_root / "provenance.tsv")
    manifest_path = root / "EVIDENCE_SHA256SUMS"
    if not manifest_path.is_file():
        fail("E_BUNDLE_MANIFEST", "prepared bundle lacks EVIDENCE_SHA256SUMS")
    actual: dict[str, str] = {}
    for line_number, line in enumerate(
        manifest_path.read_text(encoding="utf-8").splitlines(), start=1
    ):
        fields = line.split("  ")
        if len(fields) != 2 or DIGEST_RE.fullmatch(fields[0]) is None:
            fail("E_BUNDLE_MANIFEST", f"noncanonical bundle checksum line {line_number}")
        digest, member = fields
        canonical_relative_path(member, f"bundle checksum member {member}")
        if member in actual:
            fail("E_BUNDLE_MANIFEST", f"duplicate bundle member {member}")
        actual[member] = digest
    if actual != expected:
        fail("E_BUNDLE_MANIFEST", "bundle checksum membership or digest changed")
    expected_files = set(expected) | {"EVIDENCE_SHA256SUMS"}
    actual_files: set[str] = set()
    for path in root.rglob("*"):
        member = path.relative_to(root).as_posix()
        if path.is_symlink():
            fail("E_BUNDLE_MANIFEST", f"bundle contains a symlink: {member}")
        if path.is_file():
            actual_files.add(member)
    if actual_files != expected_files:
        fail("E_BUNDLE_MANIFEST", "bundle file membership differs from its manifest")
    for member, digest in actual.items():
        path = path_beneath(root, member, f"bundle member {member}")
        if not path.is_file() or sha256(path) != digest:
            fail("E_BUNDLE_MANIFEST", f"bundle member digest mismatch: {member}")


def load_frozen_gold(path: Path) -> dict[str, list[str]]:
    """Load the frozen instance-to-symbol mapping without changing its order."""
    document = load_json(path)
    gold = document.get("gold", document)
    if not isinstance(gold, dict):
        fail("E_RECOMPUTE", f"{path} has no gold object")
    frozen: dict[str, list[str]] = {}
    for instance_id, symbols in gold.items():
        if not isinstance(instance_id, str) or instance_id in frozen:
            fail("E_RECOMPUTE", f"{path} has invalid frozen instance IDs")
        if (
            not isinstance(symbols, list)
            or not symbols
            or any(not isinstance(symbol, str) for symbol in symbols)
        ):
            fail("E_RECOMPUTE", f"{instance_id} has invalid frozen symbols")
        frozen[instance_id] = list(symbols)
    return frozen


def validate_failure_rows(
    report: Mapping[str, object],
    expected_failures: Mapping[str, Mapping[str, object]],
    report_id: str,
) -> None:
    """Require the retained report's complete raw failure set and reasons."""
    results = report.get("results")
    if not isinstance(results, list):
        fail("E_FAILURE_SET", f"{report_id} has no results[]")
    actual: dict[str, str] = {}
    for row in results:
        if not isinstance(row, Mapping) or "error" not in row:
            continue
        instance_id = row.get("instance_id")
        error = row.get("error")
        if (
            not isinstance(instance_id, str)
            or not isinstance(error, str)
            or instance_id in actual
        ):
            fail("E_FAILURE_SET", f"{report_id} has malformed failure rows")
        actual[instance_id] = error
    expected = {
        instance_id: str(failure["raw_error"])
        for instance_id, failure in expected_failures.items()
    }
    if actual != expected:
        fail("E_FAILURE_SET", f"{report_id} raw failure set or reason changed")


def recompute_results(
    root: Path,
    field: str,
    authority: dict[str, Any],
    provenance: list[dict[str, str]],
    context: dict[str, dict[str, Any]],
) -> None:
    """Rebuild curves from primitives, check stored parity, then aggregate."""
    from ttg.curve_recompute import CurveInputError, reconstruct_selected_curves
    from ttg.report_io import load_report
    from ttg.rollup import rollup

    index = provenance_index(provenance)
    denominators = context["denominators"]
    arms = context["arms"]
    failure_set = authority["failure_sets"][0]
    expected_failures = {
        failure["instance_id"]: failure for failure in failure_set["failures"]
    }
    for result in authority["results"]:
        corpus_id = result["corpus_id"]
        arm_id = result["arm_id"]
        gold_row = require_artifact(index, "frozen_gold", corpus_id)
        report_row = require_artifact(index, "report", result["report_id"])
        frozen_gold = load_frozen_gold(evidence_path(root, gold_row, field))
        frozen_ids = list(frozen_gold)
        denominator = denominators[result["denominator_id"]]
        excluded = set(denominator["excluded_instance_ids"])
        selected_ids = [instance_id for instance_id in frozen_ids if instance_id not in excluded]
        if len(selected_ids) != denominator["n"]:
            fail("E_RECOMPUTE", f"denominator size changed for {corpus_id}/{arm_id}")
        report = load_report(evidence_path(root, report_row, field))
        if result["report_id"] in failure_set["report_ids"]:
            validate_failure_rows(report, expected_failures, result["report_id"])
        try:
            curves = reconstruct_selected_curves(
                report,
                frozen_gold,
                selected_ids,
                arms[arm_id]["retrieval_identity_kind"],
            )
        except CurveInputError as exc:
            fail("E_CURVE_PARITY", f"{corpus_id}/{arm_id}: {exc}")
        reconstructed_report = {
            "results": [
                {
                    "instance_id": instance_id,
                    "token_coverage_wire": curves[instance_id].as_report_curve(),
                }
                for instance_id in selected_ids
            ]
        }
        binding = rollup(
            reconstructed_report, frozen_instance_ids=selected_ids
        ).binding
        metrics = result["metrics"]
        observed_gold = {
            str(budget): f"{binding.gold_at_budget[budget]:.9f}"
            for budget in (2000, 8000, 32000)
        }
        observed_reach = f"{binding.reach_at_coverage[80]:.9f}"
        observed_median = binding.median_ttg_at_coverage[80]
        if (
            binding.n != denominator["n"]
            or observed_gold != metrics["gold_at_wire_budget"]
            or observed_reach != metrics["ttg_at_80_whole_response"]["reach"]
            or observed_median
            != metrics["ttg_at_80_whole_response"]["median_wire_tokens"]
        ):
            fail("E_RECOMPUTE", f"tuple mismatch for {corpus_id}/{arm_id}")


def write_derived(
    package_root: Path,
    authority: dict[str, Any],
    context: dict[str, dict[str, Any]],
) -> None:
    """Regenerate every derived view and the one package checksum manifest."""
    (package_root / "RESULTS.md").write_text(
        render_results(authority, context), encoding="utf-8"
    )
    (package_root / "STATUS.md").write_text(render_status(authority), encoding="utf-8")
    (package_root / "BUNDLE.md").write_text(
        render_bundle(authority), encoding="utf-8"
    )
    missing = [
        member
        for member in PACKAGE_PAYLOAD_MEMBERS
        if not (package_root / member).is_file()
    ]
    if missing:
        fail("E_PACKAGE_MEMBERSHIP", f"cannot hash missing members: {sorted(missing)}")
    body = "".join(
        f"{sha256(package_root / member)}  {member}\n"
        for member in sorted(PACKAGE_PAYLOAD_MEMBERS)
    )
    (package_root / "SHA256SUMS").write_text(body, encoding="utf-8")
    validate_package_boundary(package_root)


def atomic_publish_directory(staging: Path, target: Path) -> None:
    """Atomically rename a directory without replacing any target."""
    libc = ctypes.CDLL(None, use_errno=True)
    source_bytes = os.fsencode(staging)
    target_bytes = os.fsencode(target)
    if sys.platform == "darwin":
        rename_exclusive = libc.renamex_np
        rename_exclusive.argtypes = [
            ctypes.c_char_p,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename_exclusive.restype = ctypes.c_int
        result = rename_exclusive(source_bytes, target_bytes, 0x00000004)
    elif sys.platform.startswith("linux"):
        try:
            rename_exclusive = libc.renameat2
        except AttributeError:
            fail("E_BUNDLE_PUBLISH", "renameat2 is unavailable; refusing unsafe publish")
        rename_exclusive.argtypes = [
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_int,
            ctypes.c_char_p,
            ctypes.c_uint,
        ]
        rename_exclusive.restype = ctypes.c_int
        result = rename_exclusive(-100, source_bytes, -100, target_bytes, 1)
    else:
        fail(
            "E_BUNDLE_PUBLISH",
            f"exclusive directory publication is unsupported on {sys.platform}",
        )
    if result == 0:
        return
    error_number = ctypes.get_errno()
    if error_number in {errno.EEXIST, errno.ENOTEMPTY}:
        fail("E_BUNDLE_TARGET", f"bundle target already exists: {target}")
    message = os.strerror(error_number)
    fail("E_BUNDLE_PUBLISH", f"exclusive bundle publish failed: {message}")


def atomic_prepare_directory(
    target: Path,
    populate: Callable[[Path], None],
    validate: Callable[[Path], None],
) -> None:
    """Build in an owned sibling and expose only a fully validated directory."""
    target = target.absolute()
    if target.exists() or target.is_symlink():
        fail("E_BUNDLE_TARGET", f"bundle target already exists: {target}")
    parent = target.parent
    if not parent.is_dir() or parent.is_symlink():
        fail("E_BUNDLE_TARGET", f"bundle parent is not a regular directory: {parent}")
    staging = Path(
        tempfile.mkdtemp(prefix=f".{target.name}.tmp-", dir=parent)
    )
    published = False
    try:
        populate(staging)
        validate(staging)
        atomic_publish_directory(staging, target)
        published = True
    finally:
        if not published and staging.exists():
            shutil.rmtree(staging)


def prepare_bundle(
    audit_root: Path,
    target: Path,
    authority: dict[str, Any],
    provenance: list[dict[str, str]],
    context: dict[str, dict[str, Any]],
    repo_root: Path,
    package_root: Path,
) -> None:
    """Prepare, fully verify, and atomically publish a local evidence bundle."""
    audit_evidence(audit_root, provenance, "local_audit_path")
    recompute_results(
        audit_root, "local_audit_path", authority, provenance, context
    )
    evidence_rows = [row for row in provenance if row["state"] in FILE_STATES]

    def populate(staging: Path) -> None:
        for row in evidence_rows:
            source = evidence_path(audit_root, row, "local_audit_path")
            destination = path_beneath(
                staging,
                row["release_path"],
                f"{row['kind']}/{row['id']} release_path",
            )
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, destination)
        publication = staging / "publication"
        publication.mkdir()
        shutil.copyfile(package_root / "authority.json", publication / "authority.json")
        shutil.copyfile(package_root / "provenance.tsv", publication / "provenance.tsv")
        manifest_entries = {
            row["release_path"]: row["sha256"] for row in evidence_rows
        }
        manifest_entries["publication/authority.json"] = sha256(
            package_root / "authority.json"
        )
        manifest_entries["publication/provenance.tsv"] = sha256(
            package_root / "provenance.tsv"
        )
        manifest = "".join(
            f"{digest}  {member}\n"
            for member, digest in sorted(manifest_entries.items())
        )
        (staging / "EVIDENCE_SHA256SUMS").write_text(manifest, encoding="utf-8")

    def validate(staging: Path) -> None:
        validate_evidence_manifest(staging, provenance, package_root)
        audit_evidence(staging, provenance, "release_path")
        recompute_results(staging, "release_path", authority, provenance, context)
        load_and_validate(repo_root, package_root)

    atomic_prepare_directory(target, populate, validate)


def write_json(path: Path, document: dict[str, Any]) -> None:
    """Write a canonical JSON test fixture."""
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")


def restamp_fixture(package_root: Path) -> None:
    """Restamp every declared payload after a deliberate self-test mutation."""
    body = "".join(
        f"{sha256(package_root / member)}  {member}\n"
        for member in sorted(PACKAGE_PAYLOAD_MEMBERS)
        if (package_root / member).is_file()
    )
    (package_root / "SHA256SUMS").write_text(body, encoding="utf-8")


def write_provenance(path: Path, rows: Sequence[Mapping[str, str]]) -> None:
    """Write typed provenance in its canonical field order."""
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=PROVENANCE_FIELDS,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def copy_clone_fixture(
    repo_root: Path, package_root: Path, destination: Path
) -> None:
    """Copy the exact clone-contained verifier and scorer closure."""
    shutil.copyfile(repo_root / "README.md", destination / "README.md")
    shutil.copyfile(repo_root / "BUNDLE.md", destination / "BUNDLE.md")
    shutil.copytree(package_root, destination / "v2")
    (destination / "ttg").mkdir()
    shutil.copyfile(repo_root / "ttg" / "__init__.py", destination / "ttg" / "__init__.py")
    for scorer in SCORER_PATHS:
        source = repo_root / scorer
        target = destination / scorer
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)


def expect_failure(
    root: Path,
    expected_code: str,
    mutation: Callable[[Path], None],
    *,
    restamp: bool = True,
) -> None:
    """Copy the package, apply one mutation, and require the intended refusal."""
    fixture = root / f"{len(tuple(root.iterdir())):02d}-{expected_code}"
    fixture.mkdir()
    copy_clone_fixture(REPO_ROOT, PACKAGE_ROOT, fixture)
    mutation(fixture)
    if restamp:
        restamp_fixture(fixture / "v2")
    try:
        load_and_validate(fixture, fixture / "v2")
    except PublicationError as exc:
        if exc.code != expected_code:
            fail(
                "E_SELF_TEST",
                f"expected {expected_code}, got {exc.code}: {exc}",
            )
        print(f"RED control caught: {expected_code} ({mutation.__name__})")
        return
    fail("E_SELF_TEST", f"{expected_code} mutation unexpectedly passed")


def self_test() -> None:
    """Exercise clone-only schema, closure, lifecycle, and atomicity controls."""
    with tempfile.TemporaryDirectory(prefix="ttg-v2-selftest-") as temporary:
        root = Path(temporary)

        def invalid_metric(fixture: Path) -> None:
            path = fixture / "v2" / "authority.json"
            document = load_json(path)
            document["results"][0]["metrics"]["gold_at_wire_budget"]["2000"] = (
                "1.999999999"
            )
            write_json(path, document)

        expect_failure(root, "E_METRIC_RANGE", invalid_metric)

        def evidence_free_tier_b(fixture: Path) -> None:
            path = fixture / "v2" / "authority.json"
            document = load_json(path)
            document["gates"]["tier_b_whole_agent"]["status"] = "available"
            document["gates"]["tier_b_whole_agent"]["results_available"] = True
            write_json(path, document)

        expect_failure(root, "E_GATE_PREREQUISITE", evidence_free_tier_b)

        def evidence_free_publication(fixture: Path) -> None:
            path = fixture / "v2" / "authority.json"
            document = load_json(path)
            document["package"]["status"] = "published"
            document["package"]["public_revision"] = "a" * 40
            document["gates"]["publication"]["status"] = "published"
            document["gates"]["publication"]["results_available"] = True
            write_json(path, document)

        expect_failure(root, "E_GATE_PREREQUISITE", evidence_free_publication)

        def evidence_free_retrieval(fixture: Path) -> None:
            path = fixture / "v2" / "authority.json"
            document = load_json(path)
            document["gates"]["public_evidence_retrieval"]["status"] = "available"
            document["gates"]["public_evidence_retrieval"][
                "results_available"
            ] = True
            write_json(path, document)

        expect_failure(root, "E_GATE_PREREQUISITE", evidence_free_retrieval)

        def missing_preregistration(fixture: Path) -> None:
            path = fixture / "v2" / "provenance.tsv"
            rows = [
                row
                for row in load_provenance(path)
                if row["kind"] != "preregistration"
            ]
            write_provenance(path, rows)

        expect_failure(root, "E_EVIDENCE_ROLE", missing_preregistration)

        def downgrade_native_producer(fixture: Path) -> None:
            path = fixture / "v2" / "provenance.tsv"
            rows = load_provenance(path)
            for row in rows:
                if row["kind"] == "producer" and row["id"] == "noodl-eval-native-floor":
                    row["state"] = "declared-only"
                    row["sha256"] = "-"
            write_provenance(path, rows)

        expect_failure(root, "E_RESULT_RELATION", downgrade_native_producer)

        def drift_producer_version(fixture: Path) -> None:
            path = fixture / "v2" / "provenance.tsv"
            rows = load_provenance(path)
            for row in rows:
                if row["kind"] == "producer" and row["id"] == "noodl-eval-nbx-shipped":
                    row["version"] = "git:0000000000000000000000000000000000000000"
            write_provenance(path, rows)

        expect_failure(root, "E_RESULT_RELATION", drift_producer_version)

        def mismatch_tokenizer(fixture: Path) -> None:
            path = fixture / "v2" / "authority.json"
            document = load_json(path)
            document["measurement"]["wire_tokenizer_ref"]["id"] = "missing-tokenizer"
            write_json(path, document)

        expect_failure(root, "E_EVIDENCE_ROLE", mismatch_tokenizer)

        def wrong_report(fixture: Path) -> None:
            path = fixture / "v2" / "authority.json"
            document = load_json(path)
            document["results"][0]["report_id"] = "ts-native-floor"
            write_json(path, document)

        expect_failure(root, "E_RESULT_RELATION", wrong_report)

        def downgrade_report(fixture: Path) -> None:
            path = fixture / "v2" / "provenance.tsv"
            rows = load_provenance(path)
            for row in rows:
                if row["kind"] == "report" and row["id"] == "py-native-floor":
                    row["state"] = "declared-only"
                    row["sha256"] = "-"
                    row["local_audit_path"] = "-"
                    row["release_path"] = "-"
            write_provenance(path, rows)

        expect_failure(root, "E_PROVENANCE_STATE", downgrade_report)

        def path_traversal(fixture: Path) -> None:
            path = fixture / "v2" / "provenance.tsv"
            text = path.read_text(encoding="utf-8")
            path.write_text(
                text.replace(
                    "reports/native_floor_py_nosphinx.json",
                    "../native_floor_py_nosphinx.json",
                    1,
                ),
                encoding="utf-8",
            )

        expect_failure(root, "E_PROVENANCE_PATH", path_traversal)

        def old_budget_field(fixture: Path) -> None:
            path = fixture / "v2" / "authority.json"
            document = load_json(path)
            document["arms"][2]["query_budget_wire"] = 32000
            write_json(path, document)

        expect_failure(root, "E_AUTHORITY_SCHEMA", old_budget_field)

        def status_view_drift(fixture: Path) -> None:
            path = fixture / "v2" / "STATUS.md"
            path.write_text(
                path.read_text(encoding="utf-8") + "\nTier B results are complete.\n",
                encoding="utf-8",
            )

        expect_failure(root, "E_STATUS_RENDER", status_view_drift)

        def bundle_view_drift(fixture: Path) -> None:
            path = fixture / "v2" / "BUNDLE.md"
            path.write_text(
                path.read_text(encoding="utf-8") + "\nAll gates are complete.\n",
                encoding="utf-8",
            )

        expect_failure(root, "E_BUNDLE_RENDER", bundle_view_drift)

        def extra_package_file(fixture: Path) -> None:
            (fixture / "v2" / "alternate-results.json").write_text(
                "{}\n", encoding="utf-8"
            )

        expect_failure(root, "E_PACKAGE_MEMBERSHIP", extra_package_file)

        def missing_package_file(fixture: Path) -> None:
            (fixture / "v2" / "README.md").unlink()

        expect_failure(root, "E_PACKAGE_MEMBERSHIP", missing_package_file)

        def package_symlink(fixture: Path) -> None:
            (fixture / "v2" / "alternate-results.json").symlink_to("authority.json")

        expect_failure(root, "E_PACKAGE_MEMBERSHIP", package_symlink)

        def boolean_true_median(fixture: Path) -> None:
            path = fixture / "v2" / "authority.json"
            document = load_json(path)
            document["results"][0]["metrics"]["ttg_at_80_whole_response"][
                "median_wire_tokens"
            ] = True
            write_json(path, document)

        expect_failure(root, "E_METRIC_RANGE", boolean_true_median)

        def boolean_false_median(fixture: Path) -> None:
            path = fixture / "v2" / "authority.json"
            document = load_json(path)
            document["results"][0]["metrics"]["ttg_at_80_whole_response"][
                "median_wire_tokens"
            ] = False
            write_json(path, document)

        expect_failure(root, "E_METRIC_RANGE", boolean_false_median)

        def corrupt_fixture_scorer(fixture: Path) -> None:
            path = fixture / "ttg" / "matcher.py"
            path.write_text(path.read_text(encoding="utf-8") + "\n# corrupt\n")

        expect_failure(root, "E_SCORER_IDENTITY", corrupt_fixture_scorer)

        def missing_checksum(fixture: Path) -> None:
            path = fixture / "v2" / "SHA256SUMS"
            lines = [
                line
                for line in path.read_text(encoding="utf-8").splitlines()
                if not line.endswith("  README.md")
            ]
            path.write_text("\n".join(lines) + "\n", encoding="utf-8")

        expect_failure(
            root, "E_PACKAGE_MEMBERSHIP", missing_checksum, restamp=False
        )

        def duplicate_checksum(fixture: Path) -> None:
            path = fixture / "v2" / "SHA256SUMS"
            first = path.read_text(encoding="utf-8").splitlines()[0]
            with path.open("a", encoding="utf-8") as stream:
                stream.write(first + "\n")

        expect_failure(
            root, "E_PACKAGE_MEMBERSHIP", duplicate_checksum, restamp=False
        )

        def unknown_checksum(fixture: Path) -> None:
            path = fixture / "v2" / "SHA256SUMS"
            with path.open("a", encoding="utf-8") as stream:
                stream.write(f"{'0' * 64}  unknown.md\n")

        expect_failure(
            root, "E_PACKAGE_MEMBERSHIP", unknown_checksum, restamp=False
        )

        publication_fixture = root / "future-publication-state"
        publication_fixture.mkdir()
        copy_clone_fixture(REPO_ROOT, PACKAGE_ROOT, publication_fixture)
        approval_path = publication_fixture / "review" / "release-approval.txt"
        approval_path.parent.mkdir()
        approval_path.write_text("fixture-only reviewed release anchor\n", encoding="utf-8")
        publication_provenance_path = publication_fixture / "v2" / "provenance.tsv"
        publication_rows = load_provenance(publication_provenance_path)
        revision = "a" * 40
        publication_rows.append(
            {
                "kind": "publication_anchor",
                "id": "fixture-release-approval",
                "version": f"git:{revision}",
                "sha256": sha256(approval_path),
                "local_audit_path": "review/release-approval.txt",
                "release_path": "publication-anchors/release-approval.txt",
                "public_locator": "https://example.invalid/fixture-release-approval",
                "state": "public-verified",
                "corpus_id": "-",
                "arm_id": "-",
                "system_id": "-",
                "note": "Fixture-only accepted-byte anchor",
            }
        )
        write_provenance(publication_provenance_path, publication_rows)
        publication_authority_path = publication_fixture / "v2" / "authority.json"
        publication_authority = load_json(publication_authority_path)
        publication_authority["package"]["status"] = "published"
        publication_authority["package"]["public_revision"] = revision
        publication_gate = publication_authority["gates"]["publication"]
        publication_gate["status"] = "published"
        publication_gate["results_available"] = True
        publication_gate["evidence_refs"] = [
            {"kind": "publication_anchor", "id": "fixture-release-approval"}
        ]
        publication_gate["reason"] = "Fixture-only evidence-backed transition."
        write_json(publication_authority_path, publication_authority)
        publication_context = validate_authority(
            publication_authority,
            publication_rows,
            publication_fixture,
        )
        write_derived(
            publication_fixture / "v2",
            publication_authority,
            publication_context,
        )
        load_and_validate(publication_fixture, publication_fixture / "v2")
        audit_evidence(
            publication_fixture,
            [publication_rows[-1]],
            "local_audit_path",
        )
        print("GREEN control passed: evidence-backed future publication state")

        release_path = publication_fixture / "review" / "evidence-release.txt"
        release_path.write_text("fixture-only immutable evidence release\n", encoding="utf-8")
        release_digest = sha256(release_path)
        release_locator = "https://example.invalid/fixture-evidence-release"
        publication_rows.append(
            {
                "kind": "evidence_release",
                "id": "fixture-evidence-release",
                "version": "fixture-v1",
                "sha256": release_digest,
                "local_audit_path": "review/evidence-release.txt",
                "release_path": "evidence-releases/evidence-release.txt",
                "public_locator": release_locator,
                "state": "public-verified",
                "corpus_id": "-",
                "arm_id": "-",
                "system_id": "-",
                "note": "Fixture-only immutable evidence release",
            }
        )
        write_provenance(publication_provenance_path, publication_rows)
        retrieval_gate = publication_authority["gates"]["public_evidence_retrieval"]
        retrieval_gate["status"] = "available"
        retrieval_gate["results_available"] = True
        retrieval_gate["evidence_refs"] = [
            {"kind": "evidence_release", "id": "fixture-evidence-release"}
        ]
        retrieval_gate["reason"] = "Fixture-only evidence-backed transition."
        reproduction_gate = publication_authority["gates"]["public_reproduction"]
        reproduction_gate["status"] = "available"
        reproduction_gate["results_available"] = True
        reproduction_gate["evidence_refs"] = list(retrieval_gate["evidence_refs"])
        reproduction_gate["reason"] = "Fixture-only evidence-backed transition."
        publication_authority["evidence_bundle"].update(
            {
                "status": "published",
                "public_locator": release_locator,
                "sha256": release_digest,
            }
        )
        write_json(publication_authority_path, publication_authority)
        publication_context = validate_authority(
            publication_authority,
            publication_rows,
            publication_fixture,
        )
        write_derived(
            publication_fixture / "v2",
            publication_authority,
            publication_context,
        )
        load_and_validate(publication_fixture, publication_fixture / "v2")
        audit_evidence(
            publication_fixture,
            [publication_rows[-1]],
            "local_audit_path",
        )
        print("GREEN control passed: bound future retrieval/reproduction state")

        atomic_root = root / "atomic"
        atomic_root.mkdir()

        def good_populate(staging: Path) -> None:
            (staging / "payload").write_text("complete\n", encoding="utf-8")

        def good_validate(staging: Path) -> None:
            if (staging / "payload").read_text(encoding="utf-8") != "complete\n":
                fail("E_SELF_TEST", "atomic fixture payload changed")

        def require_clean_failure(
            name: str,
            populate: Callable[[Path], None],
            validate: Callable[[Path], None],
            expected: type[BaseException],
        ) -> Path:
            target = atomic_root / name
            try:
                atomic_prepare_directory(target, populate, validate)
            except expected:
                pass
            else:
                fail("E_SELF_TEST", f"{name} atomic failure was not raised")
            leftovers = list(atomic_root.glob(f".{name}.tmp-*"))
            if target.exists() or leftovers:
                fail("E_SELF_TEST", f"{name} exposed a partial target or staging tree")
            atomic_prepare_directory(target, good_populate, good_validate)
            if not target.is_dir():
                fail("E_SELF_TEST", f"{name} retry did not publish")
            print(f"RED control caught: atomic {name}; retry passed")
            return target

        def copy_failure(staging: Path) -> None:
            (staging / "partial").write_text("partial\n", encoding="utf-8")
            raise OSError("injected copy failure")

        require_clean_failure(
            "copy-failure", copy_failure, good_validate, OSError
        )

        def manifest_failure(_staging: Path) -> None:
            fail("E_BUNDLE_MANIFEST", "injected manifest failure")

        require_clean_failure(
            "manifest-failure",
            good_populate,
            manifest_failure,
            PublicationError,
        )

        def validation_failure(_staging: Path) -> None:
            fail("E_RECOMPUTE", "injected validation failure")

        require_clean_failure(
            "validation-failure",
            good_populate,
            validation_failure,
            PublicationError,
        )

        concurrent_target = atomic_root / "concurrent-target"

        def create_concurrent_target(_staging: Path) -> None:
            concurrent_target.mkdir()
            (concurrent_target / "owner").write_text("other\n", encoding="utf-8")

        try:
            atomic_prepare_directory(
                concurrent_target, good_populate, create_concurrent_target
            )
        except PublicationError as exc:
            if exc.code != "E_BUNDLE_TARGET":
                fail("E_SELF_TEST", f"concurrent target raised {exc.code}")
        else:
            fail("E_SELF_TEST", "concurrent bundle target was overwritten")
        if (concurrent_target / "owner").read_text(encoding="utf-8") != "other\n":
            fail("E_SELF_TEST", "concurrent bundle target contents changed")
        if list(atomic_root.glob(".concurrent-target.tmp-*")):
            fail("E_SELF_TEST", "concurrent bundle staging tree was not cleaned")
        print("RED control caught: concurrent bundle target preserved")

    print("All V2 negative controls passed.")


def write_evidence_manifest(
    bundle_root: Path,
    provenance: Sequence[Mapping[str, str]],
    package_root: Path,
) -> None:
    """Restamp a deliberately mutated portable-bundle fixture."""
    entries = {
        row["release_path"]: row["sha256"]
        for row in provenance
        if row["state"] in FILE_STATES
    }
    entries["publication/authority.json"] = sha256(package_root / "authority.json")
    entries["publication/provenance.tsv"] = sha256(package_root / "provenance.tsv")
    body = "".join(
        f"{digest}  {member}\n" for member, digest in sorted(entries.items())
    )
    (bundle_root / "EVIDENCE_SHA256SUMS").write_text(body, encoding="utf-8")


def audit_self_test(
    audit_root: Path,
    authority: dict[str, Any],
    provenance: list[dict[str, str]],
    context: dict[str, dict[str, Any]],
    repo_root: Path,
    package_root: Path,
) -> None:
    """Restamp raw-evidence mutations and require primitive replay refusal."""
    from ttg.report_io import load_report

    with tempfile.TemporaryDirectory(prefix="ttg-v2-audit-selftest-") as temporary:
        root = Path(temporary)
        base_bundle = root / "base-bundle"
        prepare_bundle(
            audit_root,
            base_bundle,
            authority,
            provenance,
            context,
            repo_root,
            package_root,
        )

        def make_case(name: str) -> tuple[Path, Path]:
            fixture = root / f"{name}-repo"
            fixture.mkdir()
            copy_clone_fixture(repo_root, package_root, fixture)
            bundle = root / f"{name}-bundle"
            shutil.copytree(base_bundle, bundle)
            return fixture, bundle

        def restamp_case(
            fixture: Path,
            bundle: Path,
            report_id: str,
            report_path: Path,
        ) -> tuple[dict[str, Any], list[dict[str, str]], dict[str, dict[str, Any]]]:
            provenance_path = fixture / "v2" / "provenance.tsv"
            rows = load_provenance(provenance_path)
            report_row = next(
                row
                for row in rows
                if row["kind"] == "report" and row["id"] == report_id
            )
            report_row["sha256"] = sha256(report_path)
            write_provenance(provenance_path, rows)
            shutil.copyfile(
                provenance_path, bundle / "publication" / "provenance.tsv"
            )
            restamp_fixture(fixture / "v2")
            write_evidence_manifest(bundle, rows, fixture / "v2")
            fixture_authority, fixture_provenance, fixture_context = load_and_validate(
                fixture, fixture / "v2"
            )
            validate_evidence_manifest(bundle, fixture_provenance, fixture / "v2")
            audit_evidence(bundle, fixture_provenance, "release_path")
            return fixture_authority, fixture_provenance, fixture_context

        def require_replay_failure(
            name: str,
            expected_code: str,
            bundle: Path,
            fixture_authority: dict[str, Any],
            fixture_provenance: list[dict[str, str]],
            fixture_context: dict[str, dict[str, Any]],
        ) -> None:
            try:
                recompute_results(
                    bundle,
                    "release_path",
                    fixture_authority,
                    fixture_provenance,
                    fixture_context,
                )
            except PublicationError as exc:
                if exc.code != expected_code:
                    fail("E_SELF_TEST", f"{name} expected {expected_code}, got {exc.code}")
                print(f"RED control caught: {expected_code} ({name})")
                return
            fail("E_SELF_TEST", f"{name} restamped mutation unexpectedly replayed")

        curve_fixture, curve_bundle = make_case("stored-curve-corruption")
        curve_report_id = "py-nbx-shipped"
        curve_release_path = next(
            row["release_path"]
            for row in provenance
            if row["kind"] == "report" and row["id"] == curve_report_id
        )
        curve_report_path = curve_bundle / curve_release_path
        curve_report = load_report(curve_report_path)
        curve_row = next(
            row
            for row in curve_report["results"]
            if isinstance(row, dict)
            and "error" not in row
            and (row.get("gold_symbol_count") or 0) > 0
        )
        stored_ttg = curve_row["token_coverage_wire"]["tokens_to_coverage"]
        stored_ttg["50"] = int(stored_ttg["50"]) + 1
        write_json(curve_report_path, curve_report)
        curve_authority, curve_provenance, curve_context = restamp_case(
            curve_fixture,
            curve_bundle,
            curve_report_id,
            curve_report_path,
        )
        require_replay_failure(
            "stored-curve-corruption",
            "E_CURVE_PARITY",
            curve_bundle,
            curve_authority,
            curve_provenance,
            curve_context,
        )

        failure_fixture, failure_bundle = make_case("zero-gold-error-removal")
        failure_report_id = "rust-graphify-32k"
        failure_release_path = next(
            row["release_path"]
            for row in provenance
            if row["kind"] == "report" and row["id"] == failure_report_id
        )
        failure_report_path = failure_bundle / failure_release_path
        failure_report = load_report(failure_report_path)
        failure_report["results"] = [
            row
            for row in failure_report["results"]
            if row.get("instance_id") != "astral-sh__ruff-15626"
        ]
        write_json(failure_report_path, failure_report)
        failure_authority, failure_provenance, failure_context = restamp_case(
            failure_fixture,
            failure_bundle,
            failure_report_id,
            failure_report_path,
        )
        require_replay_failure(
            "zero-gold-error-removal",
            "E_FAILURE_SET",
            failure_bundle,
            failure_authority,
            failure_provenance,
            failure_context,
        )

    print("All V2 raw-evidence negative controls passed.")


def parse_args() -> argparse.Namespace:
    """Parse the offline verifier command line."""
    parser = argparse.ArgumentParser()
    parser.add_argument("--audit-root", type=Path)
    parser.add_argument("--bundle-root", type=Path)
    parser.add_argument("--prepare-bundle", type=Path)
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--write-derived", action="store_true")
    return parser.parse_args()


def main() -> int:
    """Run clone checks and optional retained-evidence gates."""
    args = parse_args()
    if args.audit_root is not None and args.bundle_root is not None:
        fail("E_USAGE", "choose either --audit-root or --bundle-root")
    if args.prepare_bundle is not None and args.audit_root is None:
        fail("E_USAGE", "--prepare-bundle requires --audit-root")

    authority = load_json(AUTHORITY_PATH)
    provenance = load_provenance(PROVENANCE_PATH)
    context = validate_authority(authority, provenance, REPO_ROOT)
    if args.write_derived:
        write_derived(PACKAGE_ROOT, authority, context)
    authority, provenance, context = load_and_validate()

    if args.audit_root is not None:
        audit_evidence(args.audit_root, provenance, "local_audit_path")
        recompute_results(
            args.audit_root,
            "local_audit_path",
            authority,
            provenance,
            context,
        )
    if args.bundle_root is not None:
        validate_evidence_manifest(args.bundle_root, provenance, PACKAGE_ROOT)
        audit_evidence(args.bundle_root, provenance, "release_path")
        recompute_results(
            args.bundle_root,
            "release_path",
            authority,
            provenance,
            context,
        )
    if args.prepare_bundle is not None:
        prepare_bundle(
            args.audit_root,
            args.prepare_bundle,
            authority,
            provenance,
            context,
            REPO_ROOT,
            PACKAGE_ROOT,
        )
    if args.self_test:
        self_test()
        if args.audit_root is not None:
            audit_self_test(
                args.audit_root,
                authority,
                provenance,
                context,
                REPO_ROOT,
                PACKAGE_ROOT,
            )
    print("V2 Tier A A1 publication candidate verification passed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except PublicationError as error:
        print(f"V2 verification failed [{error.code}]: {error}", file=sys.stderr)
        raise SystemExit(1) from error
