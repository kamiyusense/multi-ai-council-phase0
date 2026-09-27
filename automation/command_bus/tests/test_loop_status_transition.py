from __future__ import annotations

import copy
import unittest

from automation.command_bus.loop_status_transition import project_durable_transition
from automation.command_bus.tests.test_loop_owner import EVIDENCE, NOW, next_event, receipt_for, records, target_for
from automation.command_bus.tests.test_loop_status_issue import state


def inputs():
    events, receipt, target, observation = records()
    receipt = {"schema_version": 1, **receipt}
    return {
        "state": state(last_command_id=events[-1]["command_id"], last_receipt_id=events[-1]["source_receipt_id"], expected_target=target),
        "owner_events": events,
        "receipt_ref": events[-1]["source_receipt_ref"],
        "receipt": receipt,
        "target": target,
        "evidence_readbacks": {EVIDENCE: {"schema_version": 1, "kind": "owner-evidence"}},
        "provider_observation_ref": "automation/command_bus/loop_owner_observations/loop-015/000001.json",
        "provider_observation": observation,
        "now": NOW,
        "expected_loop_id": "loop-015",
        "last_durable_progress": "receipt-owner-1 verified",
    }


class LoopStatusTransitionTests(unittest.TestCase):
    def test_valid_active_transition_projects_semiauto(self):
        result = project_durable_transition(**inputs())
        self.assertEqual((result.status, result.projection.display_state), ("VALID", "SEMI_AUTO"))
        self.assertEqual(result.projection.owner, "SEMI_AUTO")

    def test_state_identity_must_match_owner_event(self):
        values = inputs()
        values["state"] = state(last_command_id=values["owner_events"][-1]["command_id"], last_receipt_id="mismatch-receipt", expected_target=values["target"])
        result = project_durable_transition(**values)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIn("last_receipt_id", result.reason)

        values = inputs()
        values["state"] = state(last_command_id="mismatch-command", last_receipt_id=values["owner_events"][-1]["source_receipt_id"], expected_target=values["target"])
        result = project_durable_transition(**values)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIn("last_command_id", result.reason)

    def test_receipt_locator_mismatch_fails_before_projection(self):
        values = inputs()
        values["receipt_ref"] = "automation/command_bus/receipts/other-loop/000001.json"
        result = project_durable_transition(**values)
        self.assertEqual((result.status, result.projection), ("UNKNOWN", None))
        self.assertIn("receipt locator", result.reason)

    def test_active_owner_requires_provider_observation(self):
        values = inputs()
        values["provider_observation_ref"] = None
        values["provider_observation"] = None
        result = project_durable_transition(**values)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIn("provider observation", result.reason)

    def test_provider_observation_locator_mismatch_fails_before_projection(self):
        values = inputs()
        values["provider_observation_ref"] = "automation/command_bus/loop_owner_observations/loop-015/000002.json"
        result = project_durable_transition(**values)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIn("observation locator", result.reason)

    def test_missing_evidence_readback_fails_closed(self):
        values = inputs()
        values["evidence_readbacks"] = None
        result = project_durable_transition(**values)
        self.assertEqual(result.status, "UNKNOWN")

    def test_extra_or_wrong_evidence_readback_fails_closed(self):
        values = inputs()
        values["evidence_readbacks"] = {
            EVIDENCE: {"schema_version": 1},
            "automation/command_bus/evidence/loop-015/extra.json": {"schema_version": 1},
        }
        result = project_durable_transition(**values)
        self.assertEqual(result.status, "UNKNOWN")

    def test_receipt_that_is_safe_but_not_done_projects_blocked(self):
        values = inputs()
        values["receipt"] = {**values["receipt"], "state": "BLOCKED"}
        result = project_durable_transition(**values)
        self.assertEqual((result.status, result.projection.display_state), ("BLOCKED", "BLOCKED"))
        self.assertEqual(result.projection.owner, "NONE")

    def test_complete_state_without_owner_close_fails_closed(self):
        values = inputs()
        values["state"] = state(
            state="COMPLETE",
            last_command_id=values["owner_events"][-1]["command_id"],
            last_receipt_id=values["owner_events"][-1]["source_receipt_id"],
            expected_target=values["target"],
        )
        result = project_durable_transition(**values)
        self.assertEqual((result.status, result.projection.display_state), ("BLOCKED", "BLOCKED"))
        self.assertEqual(result.projection.owner, "NONE")

    def test_verified_terminal_event_projects_idle_without_provider_observation(self):
        values = inputs()
        first = values["owner_events"][0]
        terminal = next_event(first, event_type="TERMINAL")
        receipt = receipt_for(terminal)
        target = target_for(terminal)
        evidence_ref = terminal["evidence_refs"][0]
        values.update(
            owner_events=[first, terminal],
            state=state(
                state="COMPLETE",
                last_command_id=terminal["command_id"],
                last_receipt_id=terminal["source_receipt_id"],
                expected_target=target,
            ),
            receipt_ref=terminal["source_receipt_ref"],
            receipt=receipt,
            target=target,
            evidence_readbacks={evidence_ref: {"schema_version": 1, "kind": "terminal-evidence"}},
            provider_observation_ref=None,
            provider_observation=None,
        )
        result = project_durable_transition(**values)
        self.assertEqual((result.status, result.projection.display_state), ("TERMINAL", "IDLE"))
        self.assertEqual(result.projection.owner, "NONE")

    def test_close_event_with_active_state_is_blocked(self):
        values = inputs()
        first = values["owner_events"][0]
        released = next_event(first, event_type="RELEASE")
        receipt = receipt_for(released)
        target = target_for(released)
        evidence_ref = released["evidence_refs"][0]
        values.update(
            owner_events=[first, released],
            state=state(
                state="RUNNING",
                last_command_id=released["command_id"],
                last_receipt_id=released["source_receipt_id"],
                expected_target=target,
            ),
            receipt_ref=released["source_receipt_ref"],
            receipt=receipt,
            target=target,
            evidence_readbacks={evidence_ref: {"schema_version": 1, "kind": "release-evidence"}},
            provider_observation_ref=None,
            provider_observation=None,
        )
        result = project_durable_transition(**values)
        self.assertEqual((result.status, result.projection.display_state), ("BLOCKED", "BLOCKED"))

    def test_requested_loop_mismatch_is_unknown(self):
        values = inputs()
        values["expected_loop_id"] = "other-loop"
        result = project_durable_transition(**values)
        self.assertEqual(result.status, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
