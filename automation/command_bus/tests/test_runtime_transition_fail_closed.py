from __future__ import annotations

import copy
import unittest

from automation.command_bus.runtime_transition_coordinator import TransitionRequest
from automation.command_bus.tests.test_runtime_transition_publisher import RuntimeTransitionPublisherTests


class FailClosedTests(RuntimeTransitionPublisherTests):
    def test_expired_owner_and_provider_never_write(self):
        self.event["expires_at"] = "2026-09-27T09:59:00+00:00"
        result = self.publisher().publish(self.request())
        self.assertEqual((result.status, result.stage), ("UNKNOWN", "preflight_projection"))
        self.assertEqual((self.client.creates, self.client.updates), (0, 0))

        self.event["expires_at"] = "2026-09-27T11:00:00+00:00"
        self.observation["expires_at"] = "2026-09-27T09:59:00+00:00"
        result = self.publisher().publish(self.request())
        self.assertEqual((result.status, result.stage), ("UNKNOWN", "preflight_projection"))
        self.assertEqual((self.client.creates, self.client.updates), (0, 0))

    def test_fencing_mismatch_and_wrong_generation_never_write(self):
        self.event["fencing_token"] = 2
        self.assertEqual(self.publisher().publish(self.request()).status, "UNKNOWN")
        self.event["fencing_token"] = 1
        self.event["generation"] = 2
        self.assertEqual(self.publisher().publish(self.request()).status, "UNKNOWN")
        self.assertEqual((self.client.creates, self.client.updates), (0, 0))

    def test_competing_authority_and_bad_provider_proof_never_write(self):
        class WrongAuthority:
            def authorize(self, event, prior_state, target, receipt, chain):
                return None

        publisher = self.publisher()
        publisher.owner_authority = WrongAuthority()
        self.assertEqual(publisher.publish(self.request()).status, "NOT_WIRED")

        class WrongProof:
            def verify(self, candidate, evidence, receipt):
                return None

        publisher = self.publisher()
        publisher.provider_verifier = WrongProof()
        self.assertEqual(publisher.publish(self.request()).status, "NOT_WIRED")
        self.assertEqual((self.client.creates, self.client.updates), (0, 0))

    def test_durable_state_cannot_advance_without_owner_event(self):
        self.client.put("automation/command_bus/state/loop-015.json", self.desired)
        result = self.publisher().publish(self.request())
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual((self.client.creates, self.client.updates), (0, 0))


if __name__ == "__main__":
    unittest.main()
