from __future__ import annotations

import copy
import unittest

from automation.command_bus.runtime_takeover_prepare import prepare_takeover_transition
from automation.command_bus.tests.test_loop_status_issue import state
from automation.command_bus.tests.test_runtime_takeover import (
    NOW,
    authority_for,
    current_state,
    proposed,
    provider_for,
)
from automation.command_bus.tests.test_loop_owner import (
    first_event,
    observation_for,
    receipt_for,
    target_for,
)


def evidence_for(event):
    return {
        "schema_version": 1,
        "evidence_id": f"owner-{event['generation']}",
        "loop_id": event["loop_id"],
        "generation": event["generation"],
        "command_id": event["command_id"],
        "correlation_id": event["correlation_id"],
        "expected_repo": event["expected_repo"],
        "expected_pr": event["expected_pr"],
        "expected_target_head": event["expected_target_head"],
        "source_receipt_ref": event["source_receipt_ref"],
        "provider_kind": "JULES",
        "provider_state": "RUNNING",
        "observed_at": "2026-09-27T11:00:30+00:00",
        "external_refs": [],
        "test_results": [],
        "provider_readback": f"provider:takeover-{event['generation']}",
        "publication_evidence": None,
    }


def desired_state_for(event):
    return state(
        state="RUNNING",
        stop_requested=False,
        last_command_id=event["command_id"],
        last_receipt_id=event["source_receipt_id"],
        expected_target=target_for(event),
    )


def provider_input_for(event):
    value = copy.deepcopy(provider_for(event).observation)
    value.pop("verified")
    return value


def bundle(**changes):
    first = changes.pop("first", first_event())
    handoff = changes.pop("proposed_event", proposed(first))
    values = {
        "state": current_state(first),
        "owner_events": [first],
        "current_receipt": receipt_for(first),
        "current_evidence_refs": set(first["evidence_refs"]),
        "current_provider_observation": observation_for(first),
        "target": target_for(first),
        "proposed_event": handoff,
        "proposed_receipt": receipt_for(handoff),
        "authorized_owner": authority_for(handoff),
        "verified_provider": provider_for(handoff),
        "evidence_document": evidence_for(handoff),
        "provider_observation_input": provider_input_for(handoff),
        "desired_state": desired_state_for(handoff),
        "now": NOW,
    }
    values.update(changes)
    return values


class RuntimeTakeoverPrepareTests(unittest.TestCase):
    def test_ready_preflight_builds_publisher_request(self):
        values = bundle()
        result = prepare_takeover_transition(**values)
        self.assertEqual((result.status, result.stage), ("READY", "complete"), result)
        self.assertIsNotNone(result.plan)
        self.assertIsNotNone(result.request)
        self.assertEqual(result.request.owner_event, values["proposed_event"])
        self.assertEqual(result.request.evidence_document, values["evidence_document"])
        self.assertEqual(
            result.request.provider_observation_input,
            values["provider_observation_input"],
        )
        self.assertEqual(result.request.expected_prior_state, values["state"])
        self.assertEqual(result.request.desired_state, values["desired_state"])

    def test_preflight_failure_is_preserved_and_no_request_is_created(self):
        values = bundle(now="2026-09-27T10:59:59+00:00")
        result = prepare_takeover_transition(**values)
        self.assertEqual((result.status, result.stage), ("BLOCKED", "preflight:expiry"))
        self.assertIsNone(result.request)
        self.assertIsNone(result.plan)

    def test_missing_authority_or_provider_remains_not_wired(self):
        for field in ("authorized_owner", "verified_provider"):
            values = bundle(**{field: None})
            result = prepare_takeover_transition(**values)
            self.assertEqual(result.status, "NOT_WIRED", result)
            self.assertTrue(result.stage.startswith("preflight:"))
            self.assertIsNone(result.request)

    def test_evidence_must_bind_exact_handoff_and_provider_proof(self):
        base = bundle()

        bad = copy.deepcopy(base["evidence_document"])
        bad["expected_target_head"] = "b" * 40
        result = prepare_takeover_transition(**{**base, "evidence_document": bad})
        self.assertEqual((result.status, result.stage), ("BLOCKED", "evidence"))

        bad = copy.deepcopy(base["evidence_document"])
        bad["provider_state"] = "FAILED"
        result = prepare_takeover_transition(**{**base, "evidence_document": bad})
        self.assertEqual((result.status, result.stage), ("BLOCKED", "evidence"))

        bad = copy.deepcopy(base["evidence_document"])
        bad["provider_readback"] = "provider:wrong"
        result = prepare_takeover_transition(**{**base, "evidence_document": bad})
        self.assertEqual((result.status, result.stage), ("BLOCKED", "evidence"))

    def test_event_evidence_ref_must_be_exactly_canonical_document(self):
        values = bundle()
        event = copy.deepcopy(values["proposed_event"])
        event["evidence_refs"] = [
            "automation/command_bus/evidence/loop-015/other.json"
        ]
        receipt = receipt_for(event)
        authority = authority_for(event)
        provider = provider_for(event)
        provider_input = copy.deepcopy(provider.observation)
        provider_input.pop("verified")
        result = prepare_takeover_transition(
            **{
                **values,
                "proposed_event": event,
                "proposed_receipt": receipt,
                "authorized_owner": authority,
                "verified_provider": provider,
                "provider_observation_input": provider_input,
            }
        )
        self.assertEqual((result.status, result.stage), ("BLOCKED", "evidence"))

    def test_caller_cannot_supply_verified_provider_input(self):
        values = bundle()
        bad = copy.deepcopy(values["provider_observation_input"])
        bad["verified"] = True
        result = prepare_takeover_transition(
            **{**values, "provider_observation_input": bad}
        )
        self.assertEqual((result.status, result.stage), ("BLOCKED", "provider_input"))

    def test_provider_input_must_match_independent_proof(self):
        values = bundle()
        bad = copy.deepcopy(values["provider_observation_input"])
        bad["holder_id"] = "different-holder"
        result = prepare_takeover_transition(
            **{**values, "provider_observation_input": bad}
        )
        self.assertEqual((result.status, result.stage), ("BLOCKED", "provider_input"))

    def test_desired_state_must_bind_takeover_generation_and_remain_active(self):
        values = bundle()

        bad = copy.deepcopy(values["desired_state"])
        bad["last_command_id"] = "other-command"
        result = prepare_takeover_transition(**{**values, "desired_state": bad})
        self.assertEqual((result.status, result.stage), ("BLOCKED", "desired_state"))

        bad = copy.deepcopy(values["desired_state"])
        bad["last_receipt_id"] = "other-receipt"
        result = prepare_takeover_transition(**{**values, "desired_state": bad})
        self.assertEqual((result.status, result.stage), ("BLOCKED", "desired_state"))

        bad = copy.deepcopy(values["desired_state"])
        bad["expected_target"] = {**bad["expected_target"], "head": "b" * 40}
        result = prepare_takeover_transition(**{**values, "desired_state": bad})
        self.assertEqual((result.status, result.stage), ("BLOCKED", "desired_state"))

        bad = copy.deepcopy(values["desired_state"])
        bad["state"] = "COMPLETE"
        result = prepare_takeover_transition(**{**values, "desired_state": bad})
        self.assertEqual((result.status, result.stage), ("BLOCKED", "desired_state"))

    def test_prepared_request_is_frozen_against_later_caller_mutation(self):
        values = bundle()
        result = prepare_takeover_transition(**values)
        self.assertEqual(result.status, "READY")
        original_head = result.request.owner_event["expected_target_head"]
        original_target = copy.deepcopy(result.request.desired_state["expected_target"])

        values["proposed_event"]["expected_target_head"] = "b" * 40
        values["desired_state"]["expected_target"]["head"] = "c" * 40
        values["provider_observation_input"]["holder_id"] = "changed"

        self.assertEqual(result.request.owner_event["expected_target_head"], original_head)
        self.assertEqual(result.request.desired_state["expected_target"], original_target)
        self.assertNotEqual(
            result.request.provider_observation_input["holder_id"],
            values["provider_observation_input"]["holder_id"],
        )


if __name__ == "__main__":
    unittest.main()
