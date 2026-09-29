"""The delivered arm's cell driver and corpus scorer (B64).

The MCP driver is exercised against a fake stdio JSON-RPC server that only
answers each request after it arrives, so a driver that closed stdin early or
never awaited an answer fails here. The scorer is exercised on a synthetic cell
of a real ts40 gold instance.
"""

from __future__ import annotations

import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

from ttg.acceptance import load_frozen_gold
import subprocess

from ttg.delivered_cells import ROW_PLAN, Instance, mcp_response, prepare_checkout, run_mcp, search_argv
from ttg.delivered_report import MAX_FAILED_CELLS, mcp_content_text, score_corpus

FAKE_MCP = textwrap.dedent(
    """
    import json, sys
    for line in sys.stdin:
        msg = json.loads(line)
        if msg.get("method") == "initialize":
            print(json.dumps({"jsonrpc": "2.0", "id": msg["id"], "result": {"protocolVersion": "2025-06-18"}}), flush=True)
        elif msg.get("method") == "tools/call":
            query = msg["params"]["arguments"]["query"]
            body = json.dumps({"result": {"symbols": [], "echo": query}})
            print(json.dumps({"jsonrpc": "2.0", "id": msg["id"],
                              "result": {"content": [{"type": "text", "text": body}]}}), flush=True)
    """
)


def whitespace_count(data: bytes) -> int:
    return len(data.split())


class RowPlan(unittest.TestCase):
    def test_task_text_follows_the_separator(self) -> None:
        argv = search_argv("nbx", ROW_PLAN[0], "--looks like a flag")
        self.assertEqual(argv[-2:], ["--", "--looks like a flag"])

    def test_budgets_and_surfaces_are_the_preregistered_ones(self) -> None:
        keys = [spec.key for spec in ROW_PLAN if spec.scored]
        self.assertEqual(keys, ["grep.4000", "grep.8000", "grep.32000",
                                "json.4000", "json.8000", "json.32000", "default"])


class McpDriver(unittest.TestCase):
    def test_awaits_each_answer_and_returns_the_content_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            server = Path(tmp) / "fake_mcp.py"
            server.write_text(FAKE_MCP)
            launcher = Path(tmp) / "nbx"
            launcher.write_text(f"#!/bin/sh\nexec {sys.executable} {server}\n")
            launcher.chmod(0o755)
            record = run_mcp(str(launcher), "find the parser", Path(tmp), {}, Path(tmp) / "mcp")
            transcript = (Path(tmp) / "mcp.stdout").read_bytes()
        self.assertEqual(record["rc"], 0)
        self.assertIsNotNone(mcp_response(transcript))
        self.assertEqual(json.loads(mcp_content_text(transcript))["result"]["echo"], "find the parser")


class Checkout(unittest.TestCase):
    def test_the_checkout_origin_is_the_public_github_repository(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            cache = root / "repos" / "owner__repo"
            cache.mkdir(parents=True)
            git = ["git", "-C", str(cache), "-c", "user.email=t@t", "-c", "user.name=t"]
            subprocess.run([*git, "init", "-q"], check=True)
            (cache / "a.ts").write_text("export const a = 1;\n")
            subprocess.run([*git, "add", "."], check=True)
            subprocess.run([*git, "commit", "-q", "-m", "c"], check=True)
            head = subprocess.run([*git, "rev-parse", "HEAD"], check=True, capture_output=True, text=True).stdout.strip()
            checkout = prepare_checkout(root, Instance("ts40", "i", "owner/repo", head, "task"))
            # The stored value: `remote get-url` would apply a host's url.insteadOf.
            origin = subprocess.run(["git", "-C", str(checkout), "config", "--get", "remote.origin.url"],
                                    check=True, capture_output=True, text=True).stdout.strip()
            self.assertEqual(origin, "https://github.com/owner/repo")
            self.assertEqual(checkout.name, "checkout")
            self.assertTrue((checkout / "a.ts").is_file())


def write_cell(root: Path, corpus: str, iid: str, stdout: dict[str, bytes]) -> None:
    cell = root / corpus / iid
    cell.mkdir(parents=True)
    rows = {key: {"argv": [], "rc": 0, "ms": 1} for key in stdout}
    (cell / "cell.json").write_text(json.dumps({"instance_id": iid, "analyze": {"rc": 0}, "rows": rows}))
    for key, data in stdout.items():
        (cell / f"{key}.stdout").write_bytes(data)
        (cell / f"{key}.stderr").write_bytes(b"freshness: ok")


class CorpusScorer(unittest.TestCase):
    def test_scores_one_cell_and_fails_every_unrecorded_instance(self) -> None:
        gold = {k: v for k, v in load_frozen_gold("ts40").items() if v}
        iid = sorted(gold)[0]
        path, name = gold[iid][0].split(":", 1)
        envelope = json.dumps({"result": {"symbols": [
            {"name": name, "location": {"file_path": path, "start_line": 3}}]}}).encode()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            write_cell(root, "ts40", iid, {
                "json.8000": envelope,
                "grep.8000": f"{path}:4:[definition · exact] {name}".encode(),
                "oracle.implement": envelope,
            })
            report = score_corpus(root, "ts40", whitespace_count, {"nbx_sha256": "x"})
        json8 = report["rows"]["json.8000"]
        grep8 = report["rows"]["grep.8000"]
        mine = next(s for s in json8["instances"] if s["instance_id"] == iid)
        self.assertEqual(mine["gold_lower"], 1 / len(gold[iid]))
        self.assertEqual(mine["ttg_wire"], whitespace_count(envelope + b"freshness: ok"))
        self.assertEqual(next(s for s in grep8["instances"] if s["instance_id"] == iid)["gold_lower"],
                         1 / len(gold[iid]))
        self.assertEqual(json8["summary"]["n"], len(gold))
        self.assertEqual(len(json8["summary"]["failed_cells"]), len(gold) - 1)
        self.assertGreater(len(gold) - 1, MAX_FAILED_CELLS)
        self.assertFalse(json8["summary"]["publishable"])
        self.assertTrue(report["publishable_as_delivered"])


if __name__ == "__main__":
    unittest.main()
