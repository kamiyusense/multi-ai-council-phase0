from __future__ import annotations

import json
import unittest
from pathlib import Path

from automation.command_bus.control_tower_registration import (
    assess_registration_readiness,
)
from automation.command_bus.loop_owner import OwnerDecision
from automation.command_bus.loop_status_issue import StatusProjection
from automation.command_bus.loop_status_transition import TransitionProjectionResult


ROOT = Path(__file__).parents[1]
REGISTRY_PATH = ROOT / "config" / "control_tower_registry.json"


def registry():
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def one_lane_registry(loop_id="loop-015", *, identity_state="DURABLE"):
    return {
        "schema_version": 1,
        "loops": [
            {
                "loop_id": loop_id,
                "display_name": "Loop 015",
                "mode": "SEMI_AUTO",
                "controller_kind": "CHATGPT",
                "worker_kind": "JULES",
                "display_order": 10,
                "enabled": True,
                "safe_detail_ref": "issue:33",
                "identity_state": identity_state,
            }
        ],
    }


def verified_result(loop_id, *, status="VALID", display_state="SEMI_AUTO"):
    return TransitionProjectionResult(
        status=status,
        reason="fixture durable transition verified",
        projection=StatusProjection(
            display_state=display_state,
            source_state="RUNNING" if display_state in {"SEMI_AUTO", "AUTO"} else "BLOCKED",
            owner="SEMI_AUTO" if display_state == "SEMI_AUTO" else ("AUTO" if display_state == "AUTO" else "NONE"),
            loop_id=loop_id,
            round=1,
            max_rounds=6,
            provider_state="RUNNING",
            last_durable_progress="fixture",
            expires_at="2026-09-28T05:00:00+00:00",
            human_action="NONE" if display_state in {"SEMI_AUTO", "AUTO"} else "REVIEW REQUIRED",
            reason="fixture",
        ),
        owner_decision=OwnerDecision(
            status="VALID",
            owner="SEMI_AUTO" if display_state == "SEMI_AUTO" else ("AUTO" if display_state == "AUTO" else "NONE"),
            generation=1,
            fencing_token=1,
            reason="fixture",
        ),
        event_id=f"event-{loop_id}",
    )


class ControlTowerRegistrationReadinessTests(unittest.TestCase):
    def test_repository_registry_placeholders_are_not_wired(self):
        result = assess_registration_readiness(registry(), None)
        self.assertEqual(result.status, "NOT_WIRED")
        self.assertEqual(result.ready_loop_ids, ())
        self.assertEqual(result.missing_loop_ids, ())
        self.assertEqual(
            result.placeholder_loop_ids,
            (
                "chatgpt-semi-auto",
                "claude-gemini",
                "claude-claude",
                "work-gemini",
            ),
        )
        self.assertIn("PLACEHOLDER", result.reason)


    def test_placeholder_identity_never_becomes_ready_even_with_matching_transition(self):
        raw = one_lane_registry("loop-015", identity_state="PLACEHOLDER")
        result = assess_registration_readiness(
            raw,
            {"loop-015": verified_result("loop-015")},
        )
        self.assertEqual(result.status, "NOT_WIRED")
        self.assertEqual(result.ready_loop_ids, ())
        self.assertEqual(result.placeholder_loop_ids, ("loop-015",))
        self.assertIn("PLACEHOLDER", result.reason)

    def test_registry_id_by_itself_never_counts_as_ready(self):
        raw = one_lane_registry("loop-015")
        result = assess_registration_readiness(raw, {})
        self.assertEqual(result.status, "NOT_WIRED")
        self.assertEqual(result.missing_loop_ids, ("loop-015",))

    def test_matching_existing_transition_projection_is_ready(self):
        raw = one_lane_registry("loop-015")
        result = assess_registration_readiness(
            raw,
            {"loop-015": verified_result("loop-015")},
        )
        self.assertEqual(result.status, "READY")
        self.assertEqual(result.ready_loop_ids, ("loop-015",))
        self.assertEqual(result.missing_loop_ids, ())
        self.assertEqual(result.unknown_loop_ids, ())

    def test_unknown_transition_is_not_promoted_to_ready(self):
        raw = one_lane_registry("loop-015")
        unknown = TransitionProjectionResult(
            "UNKNOWN",
            "missing durable evidence",
            None,
            None,
            None,
        )
        result = assess_registration_readiness(raw, {"loop-015": unknown})
        self.assertEqual(result.status, "NOT_WIRED")
        self.assertEqual(result.unknown_loop_ids, ("loop-015",))
        self.assertEqual(result.ready_loop_ids, ())

    def test_projection_loop_identity_mismatch_blocks(self):
        raw = one_lane_registry("loop-015")
        result = assess_registration_readiness(
            raw,
            {"loop-015": verified_result("different-loop")},
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("loop_id mismatch", result.reason)

    def test_non_transition_object_blocks(self):
        raw = one_lane_registry("loop-015")
        result = assess_registration_readiness(raw, {"loop-015": object()})
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("TransitionProjectionResult", result.reason)

    def test_incomplete_accepted_transition_blocks(self):
        raw = one_lane_registry("loop-015")
        malformed = TransitionProjectionResult(
            "VALID",
            "malformed",
            None,
            None,
            "event-1",
        )
        result = assess_registration_readiness(raw, {"loop-015": malformed})
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("incomplete", result.reason)

    def test_disabled_registry_lane_does_not_require_durable_transition(self):
        raw = one_lane_registry("loop-015")
        raw["loops"][0]["enabled"] = False
        result = assess_registration_readiness(raw, {})
        self.assertEqual(result.status, "READY")
        self.assertEqual(result.ready_loop_ids, ())

    def test_unregistered_verified_transition_does_not_make_missing_lane_ready(self):
        raw = one_lane_registry("loop-015")
        result = assess_registration_readiness(
            raw,
            {"other-loop": verified_result("other-loop")},
        )
        self.assertEqual(result.status, "NOT_WIRED")
        self.assertEqual(result.missing_loop_ids, ("loop-015",))
        self.assertIn("unregistered verified transitions ignored=other-loop", result.reason)

    def test_multiple_lanes_require_all_enabled_durable_identities(self):
        raw = {
            "schema_version": 1,
            "loops": [
                {
                    "loop_id": "loop-a",
                    "display_name": "Loop A",
                    "mode": "SEMI_AUTO",
                    "controller_kind": "CHATGPT",
                    "worker_kind": "JULES",
                    "display_order": 10,
                    "enabled": True,
                    "safe_detail_ref": "issue:33",
                    "identity_state": "DURABLE",
                },
                {
                    "loop_id": "loop-b",
                    "display_name": "Loop B",
                    "mode": "AUTO",
                    "controller_kind": "CLAUDE",
                    "worker_kind": "GEMINI",
                    "display_order": 20,
                    "enabled": True,
                    "safe_detail_ref": "issue:33",
                },
            ],
        }
        result = assess_registration_readiness(
            raw,
            {"loop-a": verified_result("loop-a")},
        )
        self.assertEqual(result.status, "NOT_WIRED")
        self.assertEqual(result.ready_loop_ids, ("loop-a",))
        self.assertEqual(result.missing_loop_ids, ("loop-b",))

        result = assess_registration_readiness(
            raw,
            {
                "loop-a": verified_result("loop-a"),
                "loop-b": verified_result("loop-b", display_state="AUTO"),
            },
        )
        self.assertEqual(result.status, "READY")
        self.assertEqual(result.ready_loop_ids, ("loop-a", "loop-b"))


if __name__ == "__main__":
    unittest.main()
