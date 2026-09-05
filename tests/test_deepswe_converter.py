"""Faithfulness gate for `ttg/deepswe_to_jsonl.py`.

The converter is the versioned, reproducible way to build a DeepSWE-lineage
corpus JSONL (ts40, go34). Its acceptance is byte-identity against the homed
`ts40.jsonl` — proving the field lineage (instance_id/repo/base_commit/
problem_statement/patch) reifies the frozen corpus, not an approximation.

Requires the DeepSWE task tree; set DEEPSWE_TASKS to
`…/noodlbox-evals/deep-swe/tasks`. Skips (does not fail) when absent, so the
suite stays runnable on a fresh clone without the private task tree.

Documented exception: one ts40 row (`eicrud-keyset-pagination-cursor`) carries
a 7-char abbreviated `base_commit_hash` in its task.toml; the frozen ts40 holds
the full 40-hex commit. They are the same commit (prefix), so that field is
asserted prefix-equivalent rather than byte-equal. Every other field on every
row — and every field of every non-abbreviated row — is byte-equal.
"""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path

from ttg.deepswe_to_jsonl import select_by_ids, task_to_row

_CORPORA_ENV = "TTG_CORPORA_DIR"  # dir holding ts40.jsonl (private wiki corpora/)
_TASKS_ENV = "DEEPSWE_TASKS"


def _tasks_root() -> Path | None:
    v = os.environ.get(_TASKS_ENV)
    return Path(v) if v and Path(v).is_dir() else None


def _corpus(name: str) -> Path | None:
    v = os.environ.get(_CORPORA_ENV)
    if not v:
        return None
    p = Path(v) / name
    return p if p.exists() else None


class DeepSweConverterTest(unittest.TestCase):
    def setUp(self) -> None:
        tasks = _tasks_root()
        ts40 = _corpus("ts40.jsonl")
        if tasks is None or ts40 is None:
            self.skipTest(
                f"set {_TASKS_ENV} and {_CORPORA_ENV} to run the byte-match gate")
        self.tasks: Path = tasks
        self.ts40: Path = ts40

    def test_ts40_reifies_byte_exact_modulo_abbreviated_commit(self) -> None:
        homed = [json.loads(ln) for ln in self.ts40.read_text().splitlines() if ln]
        ids = {r["instance_id"] for r in homed}
        regen = {d.name: task_to_row(d) for d in select_by_ids(self.tasks, ids)}
        homed_by_id = {r["instance_id"]: r for r in homed}

        self.assertEqual(set(regen), set(homed_by_id), "id set must match")
        for iid, want in homed_by_id.items():
            got = regen[iid]
            for field in ("instance_id", "repo", "problem_statement", "patch"):
                self.assertEqual(got[field], want[field], f"{iid}.{field}")
            if len(got["base_commit"]) == 40:
                self.assertEqual(got["base_commit"], want["base_commit"],
                                 f"{iid}.base_commit")
            else:  # abbreviated task.toml hash — must be a prefix of the full
                self.assertTrue(want["base_commit"].startswith(got["base_commit"]),
                                f"{iid}.base_commit not prefix-equivalent")

    def test_ts40_full_hash_rows_are_line_byte_identical(self) -> None:
        """Every row whose task.toml carries a full 40-hex commit must
        serialize line-byte-identical to the homed ts40 (catches any JSON
        formatting / ordering / encoding drift, not just field equality)."""
        homed_lines = {json.loads(ln)["instance_id"]: ln
                       for ln in self.ts40.read_text().splitlines() if ln}
        ids = set(homed_lines)
        for d in select_by_ids(self.tasks, ids):
            row = task_to_row(d)
            if len(row["base_commit"]) != 40:
                continue
            line = json.dumps(row, ensure_ascii=False)
            self.assertEqual(line, homed_lines[d.name], f"{d.name} line bytes")


if __name__ == "__main__":
    unittest.main()
