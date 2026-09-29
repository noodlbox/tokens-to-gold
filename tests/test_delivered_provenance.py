"""Addendum 3: asserted local pinned provenance and itemised stderr.

The stderr lines are the real ones a signed-in `nbx search` emitted on the
harness smoke (their cursor payload shortened).
"""

from __future__ import annotations

import json
import unittest

from ttg.delivered_provenance import ProvenanceError, StderrKind, classify, itemise, local_pinned_provenance

BASE = "82ac179c1de4c216c4e333093044fac643303f0c"
STATUS = json.dumps({"box_id": "55ca4098-b44a-4d9c-81f3-4d3f711b4e67", "noodlbox_version": "2.8.0"})


def oracle(**changes) -> str:
    snapshot = {
        "repository": "checkout",
        "analysis_revision": "blake3-8b50",
        "source_revision": BASE,
        "freshness": {"per_repo": [{"alias": "checkout", "analyzed_commit": "82ac179", "head_matches": True}],
                      "serves": "committed_only"},
    }
    snapshot.update(changes)
    return json.dumps({"result": {}, "snapshot": snapshot})


class LocalPinnedProvenance(unittest.TestCase):
    def test_the_pinned_local_read_asserts(self) -> None:
        got = local_pinned_provenance(STATUS, oracle(), BASE, "checkout")
        self.assertEqual((got.box_id, got.serves), ("55ca4098-b44a-4d9c-81f3-4d3f711b4e67", "committed_only"))

    def test_another_commit_fails(self) -> None:
        with self.assertRaises(ProvenanceError):
            local_pinned_provenance(STATUS, oracle(source_revision="f" * 40), BASE, "checkout")

    def test_a_read_that_is_not_the_committed_local_box_fails(self) -> None:
        freshness = {"per_repo": [{"analyzed_commit": "82ac179", "head_matches": True}], "serves": "hub"}
        with self.assertRaises(ProvenanceError):
            local_pinned_provenance(STATUS, oracle(freshness=freshness), BASE, "checkout")

    def test_another_repository_fails(self) -> None:
        with self.assertRaises(ProvenanceError):
            local_pinned_provenance(STATUS, oracle(repository="react"), BASE, "checkout")

    def test_no_local_box_fails(self) -> None:
        with self.assertRaises(ProvenanceError):
            local_pinned_provenance(json.dumps({"box_id": None}), oracle(), BASE, "checkout")


REAL_STDERR = "\n".join([
    "[noodlbox] graph@82ac179 · HEAD 82ac179 · fresh · serves:committed-only · graph holds 53 of 70 walked files",
    "[noodlbox] 499 shown · 219 more omitted by budget · --cursor nbx-search-v2.eyJ2ZXJzaW9uIjoy",
    "Source and relationships: nbx def '2cb8' --include-content --json --box '/x/checkout' --repo 'checkout'",
    "[noodlbox] search model not installed — results are keyword-ordered (BM25)",
    "thread 'main' panicked",
])


class StderrItemised(unittest.TestCase):
    def test_every_real_line_lands_in_its_kind(self) -> None:
        kinds = [classify(line) for line in REAL_STDERR.splitlines()]
        self.assertEqual(kinds, [StderrKind.FRESHNESS_RECEIPT, StderrKind.BUDGET_FOOTER,
                                 StderrKind.EXPANSION_HINT, StderrKind.NOTICE, StderrKind.OTHER])

    def test_no_line_is_dropped(self) -> None:
        grouped = itemise(REAL_STDERR)
        self.assertEqual(sum(len(text.splitlines()) for text in grouped.values()), 5)


if __name__ == "__main__":
    unittest.main()
