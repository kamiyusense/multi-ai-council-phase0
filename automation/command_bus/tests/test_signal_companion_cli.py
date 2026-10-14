"""Unit tests for Windows Signal Companion v1 CLI bridge (SF-12).

Tests:
- subcommand state output and exit code 0 for valid, missing, unreadable, and malformed snapshots
- subcommand state --max-age parameter passing
- subcommand notify output and exit code 0 for valid, missing, and unreadable files, including --first-run
- subcommand notify missing --seen file handled as empty seen state
- subcommand notify seen_state round-trip prevents duplicate notifications
- bad arguments (unknown subcommand, missing option, --now without Z, non-integer --max-age) exit code 2
- utf-8 encoding compliance when reading files
- module purity: standard library only, no file writes/network/subprocess
"""
from __future__ import annotations

import ast
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation.command_bus import signal_companion_cli as cli


def _make_lane(
    loop_id: str = "auto-claude-gemini",
    display_name: str = "Claude -> Gemini",
    mode: str = "AUTO",
    display_state: str = "AUTO",
    controller_kind: str = "CLAUDE",
    worker_kind: str = "GEMINI",
    identity_state: str = "DURABLE",
    generation: int | None = 4,
    target_ref: str | None = "pr:10",
    last_event_kind: str | None = "TURN_COMPLETE",
    last_event_id: str | None = "receipt-100",
    schedule_hint: dict | None = None,
    human_action: str = "NONE",
    safe_detail_ref: str = "issue:33",
) -> dict:
    return {
        "loop_id": loop_id,
        "display_name": display_name,
        "mode": mode,
        "display_state": display_state,
        "controller_kind": controller_kind,
        "worker_kind": worker_kind,
        "identity_state": identity_state,
        "generation": generation,
        "target_ref": target_ref,
        "last_event_kind": last_event_kind,
        "last_event_id": last_event_id,
        "schedule_hint": schedule_hint,
        "human_action": human_action,
        "safe_detail_ref": safe_detail_ref,
    }


def _make_snapshot(
    loops: list[dict] | None = None,
    generated_at: str = "2026-09-28T11:55:00Z",
) -> str:
    if loops is None:
        loops = [_make_lane()]
    return json.dumps(
        {
            "schema_version": 1,
            "project": "phase0",
            "generated_at": generated_at,
            "loops": loops,
        }
    )


class StateSubcommandTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def _write_file(self, filename: str, content: str, encoding: str = "utf-8") -> str:
        filepath = os.path.join(self.temp_dir.name, filename)
        with open(filepath, "w", encoding=encoding) as f:
            f.write(content)
        return filepath

    def test_state_valid_snapshot(self):
        snap_path = self._write_file("snap.json", _make_snapshot())
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = cli.main(["state", "--snapshot", snap_path, "--now", "2026-09-28T12:00:00Z"])
        self.assertEqual(code, 0)
        output = json.loads(stdout.getvalue().strip())
        self.assertEqual(output["color"], "PURPLE")
        self.assertEqual(output["reason_code"], "AUTO_ACTIVE")

    def test_state_custom_max_age(self):
        # snapshot 700s old (generated at 11:48:20Z, now is 12:00:00Z)
        snap_path = self._write_file(
            "snap_old.json", _make_snapshot(generated_at="2026-09-28T11:48:20Z")
        )

        # Default --max-age 600 -> SNAPSHOT_STALE
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = cli.main(["state", "--snapshot", snap_path, "--now", "2026-09-28T12:00:00Z"])
        self.assertEqual(code, 0)
        out_default = json.loads(stdout.getvalue().strip())
        self.assertEqual(out_default["color"], "WHITE")
        self.assertEqual(out_default["reason_code"], "SNAPSHOT_STALE")

        # Custom --max-age 1000 -> PURPLE
        stdout_custom = io.StringIO()
        with patch("sys.stdout", stdout_custom):
            code_custom = cli.main(
                ["state", "--snapshot", snap_path, "--now", "2026-09-28T12:00:00Z", "--max-age", "1000"]
            )
        self.assertEqual(code_custom, 0)
        out_custom = json.loads(stdout_custom.getvalue().strip())
        self.assertEqual(out_custom["color"], "PURPLE")

    def test_state_missing_snapshot_file(self):
        missing_path = os.path.join(self.temp_dir.name, "does_not_exist.json")
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = cli.main(["state", "--snapshot", missing_path, "--now", "2026-09-28T12:00:00Z"])
        self.assertEqual(code, 0)
        output = json.loads(stdout.getvalue().strip())
        self.assertEqual(output["color"], "WHITE")
        self.assertEqual(output["reason_code"], "SNAPSHOT_MISSING")

    def test_state_unreadable_snapshot_directory(self):
        dir_path = self.temp_dir.name
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = cli.main(["state", "--snapshot", dir_path, "--now", "2026-09-28T12:00:00Z"])
        self.assertEqual(code, 0)
        output = json.loads(stdout.getvalue().strip())
        self.assertEqual(output["color"], "WHITE")
        self.assertEqual(output["reason_code"], "SNAPSHOT_MISSING")

    def test_state_malformed_snapshot_file(self):
        bad_path = self._write_file("bad.json", "this-is-not-json")
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = cli.main(["state", "--snapshot", bad_path, "--now", "2026-09-28T12:00:00Z"])
        self.assertEqual(code, 0)
        output = json.loads(stdout.getvalue().strip())
        self.assertEqual(output["color"], "WHITE")
        self.assertEqual(output["reason_code"], "SNAPSHOT_MALFORMED")


class NotifySubcommandTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp_dir.cleanup)

    def _write_file(self, filename: str, content: str, encoding: str = "utf-8") -> str:
        filepath = os.path.join(self.temp_dir.name, filename)
        with open(filepath, "w", encoding=encoding) as f:
            f.write(content)
        return filepath

    def test_notify_valid_files(self):
        snap_path = self._write_file("snap.json", _make_snapshot())
        seen_path = self._write_file("seen.json", json.dumps({"seen_event_ids": []}))
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = cli.main(["notify", "--snapshot", snap_path, "--seen", seen_path])
        self.assertEqual(code, 0)
        output = json.loads(stdout.getvalue().strip())
        self.assertIn("notifications", output)
        self.assertIn("seen_state", output)
        self.assertEqual(len(output["notifications"]), 1)
        self.assertEqual(output["notifications"][0]["kind"], "TURN_COMPLETE")

    def test_notify_seen_state_round_trip_gives_no_repeat(self):
        snap_path = self._write_file("snap.json", _make_snapshot())
        seen_path_1 = self._write_file("seen_1.json", json.dumps({"seen_event_ids": []}))
        stdout_1 = io.StringIO()
        with patch("sys.stdout", stdout_1):
            code_1 = cli.main(["notify", "--snapshot", snap_path, "--seen", seen_path_1])
        self.assertEqual(code_1, 0)
        output_1 = json.loads(stdout_1.getvalue().strip())
        self.assertEqual(len(output_1["notifications"]), 1)
        self.assertEqual(output_1["notifications"][0]["event_id"], "receipt-100")

        # Round-trip: write the printed seen_state to a second file and run notify again
        seen_path_2 = self._write_file("seen_2.json", json.dumps(output_1["seen_state"]))
        stdout_2 = io.StringIO()
        with patch("sys.stdout", stdout_2):
            code_2 = cli.main(["notify", "--snapshot", snap_path, "--seen", seen_path_2])
        self.assertEqual(code_2, 0)
        output_2 = json.loads(stdout_2.getvalue().strip())
        self.assertEqual(output_2["notifications"], [])
        self.assertEqual(output_2["seen_state"], output_1["seen_state"])

    def test_notify_first_run(self):
        snap_path = self._write_file("snap.json", _make_snapshot())
        seen_path = self._write_file("seen.json", json.dumps({"seen_event_ids": []}))
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = cli.main(["notify", "--snapshot", snap_path, "--seen", seen_path, "--first-run"])
        self.assertEqual(code, 0)
        output = json.loads(stdout.getvalue().strip())
        # TURN_COMPLETE on first_run is marked seen without notifying
        self.assertEqual(len(output["notifications"]), 0)
        self.assertIn("receipt-100", output["seen_state"]["seen_event_ids"])

    def test_notify_missing_seen_file_counts_as_empty_seen_state(self):
        snap_path = self._write_file("snap.json", _make_snapshot())
        missing_seen = os.path.join(self.temp_dir.name, "no_seen.json")
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = cli.main(["notify", "--snapshot", snap_path, "--seen", missing_seen])
        self.assertEqual(code, 0)
        output = json.loads(stdout.getvalue().strip())
        self.assertEqual(len(output["notifications"]), 1)
        self.assertEqual(output["notifications"][0]["event_id"], "receipt-100")

    def test_notify_missing_snapshot_file(self):
        missing_snap = os.path.join(self.temp_dir.name, "no_snap.json")
        seen_path = self._write_file("seen.json", json.dumps({"seen_event_ids": ["receipt-1"]}))
        stdout = io.StringIO()
        with patch("sys.stdout", stdout):
            code = cli.main(["notify", "--snapshot", missing_snap, "--seen", seen_path])
        self.assertEqual(code, 0)
        output = json.loads(stdout.getvalue().strip())
        self.assertEqual(output["notifications"], [])
        self.assertEqual(output["seen_state"]["seen_event_ids"], ["receipt-1"])


class BadArgumentsTests(unittest.TestCase):
    def test_unknown_subcommand_exits_2(self):
        stderr = io.StringIO()
        with patch("sys.stderr", stderr), self.assertRaises(SystemExit) as cm:
            cli.main(["unknown_subcommand"])
        self.assertEqual(cm.exception.code, 2)

    def test_missing_required_snapshot_exits_2(self):
        stderr = io.StringIO()
        with patch("sys.stderr", stderr), self.assertRaises(SystemExit) as cm:
            cli.main(["state", "--now", "2026-09-28T12:00:00Z"])
        self.assertEqual(cm.exception.code, 2)

    def test_missing_required_now_exits_2(self):
        stderr = io.StringIO()
        with patch("sys.stderr", stderr), self.assertRaises(SystemExit) as cm:
            cli.main(["state", "--snapshot", "f.json"])
        self.assertEqual(cm.exception.code, 2)

    def test_now_not_iso8601z_exits_2(self):
        bad_timestamps = [
            "2026-09-28T12:00:00",  # missing Z
            "2026-09-28T12:00:00+00:00",  # offset without Z
            "not-a-timestamp",
            "2026-09-28",
        ]
        for ts in bad_timestamps:
            with self.subTest(ts=ts):
                stderr = io.StringIO()
                with patch("sys.stderr", stderr), self.assertRaises(SystemExit) as cm:
                    cli.main(["state", "--snapshot", "f.json", "--now", ts])
                self.assertEqual(cm.exception.code, 2)

    def test_non_integer_max_age_exits_2(self):
        stderr = io.StringIO()
        with patch("sys.stderr", stderr), self.assertRaises(SystemExit) as cm:
            cli.main(["state", "--snapshot", "f.json", "--now", "2026-09-28T12:00:00Z", "--max-age", "abc"])
        self.assertEqual(cm.exception.code, 2)


_MODULE_PATH = Path(__file__).resolve().parents[1] / "signal_companion_cli.py"
_FORBIDDEN_MODULES = frozenset({"socket", "urllib", "http", "subprocess", "requests"})
_FORBIDDEN_WRITE_METHODS = frozenset({"write", "writelines", "write_text", "write_bytes"})


def _ast_violations(source: str) -> list[str]:
    violations: list[str] = []
    tree = ast.parse(source)

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.split(".")[0] in _FORBIDDEN_MODULES:
                    violations.append(f"import {alias.name}")
        elif isinstance(node, ast.ImportFrom):
            root = (node.module or "").split(".")[0]
            if root in _FORBIDDEN_MODULES:
                violations.append(f"from {node.module} import")

        if isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_WRITE_METHODS:
            violations.append(f"attribute call .{node.attr}()")

        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id == "open":
            encoding_val = None
            for kw in node.keywords:
                if kw.arg == "encoding" and isinstance(kw.value, ast.Constant):
                    encoding_val = kw.value.value
            if encoding_val != "utf-8":
                violations.append("open() call missing encoding='utf-8'")

            mode_val = "r"
            if len(node.args) >= 2 and isinstance(node.args[1], ast.Constant):
                mode_val = node.args[1].value
            for kw in node.keywords:
                if kw.arg == "mode" and isinstance(kw.value, ast.Constant):
                    mode_val = kw.value.value
            if mode_val != "r":
                violations.append(f"open() call uses mode '{mode_val}' instead of 'r'")

    return violations


class PurityAndComplianceTests(unittest.TestCase):
    def test_cli_has_no_forbidden_imports_or_writes(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        self.assertEqual(_ast_violations(source), [])

    def test_ast_checker_flags_missing_encoding(self):
        bad_source = "def f(p):\n    with open(p, 'r') as handle:\n        return handle.read()\n"
        self.assertIn("open() call missing encoding='utf-8'", _ast_violations(bad_source))

    def test_ast_checker_flags_write_method(self):
        for method in ("write", "writelines", "write_text", "write_bytes"):
            with self.subTest(method=method):
                bad_source = f"def f(h, x):\n    h.{method}(x)\n"
                self.assertIn(f"attribute call .{method}()", _ast_violations(bad_source))

    def test_ast_checker_flags_non_read_mode(self):
        bad_source = "def f(p):\n    with open(p, 'w', encoding='utf-8') as handle:\n        pass\n"
        self.assertIn("open() call uses mode 'w' instead of 'r'", _ast_violations(bad_source))


if __name__ == "__main__":
    unittest.main()
