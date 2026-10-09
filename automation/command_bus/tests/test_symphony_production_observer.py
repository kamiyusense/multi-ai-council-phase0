"""G5 signed upstream observation and durable restart fixtures; no model work."""
import hashlib
import hmac
import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import patch

from automation.command_bus.symphony_attempt_store import GitHubAutonomousAttemptStore
from automation.command_bus.symphony_g5_observer_cli import observe_file
from automation.command_bus.symphony_production_observer import (
    PROTOCOL, ObservedIssue, SymphonyProductionObserver,
)
from automation.command_bus.symphony_result_adoption import AdoptionAction, decide_result_adoption
from automation.command_bus.tests.test_symphony_attempt_store import FakeAttemptContents


class SymphonyProductionObserverTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeAttemptContents()
        self.store = GitHubAutonomousAttemptStore(self.client, write_branch="feature/g5-records")
        self.key = b"g5-fixture-only-signing-key-32-bytes-long"
        self.binding = ObservedIssue("task-336", 1, "a" * 40, 1, {"issue": "336"})
        self.observer = self.fresh()
        self.run_id = "0123456789abcdef0123456789abcdef"

    def fresh(self):
        return SymphonyProductionObserver(
            self.store, campaign_id="g5-proof", issues={"336": self.binding}, key=self.key,
        )

    def event(self, kind, *, status=None, **changes):
        payload = dict(protocol=PROTOCOL, issue_id="336",
                       attempt_number=int(self.run_id[:15], 16) + 1,
                       worker_run_id=self.run_id, kind=kind,
                       workspace="/isolated/GH-336",
                       status=status or ("RUNNING" if kind == "STARTED" else "WORKER_COMPLETED"))
        payload.update(changes)
        body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
        mac = hmac.new(self.key, body.encode(), hashlib.sha256).hexdigest()
        return json.dumps({"payload_json": body, "mac": mac}) + "\n"

    def test_started_crash_restore_no_duplicate_dispatch(self):
        first = self.observer.capture_line(self.event("STARTED"))
        self.assertEqual(first.status, "ACCEPTED")
        snapshot = self.store.restore("g5-proof", first.attempt_id)
        self.assertEqual(snapshot.state, "STARTED_UNRESOLVED")
        self.assertEqual(snapshot.started["observation_source"], "LIVE_OBSERVATION")
        writes = self.client.create_calls
        self.assertEqual(self.fresh().capture_line(self.event("STARTED")).status, "NOOP_DUPLICATE")
        self.assertEqual(self.client.create_calls, writes)
        self.assertFalse(hasattr(self.fresh(), "dispatch"))

    def test_terminal_crash_before_checkpoint_reconciles_without_restarting_worker(self):
        start = self.observer.capture_line(self.event("STARTED"))
        terminal = self.observer.capture_line(self.event("TERMINAL"))
        self.assertEqual(terminal.status, "ACCEPTED")
        writes = self.client.create_calls
        fresh = self.fresh()
        self.assertEqual(fresh.capture_line(self.event("STARTED")).status, "NOOP_DUPLICATE")
        self.assertEqual(fresh.capture_line(self.event("TERMINAL")).status, "NOOP_DUPLICATE")
        snapshot = self.store.restore("g5-proof", start.attempt_id)
        self.assertEqual(snapshot.state, "TERMINAL")
        self.assertEqual(snapshot.terminal["outcome"], "UNKNOWN")
        self.assertEqual(snapshot.terminal["unknown_class"], "RECOVERABLE_UNKNOWN")
        self.assertIsNone(snapshot.terminal["model_started"])
        self.assertEqual(snapshot.terminal["evidence_refs"][1], "sym-g5-status:WORKER_COMPLETED")
        self.assertEqual(self.client.create_calls, writes)

    def test_conflicting_terminal_and_worker_identity_never_overwrite(self):
        start = self.observer.capture_line(self.event("STARTED"))
        self.assertEqual(self.observer.capture_line(self.event("TERMINAL")).status, "ACCEPTED")
        writes = self.client.create_calls
        self.assertEqual(self.observer.capture_line(
            self.event("TERMINAL", status="WORKER_FAILED"),
        ).status, "CONFLICT")
        self.assertEqual(self.observer.capture_line(
            self.event("STARTED", workspace="/other/GH-336"),
        ).status, "CONFLICT")
        self.assertEqual(self.store.restore("g5-proof", start.attempt_id).state, "TERMINAL")
        self.assertEqual(self.client.create_calls, writes)

    def test_retry_stall_and_status_are_read_only(self):
        for kind in ("WORKER_UPDATE", "RETRY_SCHEDULED", "STALLED", "STATUS_AVAILABLE"):
            with self.subTest(kind=kind):
                result = self.observer.capture_line(self.event(kind))
                self.assertEqual(result.status, "READ_ONLY")
        self.assertEqual(self.client.create_calls, 0)

    def test_bad_mac_unbound_issue_and_attempt_number_are_rejected(self):
        valid = json.loads(self.event("STARTED"))
        valid["mac"] = "0" * 64
        self.assertEqual(self.observer.capture_line(json.dumps(valid)).status, "CONFLICT")
        self.assertEqual(self.observer.capture_line(self.event("STARTED", issue_id="999")).status, "CONFLICT")
        self.assertEqual(self.observer.capture_line(self.event("STARTED", attempt_number=1)).status, "CONFLICT")
        self.assertEqual(self.client.create_calls, 0)

    def test_replay_complete_lines_after_reader_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "events.jsonl"
            path.write_text(self.event("STARTED") + self.event("TERMINAL") + '{"partial":', encoding="utf-8")
            self.assertEqual([item.status for item in self.observer.replay_file(str(path))],
                             ["ACCEPTED", "ACCEPTED"])
            self.assertEqual([item.status for item in self.fresh().replay_file(str(path))],
                             ["NOOP_DUPLICATE", "NOOP_DUPLICATE"])

    def test_cli_observer_skips_partial_tail_and_replays_on_restart(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "events.jsonl"
            path.write_text(self.event("STARTED") + '{"partial":', encoding="utf-8")
            with redirect_stdout(io.StringIO()):
                self.assertEqual(observe_file(self.observer, str(path), follow=False), ["ACCEPTED"])
                self.assertEqual(observe_file(self.fresh(), str(path), follow=False), ["NOOP_DUPLICATE"])

    def test_follow_waits_for_producer_to_create_event_file(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "events.jsonl"
            calls = 0

            def wake(_seconds):
                nonlocal calls
                calls += 1
                if calls == 1:
                    path.write_text(self.event("STARTED"), encoding="utf-8")
                else:
                    raise KeyboardInterrupt

            with patch("automation.command_bus.symphony_g5_observer_cli.time.sleep", side_effect=wake):
                with redirect_stdout(io.StringIO()), self.assertRaises(KeyboardInterrupt):
                    observe_file(self.observer, str(path), follow=True, poll_seconds=0)
            self.assertEqual(len(self.store.list_campaign("g5-proof")), 1)
            self.assertEqual(self.store.list_campaign("g5-proof")[0].state, "STARTED_UNRESOLVED")

    def test_stale_head_remains_result_adoption_boundary(self):
        self.assertEqual(self.observer.capture_line(self.event("STARTED")).status, "ACCEPTED")
        self.assertEqual(self.observer.capture_line(self.event("TERMINAL")).status, "ACCEPTED")
        self.assertEqual(decide_result_adoption(
            expected_head="a" * 40, canonical_head="b" * 40,
            canonical_trustworthy=True, task_still_valid=True,
            mutation_operations=(),
        ).action, AdoptionAction.STALE_REPLAN)


if __name__ == "__main__":
    unittest.main()
