"""Addendum 3: every delivered cell's analysis is local and pinned, and its
stderr is itemised.

Provenance is read from what the binary itself reports -- `nbx status --json`
(the box) and the JSON identity oracle's envelope `snapshot` (what the read
served) -- and asserted: the served source revision is the cell's pinned
`base_commit`, every repo's analyzed commit is that commit, the read served the
committed LOCAL box, and the repository is the cell's own checkout. A cell
whose provenance does not assert is a FAILED cell.

stderr is classified by the product's own line prefixes (crates/nbx search and
read receipts); an unrecognised line is `other`, never dropped.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Mapping
from dataclasses import dataclass
from enum import Enum

from ttg.delivered import DeliveredScoringError


class ProvenanceError(DeliveredScoringError):
    """The cell's analysis is not provably the pinned commit, analysed locally."""


@dataclass(frozen=True)
class Provenance:
    box_id: str
    noodlbox_version: str
    source_revision: str
    analysis_revision: str
    serves: str


def _json(text: str, what: str) -> Mapping[str, object]:
    try:
        doc = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ProvenanceError(f"{what} is not JSON: {exc}") from exc
    if not isinstance(doc, Mapping):
        raise ProvenanceError(f"{what} is not a JSON object")
    return doc


def local_pinned_provenance(
    status_text: str, oracle_text: str, base_commit: str, checkout_name: str
) -> Provenance:
    status = _json(status_text, "nbx status --json")
    snapshot = _json(oracle_text, "the identity oracle").get("snapshot")
    if not isinstance(snapshot, Mapping):
        raise ProvenanceError("the identity oracle carries no snapshot")
    freshness = snapshot.get("freshness")
    per_repo = freshness.get("per_repo") if isinstance(freshness, Mapping) else None
    if not isinstance(per_repo, list) or not per_repo:
        raise ProvenanceError("the snapshot names no analysed repository")
    if snapshot.get("source_revision") != base_commit:
        raise ProvenanceError(
            f"served source {snapshot.get('source_revision')!r} is not the pinned {base_commit}"
        )
    for repo in per_repo:
        analyzed = repo.get("analyzed_commit") if isinstance(repo, Mapping) else None
        if not isinstance(analyzed, str) or not analyzed or not base_commit.startswith(analyzed):
            raise ProvenanceError(f"analysed commit {analyzed!r} is not the pinned {base_commit}")
        if repo.get("head_matches") is not True:
            raise ProvenanceError("an analysed repository's head does not match its checkout")
    serves = freshness.get("serves") if isinstance(freshness, Mapping) else None
    if serves != "committed_only":
        raise ProvenanceError(f"the read served {serves!r}, not the committed local box")
    if snapshot.get("repository") != checkout_name:
        raise ProvenanceError(f"the read served repository {snapshot.get('repository')!r}, not the cell's checkout")
    box_id = status.get("box_id")
    if not isinstance(box_id, str) or not box_id:
        raise ProvenanceError("nbx status reports no local box")
    return Provenance(
        box_id=box_id,
        noodlbox_version=str(status.get("noodlbox_version")),
        source_revision=base_commit,
        analysis_revision=str(snapshot.get("analysis_revision")),
        serves=serves,
    )


class StderrKind(str, Enum):
    FRESHNESS_RECEIPT = "freshness_receipt"
    BUDGET_FOOTER = "budget_footer"
    EXPANSION_HINT = "expansion_hint"
    NOTICE = "notice"
    OTHER = "other"


_PRODUCT_PREFIX = "[noodlbox] "
_FRESHNESS_PREFIX = "[noodlbox] graph@"
_HINT_PREFIX = "Source and relationships: "
_FOOTER_MARKER = " shown"


def classify(line: str) -> StderrKind:
    if line.startswith(_FRESHNESS_PREFIX):
        return StderrKind.FRESHNESS_RECEIPT
    if line.startswith(_PRODUCT_PREFIX) and _FOOTER_MARKER in line:
        return StderrKind.BUDGET_FOOTER
    if line.startswith(_HINT_PREFIX):
        return StderrKind.EXPANSION_HINT
    if line.startswith(_PRODUCT_PREFIX):
        return StderrKind.NOTICE
    return StderrKind.OTHER


def itemise(stderr: str) -> dict[StderrKind, str]:
    """stderr grouped by kind, each kind's lines in order (newline-joined)."""
    grouped: dict[StderrKind, list[str]] = {}
    for line in stderr.splitlines():
        if line:
            grouped.setdefault(classify(line), []).append(line)
    return {kind: "\n".join(lines) for kind, lines in grouped.items()}


API_BASE = "https://api.noodlbox.io"
HARNESS_USER_AGENT = "tokens-to-gold/1"
"""The production API a release `nbx` talks to (debug builds target dev)."""


def account_orgs(key: str, api_base: str = API_BASE) -> list[dict[str, str]]:
    """The signed-in key's organisations and their tiers from `GET /api/orgs` (addendum 3: the tier
    is recorded once per run, since entitlement can change behaviour). The key
    travels in a header, never in argv. A failed read is a refusal."""
    # An explicit user agent: the edge (Cloudflare, error 1010) refuses
    # Python's default signature. The route has no trailing slash.
    request = urllib.request.Request(
        f"{api_base}/api/orgs", headers={"x-api-key": key, "User-Agent": HARNESS_USER_AGENT}
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            doc = json.loads(response.read())
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ProvenanceError(f"the key's organisations could not be read: {exc}") from exc
    orgs = doc if isinstance(doc, list) else doc.get("data") if isinstance(doc, Mapping) else None
    if not isinstance(orgs, list) or not orgs:
        raise ProvenanceError("the key belongs to no organisation")
    return [{"slug": str(org.get("slug")), "tier": str(org.get("tier"))} for org in orgs if isinstance(org, Mapping)]
