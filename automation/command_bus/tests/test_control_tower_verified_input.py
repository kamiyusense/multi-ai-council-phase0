from __future__ import annotations

import copy
import unittest

from automation.command_bus.control_tower_verified_input import (
    control_tower_input_from_transition,
)
from automation.command_bus.loop_status_transition import (
    TransitionProjectionResult,
    project_durable_transition,
)
from automation.command_bus.tests.test_loop_status_transition import inputs


class ControlTowerVerifiedInputTests(unittest.TestCase):
    def test_valid_transition_becomes_control_tower_input(self):
        result = project_durable_transition(**inputs())
        lane = control_tower_input_from_transition(
            result,
            target_ref="pr:4",
            durable_event_kind="RECEIPT",
        )
        self.assertIsNotNone(lane)
        self.assertEqual(lane.projection, result.projection)
        self.assertEqual(lane.generation, result.owner_decision.generation)
        self.assertEqual(lane.target_ref, "pr:4")
        self.assertEqual(lane.last_event_kind, "RECEIPT")
        self.assertEqual(lane.last_event_id, result.event_id)

    def test_terminal_and_blocked_verified_results_remain_their_existing_projection(self):
        values = inputs()
        values["receipt"] = {**values["receipt"], "state": "BLOCKED"}
        blocked = project_durable_transition(**values)
        self.assertEqual(blocked.status, "BLOCKED")
        lane = control_tower_input_from_transition(
            blocked,
            target_ref="pr:4",
            durable_event_kind="HUMAN_NEEDED",
        )
        self.assertEqual(lane.projection.display_state, "BLOCKED")

    def test_unknown_transition_is_not_promoted_to_presentation_state(self):
        values = inputs()
        values["evidence_readbacks"] = None
        result = project_durable_transition(**values)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIsNone(
            control_tower_input_from_transition(result, target_ref="pr:4")
        )

    def test_accepted_result_requires_existing_projection_and_owner_decision(self):
        result = TransitionProjectionResult(
            "VALID",
            "malformed",
            None,
            None,
            "event-1",
        )
        with self.assertRaises(ValueError):
            control_tower_input_from_transition(result, target_ref="pr:4")

        valid = project_durable_transition(**inputs())
        malformed = TransitionProjectionResult(
            valid.status,
            valid.reason,
            valid.projection,
            None,
            valid.event_id,
        )
        with self.assertRaises(ValueError):
            control_tower_input_from_transition(malformed, target_ref="pr:4")

    def test_generation_comes_from_owner_decision_not_caller(self):
        result = project_durable_transition(**inputs())
        lane = control_tower_input_from_transition(result, target_ref="pr:4")
        self.assertEqual(lane.generation, result.owner_decision.generation)
        self.assertFalse(hasattr(lane, "caller_generation"))

    def test_private_or_unbounded_target_ref_is_rejected(self):
        result = project_durable_transition(**inputs())
        for target in (
            "https://github.com/private",
            "chat:https://private.example",
            "../bad",
            "pr:0",
        ):
            with self.subTest(target=target), self.assertRaises(ValueError):
                control_tower_input_from_transition(result, target_ref=target)

    def test_event_kind_is_bounded_but_not_inferred(self):
        result = project_durable_transition(**inputs())
        lane = control_tower_input_from_transition(result, target_ref="pr:4")
        self.assertIsNone(lane.last_event_kind)

        with self.assertRaises(ValueError):
            control_tower_input_from_transition(
                result,
                target_ref="pr:4",
                durable_event_kind="turn complete",
            )

    def test_input_does_not_mutate_transition_result(self):
        result = project_durable_transition(**inputs())
        before = copy.deepcopy(result)
        control_tower_input_from_transition(
            result,
            target_ref="pr:4",
            durable_event_kind="RECEIPT",
        )
        self.assertEqual(result, before)


if __name__ == "__main__":
    unittest.main()
