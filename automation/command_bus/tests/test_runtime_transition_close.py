from __future__ import annotations

import unittest

from automation.command_bus.loop_owner_backend import owner_event_path
from automation.command_bus.tests.test_runtime_transition_publisher import evidence
from automation.command_bus.tests.test_loop_owner import first_event, next_event, receipt_for, target_for
from automation.command_bus.tests.test_loop_status_issue import state


class CloseTransitionTests(unittest.TestCase):
    def setUp(self):
        from automation.command_bus.tests.test_runtime_transition_publisher import RuntimeTransitionPublisherTests
        self.fixture_class = RuntimeTransitionPublisherTests
        fixture = RuntimeTransitionPublisherTests()
        fixture.setUp()
        self.__dict__.update(fixture.__dict__)
        first = first_event()
        close = next_event(first, event_type="TERMINAL")
        self.client.put(owner_event_path(first["loop_id"], 1), first)
        self.event = close
        self.target.value = target_for(close)
        self.prior = state(
            state="RUNNING", last_command_id=first["command_id"],
            last_receipt_id=first["source_receipt_id"], expected_target=target_for(first),
        )
        self.desired = state(
            state="COMPLETE", last_command_id=close["command_id"],
            last_receipt_id=close["source_receipt_id"], expected_target=target_for(close),
        )
        self.evidence = evidence(close)
        self.evidence["evidence_id"] = "owner-2"
        self.evidence["provider_state"] = "COMPLETE"
        self.evidence["provider_readback"] = None
        self.observation = None
        self.client.put("automation/command_bus/state/loop-015.json", self.prior)
        self.client.put(close["source_receipt_ref"], receipt_for(close))

    def publisher(self, **kwargs):
        return self.fixture_class.publisher(self, **kwargs)

    def request(self):
        return self.fixture_class.request(self)

    def test_terminal_prepares_idle_without_provider_observation(self):
        result = self.publisher().publish(self.request())
        self.assertEqual((result.status, result.status_plan.display_state), ("READY", "IDLE"), result)
        self.assertEqual((self.client.creates, self.client.updates), (2, 1))
        self.assertEqual(self.publisher().publish(self.request()).status, "READY")
        self.assertEqual((self.client.creates, self.client.updates), (2, 1))


if __name__ == "__main__":
    unittest.main()
