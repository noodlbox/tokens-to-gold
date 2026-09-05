#!/usr/bin/env python3
"""Convert DeepSWE task directories into a benchmark corpus JSONL.

Single source of truth for building `ts40.jsonl` / `go34.jsonl` from the
DeepSWE task tree, so a corpus is reproducible from committed inputs rather
than a one-off hand run (the 2026-09 provenance audit flagged that the ts40
converter was never versioned).

Row schema (key order is load-bearing for byte-identity):
    instance_id, repo, base_commit, problem_statement, patch

Field lineage, verified byte-exact against the homed ts40.jsonl:
    instance_id       = task directory name (== task.toml task_id)
    repo              = task.toml repository_url, sans "https://github.com/"
    base_commit       = task.toml base_commit_hash
    problem_statement = instruction.md, verbatim
    patch             = solution/solution.patch, verbatim

Emission: one `json.dumps(row, ensure_ascii=False)` per line, rows sorted by
instance_id. No trailing newline discipline beyond one '\n' per row.
"""

from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

_GH_PREFIX = "https://github.com/"


# DeepSWE task.toml keeps these under [metadata]; look there explicitly rather
# than scanning every table. Explicit beats both a top-level-only lookup (which
# misses them entirely) and a first-table-that-has-the-key scan (order-dependent,
# and for a byte-identity corpus builder a silent wrong value is worse than a
# KeyError). A missing key fails fast.
def _find(toml_doc: dict, key: str) -> str:
    """Return the [metadata] value for `key`, failing fast if absent."""
    metadata = toml_doc.get("metadata")
    if not isinstance(metadata, dict):
        raise KeyError("task.toml has no [metadata] table")
    return metadata[key]


def task_to_row(task_dir: Path) -> dict[str, str]:
    toml = tomllib.loads((task_dir / "task.toml").read_text())
    repo = _find(toml, "repository_url")
    if repo.startswith(_GH_PREFIX):
        repo = repo[len(_GH_PREFIX):]
    repo = repo.removesuffix(".git")
    return {
        "instance_id": task_dir.name,
        "repo": repo,
        "base_commit": _find(toml, "base_commit_hash"),
        "problem_statement": (task_dir / "instruction.md").read_text(),
        "patch": (task_dir / "solution" / "solution.patch").read_text(),
    }


def select_by_language(tasks_root: Path, languages: set[str]) -> list[Path]:
    """Task dirs whose task.toml language is in `languages` (for MINTING a new
    tier). A curated corpus (e.g. ts40) is NOT a language filter — its 40 ids
    are a specific subset of the ts+js tasks; drive those from an id manifest
    (`select_by_ids`) so the set is authoritative, not inferred."""
    selected = []
    for task_toml in tasks_root.glob("*/task.toml"):
        lang = _find(tomllib.loads(task_toml.read_text()), "language")
        if lang in languages:
            selected.append(task_toml.parent)
    return sorted(selected, key=lambda d: d.name)


def select_by_ids(tasks_root: Path, ids: set[str]) -> list[Path]:
    """Task dirs named by an explicit instance-id manifest (the authoritative
    definition of a corpus). Fails closed on any id without a task dir rather
    than silently dropping it."""
    dirs = []
    for iid in sorted(ids):
        d = tasks_root / iid
        if not (d / "task.toml").exists():
            raise FileNotFoundError(f"no DeepSWE task dir for instance_id {iid!r}")
        dirs.append(d)
    return dirs


def build_jsonl(task_dirs: list[Path]) -> str:
    # Sort at the emission point so the "rows sorted by instance_id" invariant
    # the module docstring promises holds regardless of caller ordering -- a
    # caller passing unsorted dirs must not silently break byte-identity.
    rows = [task_to_row(d) for d in sorted(task_dirs, key=lambda d: d.name)]
    return "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows)


def _read_ids(ids_file: Path | None, ids_from_jsonl: Path | None) -> set[str]:
    # argparse guarantees exactly one of the two is set (mutually-exclusive,
    # required); assert it so the reader isn't a partial function on paper.
    src = ids_file or ids_from_jsonl
    assert src is not None, "one of --ids-file / --ids-from-jsonl is required"
    lines = [ln for ln in src.read_text().splitlines() if ln.strip()]
    if ids_file is not None:
        return {ln.strip() for ln in lines}
    return {json.loads(ln)["instance_id"] for ln in lines}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--tasks-root", required=True, type=Path,
                    help="DeepSWE tasks directory (…/deep-swe/tasks)")
    sel = ap.add_mutually_exclusive_group(required=True)
    sel.add_argument("--languages",
                     help="MINT a new tier: comma-separated task.toml "
                          "languages, e.g. 'go'. Emits every matching task.")
    sel.add_argument("--ids-file", type=Path,
                     help="reify an explicit instance-id manifest (one id/line)")
    sel.add_argument("--ids-from-jsonl", type=Path,
                     help="reify the instance_ids of a reference corpus jsonl "
                          "(used for the ts40 byte-match self-test)")
    ap.add_argument("--out", type=Path,
                    help="output .jsonl (default: stdout)")
    args = ap.parse_args()
    if args.languages:
        langs = {s.strip() for s in args.languages.split(",") if s.strip()}
        task_dirs = select_by_language(args.tasks_root, langs)
    else:
        ids = _read_ids(args.ids_file, args.ids_from_jsonl)
        task_dirs = select_by_ids(args.tasks_root, ids)
    body = build_jsonl(task_dirs)
    if args.out:
        args.out.write_text(body)
    else:
        sys.stdout.write(body)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
