import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from automation.command_bus.github_readonly import ReadResponse
from automation.command_bus.work_event_prepare_cli import prepare_github_event
from .closed_loop_fixtures import NOW, snapshot


class DeniedReader:
    def __init__(self):
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        raise OSError("mock permission denied")


class EventPrepareTests(unittest.TestCase):
    def test_unrelated_result_is_noop_without_network(self):
        event = snapshot()["wake"]["event"]
        event["pull_request"]["base"]["ref"] = "feature/blue-work-jules-webhook-loop"
        reader = DeniedReader()
        output = prepare_github_event(event, reader, lane="blue", now=NOW)
        self.assertEqual(output["status"], "NO_OP")
        self.assertEqual(reader.calls, [])

    def test_missing_permission_is_unknown_and_single_attempt(self):
        reader = DeniedReader()
        output = prepare_github_event(snapshot()["wake"]["event"], reader, lane="blue", now=NOW)
        self.assertEqual(output["status"], "UNKNOWN")
        self.assertEqual(len(reader.calls), 1)
        self.assertNotIn("mock permission denied", json.dumps(output))
        self.assertIs(output["external_send_attempted"], False)

    def test_missing_direct_jules_reader_never_uses_branch_as_proof(self):
        from .test_cloud_work_snapshot import SnapshotReader
        reader = SnapshotReader()
        with patch("automation.command_bus.work_event_prepare_cli.collect_global_jules_snapshot") as collect, \
             patch("automation.command_bus.work_event_prepare_cli.read_result_source") as source:
            collect.return_value.carrier_head = "a" * 40
            source.return_value = {"request": {"command_id": "mock-source"}}
            output = prepare_github_event(snapshot()["wake"]["event"], reader, lane="blue", now=NOW)
        self.assertEqual(output["status"], "UNKNOWN")
        self.assertNotIn("wake", output)
        self.assertIn("NOT_WIRED", output["reason"])

    def test_delayed_event_stale_before_source_lookup(self):
        from .test_cloud_work_snapshot import SnapshotReader
        reader = SnapshotReader()
        event = snapshot()["wake"]["event"]
        event["pull_request"]["head"]["sha"] = "b" * 40
        output = prepare_github_event(event, reader, lane="blue", now=NOW)
        self.assertEqual(output["status"], "STALE")

    def test_closed_reopened_and_wrong_repo_events_never_send(self):
        for action, status in (("closed", "NO_OP"), ("reopened", "NO_OP")):
            event = snapshot()["wake"]["event"]
            event["action"] = action
            reader = DeniedReader()
            self.assertEqual(prepare_github_event(event, reader, lane="blue", now=NOW)["status"], status)
            self.assertEqual(reader.calls, [])
        event["repository"]["full_name"] = "other/repo"
        self.assertEqual(prepare_github_event(event, reader, lane="blue", now=NOW)["status"], "UNKNOWN")

    def test_cli_mock_cycle_createonly_and_no_send_option(self):
        with tempfile.TemporaryDirectory() as directory:
            path, output = Path(directory) / "input.json", Path(directory) / "output.json"
            path.write_text(json.dumps(snapshot()))
            args = [sys.executable, "-m", "automation.command_bus.work_event_prepare_cli", "--snapshot", str(path),
                    "--now", NOW.isoformat(), "--output", str(output)]
            first = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
            result = json.loads(output.read_text())
            self.assertEqual(result["status"], "PREPARED")
            self.assertEqual(result["source_authentication"], "NOT_WIRED")
            before = output.read_bytes()
            second = subprocess.run(args, capture_output=True, text=True)
            self.assertEqual(second.returncode, 2)
            self.assertEqual(output.read_bytes(), before)
            forbidden = subprocess.run(args + ["--send"], capture_output=True, text=True)
            self.assertEqual(forbidden.returncode, 2)

    def test_cli_duplicate_json_naive_clock_and_invalid_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            path, output = Path(directory) / "input.json", Path(directory) / "output.json"
            path.write_text('{"source_mode":"MOCK","source_mode":"CAPTURED"}')
            args = [sys.executable, "-m", "automation.command_bus.work_event_prepare_cli", "--snapshot", str(path), "--output", str(output)]
            self.assertEqual(subprocess.run(args, capture_output=True).returncode, 2)
            self.assertFalse(output.exists())
            path.write_text(json.dumps(snapshot()))
            self.assertEqual(subprocess.run(args + ["--now", "2026-10-01T12:00:00"], capture_output=True).returncode, 2)


if __name__ == "__main__":
    unittest.main()
