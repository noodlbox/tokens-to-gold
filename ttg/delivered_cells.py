"""Run the delivered arm's cells: the shipped `nbx`, invoked as an agent does.

One FRESH cell per gold-bearing instance (PREREGISTRATION addendum §1):
a checkout at `base_commit` under ONE constant directory name (delivered order
must not depend on it, LEDGER B37), `._*` files stripped, a fresh
`NOODLBOX_DATA_DIR`, telemetry off, one `nbx analyze .`, then every row of
`ROW_PLAN` against that one store, in that fixed order. Cells run SEQUENTIALLY
(EVAL-CLONE-RACE): this module never starts a second cell while one runs.

Every invocation's exact argv, exit code, wall ms, stdout and stderr bytes are
written to disk as emitted; scoring (`ttg.delivered_report`) reads only those
files. Nothing here prices or scores.
"""

from __future__ import annotations

import json
import os
import queue
import shutil
import subprocess
import threading
import time
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from ttg.acceptance import load_frozen_gold

BUDGETS = (4000, 8000, 32000)
"""The pre-registered delivered budgets B."""

ORACLE_MAX_TOKENS = 1_000_000
"""The identity oracle's budget: never priced or scored (addendum §3)."""

CELL_TIMEOUT_S = 900
"""Per-invocation timeout, the harness's `--timeout 900` (CURRENT_GATE §1)."""

MCP_PROTOCOL_VERSION = "2025-06-18"


@dataclass(frozen=True)
class RowSpec:
    """One invocation in a cell. `query` rows get the task text after `--`."""

    key: str
    args: tuple[str, ...]
    scored: bool


def _search(key: str, *flags: str, scored: bool = True) -> RowSpec:
    return RowSpec(key, ("search", *flags), scored)


ROW_PLAN: tuple[RowSpec, ...] = (
    *(_search(f"grep.{b}", "--intent", "implement", "--max-tokens", str(b)) for b in BUDGETS),
    *(
        _search(f"json.{b}", "--intent", "implement", "--format", "json", "--max-tokens", str(b))
        for b in BUDGETS
    ),
    _search("default"),
    _search(
        "oracle.implement", "--intent", "implement", "--format", "json",
        "--max-tokens", str(ORACLE_MAX_TOKENS), scored=False,
    ),
    _search(
        "oracle.explore", "--intent", "explore", "--format", "json",
        "--max-tokens", str(ORACLE_MAX_TOKENS), scored=False,
    ),
    _search("json.explore_default", "--format", "json", scored=False),
)
"""The fixed in-cell order. The `mcp` row runs after these (it is a session,
not an argv). `json.explore_default` is the MCP byte-identity comparand."""

MCP_ROW = "mcp"


def search_argv(nbx: str, spec: RowSpec, task: str) -> list[str]:
    return [nbx, *spec.args, "--", task]


@dataclass(frozen=True)
class Instance:
    corpus: str
    instance_id: str
    repo: str
    base_commit: str
    problem_statement: str


def gold_bearing_instances(corpus: str, jsonl: Path) -> Iterator[Instance]:
    """The corpus's gold-bearing instances (the binding basis), in file order."""
    gold = load_frozen_gold(corpus)
    for line in jsonl.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        doc = json.loads(line)
        if gold.get(doc["instance_id"]):
            yield Instance(
                corpus=corpus,
                instance_id=doc["instance_id"],
                repo=doc["repo"],
                base_commit=doc["base_commit"],
                problem_statement=doc["problem_statement"],
            )


def _record(prefix: Path, argv: Sequence[str], rc: int, ms: int, stdout: bytes, stderr: bytes) -> dict[str, object]:
    prefix.with_suffix(".stdout").write_bytes(stdout)
    prefix.with_suffix(".stderr").write_bytes(stderr)
    return {"argv": list(argv), "rc": rc, "ms": ms}


def run_invocation(argv: Sequence[str], cwd: Path, env: Mapping[str, str], prefix: Path) -> dict[str, object]:
    start = time.monotonic()
    try:
        proc = subprocess.run(
            list(argv), cwd=cwd, env=dict(env), capture_output=True, timeout=CELL_TIMEOUT_S, check=False
        )
        rc, stdout, stderr = proc.returncode, proc.stdout, proc.stderr
    except subprocess.TimeoutExpired as exc:
        rc, stdout, stderr = 124, exc.stdout or b"", exc.stderr or b""
    return _record(prefix, argv, rc, round((time.monotonic() - start) * 1000), stdout, stderr)


def mcp_request(request_id: int, method: str, params: Mapping[str, object]) -> bytes:
    return (json.dumps({"jsonrpc": "2.0", "id": request_id, "method": method, "params": dict(params)}) + "\n").encode()


def mcp_initialize() -> bytes:
    return mcp_request(1, "initialize", {
        "protocolVersion": MCP_PROTOCOL_VERSION,
        "capabilities": {},
        "clientInfo": {"name": "tokens-to-gold", "version": "1"},
    })


def mcp_search_call(task: str) -> bytes:
    """The one tool call: `nbx_search` with the task text as `query` and no
    other argument (addendum 2 C). Preceded by the `initialized` notification."""
    initialized = json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
    return initialized.encode() + mcp_request(2, "tools/call", {"name": "nbx_search", "arguments": {"query": task}})


def mcp_response(transcript: bytes, request_id: int = 2) -> Mapping[str, object] | None:
    """The JSON-RPC response with `request_id` in a newline-delimited transcript."""
    for line in transcript.splitlines():
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(message, Mapping) and message.get("id") == request_id:
            return message
    return None


def _await_response(lines: queue.Queue[bytes | None], seen: list[bytes], request_id: int, deadline: float) -> bool:
    """Collect stdout lines into `seen` until the `request_id` response arrives
    (True), the server closes stdout, or the deadline passes (False)."""
    while (remaining := deadline - time.monotonic()) > 0:
        try:
            line = lines.get(timeout=remaining)
        except queue.Empty:
            return False
        if line is None:
            return False
        seen.append(line)
        if mcp_response(line, request_id) is not None:
            return True
    return False


def run_mcp(nbx: str, task: str, cwd: Path, env: Mapping[str, str], prefix: Path) -> dict[str, object]:
    """Drive `nbx mcp` over stdio: initialize, await its answer, call
    `nbx_search`, await its answer, then close stdin. The raw transcript is the
    row's stdout; a missing answer is rc 124 (the cell fails)."""
    argv = [nbx, "mcp"]
    start = time.monotonic()
    deadline = start + CELL_TIMEOUT_S
    proc = subprocess.Popen(
        argv, cwd=cwd, env=dict(env), stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE
    )
    lines: queue.Queue[bytes | None] = queue.Queue()
    stderr_chunks: list[bytes] = []

    def pump_stdout() -> None:
        for line in proc.stdout:
            lines.put(line)
        lines.put(None)

    def pump_stderr() -> None:
        stderr_chunks.append(proc.stderr.read())

    readers = [threading.Thread(target=pump_stdout), threading.Thread(target=pump_stderr)]
    for reader in readers:
        reader.start()
    seen: list[bytes] = []
    proc.stdin.write(mcp_initialize())
    proc.stdin.flush()
    answered = _await_response(lines, seen, 1, deadline)
    if answered:
        proc.stdin.write(mcp_search_call(task))
        proc.stdin.flush()
        answered = _await_response(lines, seen, 2, deadline)
    proc.stdin.close()
    try:
        proc.wait(timeout=max(1.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
    for reader in readers:
        reader.join()
    proc.stdout.close()
    proc.stderr.close()
    while (line := lines.get()) is not None:
        seen.append(line)
    rc = proc.returncode if answered else 124
    return _record(prefix, argv, rc, round((time.monotonic() - start) * 1000), b"".join(seen), b"".join(stderr_chunks))


CHECKOUT_NAME = "checkout"
"""The one constant checkout directory basename, for every cell (B37)."""


def github_url(repo: str) -> str:
    return f"https://github.com/{repo}"


def _git(*args: str) -> None:
    subprocess.run(["git", *args], check=True, capture_output=True)


def _strip_appledouble(root: Path) -> None:
    for path in root.rglob("._*"):
        if path.is_file():
            path.unlink()


def prepare_checkout(root: Path, instance: Instance) -> Path:
    """A fresh checkout at `base_commit` under `<root>/cell/checkout`, cloned
    from a per-repo cache (`<root>/repos`), `._*` stripped."""
    cache = root / "repos" / instance.repo.replace("/", "__")
    if not cache.is_dir():
        # A FULL clone: a --shared clone of a partial (blob-filtered) clone
        # inherits promisor state that libgit2 (nbx's git status) cannot read.
        _git("clone", "-q", github_url(instance.repo), str(cache))
    checkout = root / "cell" / CHECKOUT_NAME
    shutil.rmtree(checkout.parent, ignore_errors=True)
    checkout.parent.mkdir(parents=True)
    _git("clone", "-q", "--shared", "--no-checkout", str(cache), str(checkout))
    # The checkout must look like an agent's: its origin is the public GitHub
    # repository, not the local cache. nbx settles visibility from the remote,
    # and a checkout with no GitHub remote is treated as private.
    _git("-C", str(checkout), "remote", "set-url", "origin", github_url(instance.repo))
    _git("-C", str(checkout), "checkout", "-q", "--detach", instance.base_commit)
    _strip_appledouble(checkout)
    return checkout


def run_cell(nbx: str, root: Path, instance: Instance) -> Path:
    """Run one instance's cell; resumable (an existing `cell.json` is kept)."""
    out = root / "out" / instance.corpus / instance.instance_id
    manifest = out / "cell.json"
    if manifest.is_file():
        return manifest
    out.mkdir(parents=True, exist_ok=True)
    checkout = prepare_checkout(root, instance)
    store = root / "cell" / "store"
    shutil.rmtree(store, ignore_errors=True)
    # The agent's own environment, as it runs: signed in (NOODLBOX_API_KEY is
    # checked by `delivered-run` before any cell), telemetry off, a fresh store.
    env = dict(os.environ, NOODLBOX_DATA_DIR=str(store), NOODLBOX_DISABLE_TELEMETRY="1", DO_NOT_TRACK="1")
    cell: dict[str, object] = {
        "corpus": instance.corpus,
        "instance_id": instance.instance_id,
        "base_commit": instance.base_commit,
        "analyze": run_invocation([nbx, "analyze", "."], checkout, env, out / "analyze"),
    }
    rows: dict[str, object] = {}
    analyze = cell["analyze"]
    if isinstance(analyze, Mapping) and analyze.get("rc") == 0:
        for spec in ROW_PLAN:
            rows[spec.key] = run_invocation(
                search_argv(nbx, spec, instance.problem_statement), checkout, env, out / spec.key
            )
        rows[MCP_ROW] = run_mcp(nbx, instance.problem_statement, checkout, env, out / MCP_ROW)
    cell["rows"] = rows
    manifest.write_text(json.dumps(cell, indent=1), encoding="utf-8")
    shutil.rmtree(root / "cell", ignore_errors=True)
    return manifest


def run_corpus(nbx: str, root: Path, corpus: str, jsonl: Path, only: frozenset[str] | None = None) -> list[Path]:
    """Every gold-bearing instance of one corpus (or the `only` subset), one
    cell at a time. A subset run is never publishable: every instance it skips
    scores as a failed cell (`ttg.delivered_report`)."""
    return [
        run_cell(nbx, root, instance)
        for instance in gold_bearing_instances(corpus, jsonl)
        if only is None or instance.instance_id in only
    ]
