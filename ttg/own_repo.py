"""Run it on your own repo — build a one-instance corpus from a merged PR.

The benchmark's gold model transfers to any public repository through the
**bring-your-own-merged-PR** flow (the ruled B7 design): a merged PR's diff is
the reference-patch proxy for "the symbols this change actually needed", the
same protocol (and the same caveat) as the benchmark's own gold. There is no
manual gold path — gold always comes from the versioned freezer pipeline, so
an own-repo readout is derived exactly the way the published numbers were.

Instance construction is PURE (`build_instance` takes the API payloads), so
the suite tests it without network; `fetch_pr` is the thin stdlib urllib layer
over api.github.com (public repos; `GITHUB_TOKEN` honoured for rate limits).

Base-commit semantics: the pre-change state is the FIRST PARENT of the PR's
merge commit — the mainline state the change actually landed on — and the
patch is the compare diff `parent...merge_commit`. This is deliberate: for a
squash merge `pr.base.sha` can drift arbitrarily far from what the patch
applies to, while the merge commit's first parent is exact by construction.
"""

from __future__ import annotations

import json
import os
import re
import urllib.request
from dataclasses import dataclass

from arms.arm_matrix import (
    ARMS,
    INVARIANT_FLAGS,
    ArmError,
    Curation,
    assert_lane_invariants,
)

API = "https://api.github.com"

#: Arms an own-repo run supports: the three §5 arms, all budget-free. A char
#: budget is a property of a FROZEN corpus (derived from its 20k-equivalent);
#: an own-repo run has no frozen corpus, so a budgeted sweep arm is refused.
OWN_REPO_ARMS = ("shipped_treatment", "levers_off_ablation", "native_floor")


class OwnRepoError(ValueError):
    """The PR cannot honestly become a benchmark instance."""


@dataclass(frozen=True)
class OwnRepoInstance:
    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str
    patch: str
    #: Non-fatal honesty notes to surface with the readout (thin statement,
    #: single-instance binary-coverage disclosure, ...).
    disclosures: tuple[str, ...]

    def to_jsonl_row(self) -> str:
        return json.dumps(
            {
                "instance_id": self.instance_id,
                "repo": self.repo,
                "base_commit": self.base_commit,
                "problem_statement": self.problem_statement,
                "patch": self.patch,
            },
            ensure_ascii=False,
        )


def own_repo_flags(arm_name: str) -> list[str]:
    """The complete flag list for one own-repo arm.

    Reuses the matrix's invariants and the lane guard (an absent `--curation`
    is the Waterfill treatment on the other paths — omission stays
    unrepresentable here exactly as it is in the corpus matrix).
    """
    arm = ARMS.get(arm_name)
    if arm is None or arm_name not in OWN_REPO_ARMS:
        raise ArmError(
            f"own-repo runs support the section-5 arms only "
            f"{OWN_REPO_ARMS}; got {arm_name!r}"
        )
    curation = [] if arm.curation is Curation.SHIPPED_DEFAULT else ["--curation", "off"]
    flags = [*INVARIANT_FLAGS, *curation, *arm.extra_flags]
    assert_lane_invariants(flags, arm)
    return flags


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def build_instance(
    repo: str,
    pr_number: int,
    pr: dict,
    merge_commit: dict,
    patch: str,
) -> OwnRepoInstance:
    """Construct the instance from the API payloads. Pure — no network.

    `pr` is `GET /repos/{repo}/pulls/{n}`; `merge_commit` is
    `GET /repos/{repo}/commits/{merge_commit_sha}`; `patch` is the compare
    diff `parent...merge_commit` (`application/vnd.github.diff`).
    """
    if not pr.get("merged_at"):
        raise OwnRepoError(
            f"PR #{pr_number} is not merged — the gold model is the "
            "reference-patch proxy of a MERGED change; an open or closed-"
            "unmerged PR has no landed patch to derive gold from"
        )
    merge_sha = pr.get("merge_commit_sha") or ""
    parents = merge_commit.get("parents") or []
    if not parents:
        raise OwnRepoError(
            f"merge commit {merge_sha[:12]} has no parent — cannot locate the "
            "pre-change state"
        )
    base_commit = parents[0]["sha"]
    if not patch.strip():
        raise OwnRepoError(
            f"PR #{pr_number}: the compare diff {base_commit[:8]}...{merge_sha[:8]} "
            "is empty — nothing landed, so there is no gold to derive"
        )

    title = (pr.get("title") or "").strip()
    body = (pr.get("body") or "").strip()
    statement = f"{title}\n\n{body}".strip()
    disclosures = [
        "single-instance readout: per-instance coverage is COARSE (one task); "
        "run several PRs before reading a trend",
    ]
    if not body:
        disclosures.append(
            "the PR has no description — the problem statement is the title "
            "alone, which is a THIN retrieval query; expect pessimistic "
            "coverage vs a repo whose PRs carry real task text"
        )

    owner_name = _slug(repo.replace("/", "-"))
    return OwnRepoInstance(
        instance_id=f"{owner_name}-pr{pr_number}",
        repo=repo,
        base_commit=base_commit,
        problem_statement=statement,
        patch=patch,
        disclosures=tuple(disclosures),
    )


# --- the thin network layer (not exercised by the suite) ---------------------


def _get(url: str, accept: str = "application/vnd.github+json") -> bytes:
    req = urllib.request.Request(url, headers={"Accept": accept})
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req) as resp:  # noqa: S310 — fixed https host
        return resp.read()


def fetch_pr(repo: str, pr_number: int) -> OwnRepoInstance:
    """Fetch a public repo's merged PR and build the instance."""
    pr = json.loads(_get(f"{API}/repos/{repo}/pulls/{pr_number}"))
    if not pr.get("merged_at"):
        # Fail before the extra round-trips; build_instance re-checks (pure).
        raise OwnRepoError(f"PR #{pr_number} of {repo} is not merged")
    merge_sha = pr["merge_commit_sha"]
    merge_commit = json.loads(_get(f"{API}/repos/{repo}/commits/{merge_sha}"))
    parent = merge_commit["parents"][0]["sha"]
    patch = _get(
        f"{API}/repos/{repo}/compare/{parent}...{merge_sha}",
        accept="application/vnd.github.diff",
    ).decode("utf-8", errors="replace")
    return build_instance(repo, pr_number, pr, merge_commit, patch)
