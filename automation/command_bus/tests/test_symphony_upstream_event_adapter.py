from dataclasses import replace
import unittest

from automation.command_bus.symphony_upstream_event_adapter import UpstreamWorkerEvent, prepare_worker_recovery
from automation.command_bus.tests.test_symphony_attempt_store import store, intent


class SymphonyUpstreamEventAdapterTests(unittest.TestCase):
    def setUp(self):
        _, self.store = store()
        self.attempt = intent(self.store)
        self.snapshot = self.store.restore("campaign-1", self.attempt.attempt_id)
        self.event = UpstreamWorkerEvent("campaign-1", "task::one", 3, self.attempt.attempt_id,
                                         2, "a" * 40, "STALLED", "static:stall", "STATIC_SIMULATION")

    def test_stall_and_status_observations_never_fence_or_dispatch(self):
        for kind in ("STALLED", "STATUS_AVAILABLE", "TERMINAL_AVAILABLE"):
            value = prepare_worker_recovery(self.snapshot, replace(self.event, event_kind=kind))
            self.assertEqual(value.action, "RECONCILE_READ_ONLY")
            self.assertIsNone(value.fence_proof)
            self.assertFalse(value.dispatch_authorized)

    def test_only_explicit_static_unstarted_stop_or_fence_produces_proof(self):
        for kind in ("STOPPED", "FENCED"):
            value = prepare_worker_recovery(self.snapshot, replace(self.event, event_kind=kind))
            self.assertEqual(value.fence_proof.attempt_id, self.attempt.attempt_id)
            self.assertFalse(value.dispatch_authorized)
            self.assertEqual(value.production_source_authentication, "NOT_WIRED")

    def test_started_attempt_remains_read_only_even_if_worker_is_stopped(self):
        self.store.append_started(campaign_id="campaign-1", attempt_id=self.attempt.attempt_id,
                                  provider_kind="STATIC", provider_attempt_ref="worker",
                                  observation_source="STATIC_SIMULATION")
        snapshot = self.store.restore("campaign-1", self.attempt.attempt_id)
        value = prepare_worker_recovery(snapshot, replace(self.event, event_kind="STOPPED"))
        self.assertEqual(value.action, "RECONCILE_READ_ONLY")
        self.assertIsNone(value.fence_proof)

    def test_unverified_or_production_source_cannot_produce_fence(self):
        for source in ("UNAUTHENTICATED_CAPTURE", "LIVE_OBSERVATION", "VERIFIED", None):
            value = prepare_worker_recovery(self.snapshot, replace(self.event, source_authentication=source, event_kind="FENCED"))
            self.assertIsNone(value.fence_proof)
            self.assertEqual(value.action, "READ_EVIDENCE_ONLY")

    def test_stale_identity_fields_rejected(self):
        for field, value in (("campaign_id", "other"), ("task_id", "other"), ("generation", 4),
                             ("attempt_id", "other"), ("runner_generation", 5), ("expected_target_head", "b" * 40)):
            result = prepare_worker_recovery(self.snapshot, replace(self.event, **{field: value}))
            self.assertEqual(result.action, "REJECT_STALE_EVENT")

    def test_missing_evidence_or_unknown_event_cannot_fence(self):
        self.assertIsNone(prepare_worker_recovery(self.snapshot, replace(self.event, event_kind="FENCED", evidence_ref="")).fence_proof)
        self.assertEqual(prepare_worker_recovery(self.snapshot, replace(self.event, event_kind="LEASE_EXPIRED")).action, "REJECT_UNKNOWN_EVENT")


if __name__ == "__main__":
    unittest.main()
