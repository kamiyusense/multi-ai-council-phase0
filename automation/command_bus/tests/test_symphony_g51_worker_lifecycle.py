"""G5.1 static receiver/restart proof. No provider or Git result adoption."""
import json
import unittest
from pathlib import Path

from automation.command_bus.symphony_production_observer import SymphonyProductionObserver
from automation.command_bus.tests import test_symphony_production_observer as fixtures


class SymphonyG51WorkerLifecycleTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SymphonyProductionObserverTests()
        self.fixture.setUp()
        self.observer = self.fixture.observer

    def test_tracker_stop_is_durable_unknown_not_task_success(self):
        start = self.observer.capture_line(self.fixture.event("STARTED"))
        stop = self.observer.capture_line(self.fixture.event("TERMINAL", status="WORKER_STOPPED"))
        self.assertEqual(stop.status, "ACCEPTED")
        terminal = self.fixture.store.restore("g5-proof", start.attempt_id).terminal
        self.assertEqual((terminal["outcome"], terminal["unknown_class"]),
                         ("UNKNOWN", "RECOVERABLE_UNKNOWN"))
        self.assertIsNone(terminal["model_started"])
        self.assertEqual(terminal["evidence_refs"][1], "sym-g5-status:WORKER_STOPPED")

    def test_observer_only_restart_replays_both_without_writes_or_dispatch(self):
        events = [self.fixture.event("STARTED"),
                  self.fixture.event("TERMINAL", status="WORKER_STOPPED")]
        self.assertEqual([self.observer.capture_line(event).status for event in events],
                         ["ACCEPTED", "ACCEPTED"])
        writes = self.fixture.client.create_calls
        fresh = self.fixture.fresh()
        self.assertEqual([fresh.capture_line(event).status for event in events],
                         ["NOOP_DUPLICATE", "NOOP_DUPLICATE"])
        self.assertEqual(self.fixture.client.create_calls, writes)
        self.assertEqual(len(self.fixture.store.list_campaign("g5-proof")), 1)
        self.assertFalse(hasattr(fresh, "dispatch"))

    def test_conflicting_end_and_wrong_identity_cannot_overwrite(self):
        start = self.observer.capture_line(self.fixture.event("STARTED"))
        self.observer.capture_line(self.fixture.event("TERMINAL", status="WORKER_STOPPED"))
        before = self.fixture.store.restore("g5-proof", start.attempt_id).terminal
        writes = self.fixture.client.create_calls
        # Same derived attempt number, different full worker identity.
        wrong_run = self.fixture.run_id[:-1] + "0"
        for event in [
            self.fixture.event("TERMINAL", status="WORKER_COMPLETED"),
            self.fixture.event("TERMINAL", status="WORKER_STOPPED", worker_run_id=wrong_run),
            self.fixture.event("TERMINAL", status="WORKER_STOPPED", workspace="/wrong/workspace"),
        ]:
            self.assertEqual(self.observer.capture_line(event).status, "CONFLICT")
        self.assertEqual(self.fixture.client.create_calls, writes)
        self.assertEqual(self.fixture.store.restore("g5-proof", start.attempt_id).terminal, before)

    def test_stopped_requires_started_and_cannot_be_a_running_start(self):
        self.assertEqual(self.observer.capture_line(
            self.fixture.event("TERMINAL", status="WORKER_STOPPED")).status, "CONFLICT")
        self.assertEqual(self.observer.capture_line(
            self.fixture.event("STARTED", status="WORKER_STOPPED")).status, "CONFLICT")
        self.assertEqual(self.fixture.client.create_calls, 0)

    def test_actual_elixir_otp_fixture_signed_events_cross_language_restart(self):
        path = Path(__file__).parent / "fixtures/symphony_g51/otp-signed-events.jsonl"
        events = path.read_text(encoding="utf-8").splitlines(keepends=True)
        self.assertEqual(len(events), 2)
        payloads = [json.loads(json.loads(event)["payload_json"]) for event in events]
        self.assertEqual([payload["kind"] for payload in payloads], ["STARTED", "TERMINAL"])
        self.assertEqual(payloads[1]["status"], "WORKER_STOPPED")
        self.assertEqual(payloads[0]["worker_run_id"], payloads[1]["worker_run_id"])
        self.assertEqual(payloads[0]["workspace"], payloads[1]["workspace"])
        def fresh():
            return SymphonyProductionObserver(self.fixture.store, campaign_id="g51-otp-static",
                issues={"g51-static": self.fixture.binding}, key=b"f" * 32)
        reader = fresh()
        accepted = [reader.capture_line(event) for event in events]
        self.assertEqual([result.status for result in accepted], ["ACCEPTED", "ACCEPTED"])
        writes = self.fixture.client.create_calls
        restarted = fresh()
        self.assertEqual([restarted.capture_line(event).status for event in events],
                         ["NOOP_DUPLICATE", "NOOP_DUPLICATE"])
        self.assertEqual(self.fixture.client.create_calls, writes)
        self.assertEqual(len(self.fixture.store.list_campaign("g51-otp-static")), 1)
        self.assertEqual(self.fixture.store.restore("g51-otp-static", accepted[0].attempt_id).terminal["outcome"], "UNKNOWN")
        self.assertFalse(hasattr(restarted, "dispatch"))


if __name__ == "__main__":
    unittest.main()
