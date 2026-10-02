import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from automation.command_bus.blue_work_reconcile_cli import replay_snapshot
from .test_blue_work_reconcile_prepare import FIXTURE


class BlueOfflineCLITests(unittest.TestCase):
    def run_cli(self, *args):
        return subprocess.run([sys.executable, "-m", "automation.command_bus.blue_work_reconcile_cli", *map(str, args)],
                              capture_output=True, text=True, timeout=10)

    def test_replay_create_only_artifact_and_refuse_overwrite(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "candidate.json"
            result = self.run_cli(FIXTURE, "--now", "2026-10-01T12:00:00Z", "--output", output)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            original = output.read_bytes()
            data = json.loads(original)
            self.assertEqual(data["plan"]["status"], "PREPARED")
            self.assertIs(data["external_send_attempted"], False)
            self.assertEqual(data["lineage_authentication"], "NOT_WIRED")
            second = self.run_cli(FIXTURE, "--now", "2026-10-01T12:00:00Z", "--output", output)
            self.assertEqual(second.returncode, 2)
            self.assertEqual(original, output.read_bytes())

    def test_naive_clock_and_malformed_snapshot_are_unknown(self):
        self.assertEqual(self.run_cli(FIXTURE, "--now", "2026-10-01T12:00:00").returncode, 2)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "invalid.json"
            for raw in ('{"x":1,"x":2}', '[]', '{broken'):
                path.write_text(raw)
                r = self.run_cli(path, "--now", "2026-10-01T12:00:00Z")
                self.assertEqual(r.returncode, 2, r.stdout + r.stderr)

    def test_no_live_mode_can_be_requested(self):
        result = self.run_cli(FIXTURE, "--now", "2026-10-01T12:00:00Z", "--send")
        self.assertEqual(result.returncode, 2)
        self.assertIn("unrecognized arguments", result.stderr)

    def test_unknown_input_does_not_claim_prepared(self):
        from datetime import datetime, timezone
        result = replay_snapshot({}, datetime(2026, 10, 1, 12, tzinfo=timezone.utc))
        self.assertEqual(result["plan"]["status"], "UNKNOWN")
        self.assertIs(result["model_executed"], False)


if __name__ == "__main__":
    unittest.main()
