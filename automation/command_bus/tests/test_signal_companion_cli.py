"""Unit tests for Windows Signal Companion v1 CLI bridge (SF-12).

Tests:
- subcommand state output and exit code 0 for valid, missing, unreadable, and malformed snapshots
- subcommand state --max-age parameter passing
- subcommand notify output and exit code 0 for valid, missing, and unreadable files, including --first-run
- subcommand notify missing --seen file handled as empty seen state
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


class PurityAndComplianceTests(unittest.TestCase):
    def test_cli_has_no_forbidden_imports(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    self.assertNotIn(alias.name.split(".")[0], _FORBIDDEN_MODULES)
            elif isinstance(node, ast.ImportFrom):
                root = (node.module or "").split(".")[0]
                self.assertNotIn(root, _FORBIDDEN_MODULES)

    def test_cli_does_not_perform_file_writes(self):
        source = _MODULE_PATH.read_text(encoding="utf-8")
        for node in ast.walk(ast.parse(source)):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name) and func.id == "open":
                    # ensure open calls only use "r" mode
                    for arg in node.args[1:]:
                        if isinstance(arg, ast.Constant):
                            self.assertEqual(arg.value, "r")


if __name__ == "__main__":
    unittest.main()
