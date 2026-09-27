from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from automation.command_bus.loop_owner import decide_owner, project_with_durable_owner
from automation.command_bus.tests.test_loop_status_issue import state


NOW = "2026-09-27T10:00:00+00:00"
HEAD = "a" * 40


def records():
    event = {
        "schema_version": 1, "event_id": "owner-event-1", "event_type": "ACQUIRE",
        "loop_id": "loop-015", "owner_role": "SEMI_AUTO", "holder_id": "controller-1",
        "generation": 1, "fencing_token": 1, "previous_generation": None,
        "claimed_at": "2026-09-27T09:00:00+00:00", "expires_at": "2026-09-27T11:00:00+00:00",
        "expected_repo": "kamiyusense/multi-ai-council-phase0", "expected_pr": 4,
        "expected_target_head": HEAD, "command_id": "cmd-015", "correlation_id": "corr-015",
        "source_receipt_id": "receipt-owner-1", "evidence_refs": ["evidence-owner-1"],
    }
    receipt = {"receipt_id": "receipt-owner-1", "loop_id": "loop-015", "command_id": "cmd-015", "correlation_id": "corr-015", "state": "DONE", "executed_once": True, "retry_count": 0, "fallback_used": False, "evidence_refs": ["evidence-owner-1"]}
    target = {"repo": event["expected_repo"], "pr": 4, "head": HEAD}
    observation = {"verified": True, "loop_id": "loop-015", "owner_role": "SEMI_AUTO", "holder_id": "controller-1", "generation": 1, "fencing_token": 1, "expected_repo": event["expected_repo"], "expected_pr": 4, "expected_target_head": HEAD, "state": "RUNNING", "evidence_ref": "evidence-owner-1", "observed_at": "2026-09-27T09:30:00+00:00", "expires_at": "2026-09-27T10:30:00+00:00"}
    return [event], receipt, target, observation


class LoopOwnerTests(unittest.TestCase):
    def decide(self, events=None, receipt=None, target=None, evidence=None, raw_state=None, now=NOW):
        default_events, default_receipt, default_target, default_observation = records()
        return decide_owner(default_events if events is None else events, raw_state or state(), target=default_target if target is None else target, receipt=default_receipt if receipt is None else receipt, evidence_refs={"evidence-owner-1"} if evidence is None else evidence, provider_observation=default_observation, now=now)

    def test_valid_durable_semiauto_projects_green(self):
        decision = self.decide()
        self.assertEqual((decision.status, decision.owner, decision.generation), ("VALID", "SEMI_AUTO", 1))
        self.assertEqual(project_with_durable_owner(state(), decision).display_state, "SEMI_AUTO")

    def test_ownerless_or_unreadable_evidence_fails_closed(self):
        self.assertEqual(self.decide(events=[]).owner, "NONE")
        decision = self.decide(evidence=set())
        self.assertEqual(decision.status, "UNKNOWN")
        self.assertEqual(project_with_durable_owner(state(), decision).display_state, "BLOCKED")

    def test_unsafe_loop_id_and_non_hex_target_head_are_rejected(self):
        events, _, _, _ = records()
        unsafe_loop = copy.deepcopy(events)
        unsafe_loop[0]["loop_id"] = "../bad"
        self.assertEqual(self.decide(events=unsafe_loop).status, "UNKNOWN")
        bad_head = copy.deepcopy(events)
        bad_head[0]["expected_target_head"] = "z" * 40
        self.assertEqual(self.decide(events=bad_head).status, "UNKNOWN")

    def test_expired_stale_generation_target_and_receipt_are_rejected(self):
        events, receipt, target, _ = records()
        expired = copy.deepcopy(events); expired[0]["expires_at"] = "2026-09-27T09:59:00+00:00"
        self.assertEqual(self.decide(events=expired).status, "UNKNOWN")
        stale = copy.deepcopy(events); stale[0]["generation"] = 2
        self.assertEqual(self.decide(events=stale).status, "UNKNOWN")
        self.assertEqual(self.decide(target={**target, "head": "b" * 40}).status, "UNKNOWN")
        self.assertEqual(self.decide(receipt={**receipt, "retry_count": 1}).status, "UNKNOWN")

    def test_duplicate_competing_owner_and_malformed_chain_rejected(self):
        events, receipt, target, _ = records()
        competing = copy.deepcopy(events[0]); competing.update(event_id="owner-event-2", event_type="ACQUIRE", generation=2, previous_generation=1, fencing_token=2, owner_role="AUTO", holder_id="controller-2")
        self.assertEqual(self.decide(events=[events[0], competing]).status, "UNKNOWN")
        self.assertEqual(self.decide(events=[events[0], events[0]]).status, "UNKNOWN")
        malformed = copy.deepcopy(events); malformed[0]["fencing_token"] = 99
        self.assertEqual(self.decide(events=malformed).status, "UNKNOWN")

    def test_provider_observation_must_be_fresh_and_generation_bound(self):
        events, receipt, target, observation = records()
        self.assertEqual(decide_owner(events, state(), target=target, receipt=receipt, evidence_refs={"evidence-owner-1"}, provider_observation=None, now=NOW).status, "UNKNOWN")
        stale = {**observation, "expires_at": "2026-09-27T09:59:00+00:00"}
        self.assertEqual(decide_owner(events, state(), target=target, receipt=receipt, evidence_refs={"evidence-owner-1"}, provider_observation=stale, now=NOW).status, "UNKNOWN")
        mismatch = {**observation, "generation": 2}
        self.assertEqual(decide_owner(events, state(), target=target, receipt=receipt, evidence_refs={"evidence-owner-1"}, provider_observation=mismatch, now=NOW).status, "UNKNOWN")

    def test_release_and_terminal_generation_close_owner_chain(self):
        events, _, _, _ = records()
        released = copy.deepcopy(events[0]); released.update(event_id="owner-event-2", event_type="RELEASE", generation=2, previous_generation=1, fencing_token=2)
        release_decision = self.decide(events=[events[0], released])
        self.assertEqual((release_decision.status, release_decision.owner), ("BLOCKED", "NONE"))
        self.assertIn("released", release_decision.reason)

        terminal = copy.deepcopy(events[0]); terminal.update(
            event_id="owner-event-2",
            event_type="TERMINAL",
            generation=2,
            previous_generation=1,
            fencing_token=2,
            terminal_receipt_id="receipt-terminal",
        )
        terminal_decision = self.decide(events=[events[0], terminal])
        self.assertEqual((terminal_decision.status, terminal_decision.owner), ("BLOCKED", "NONE"))
        self.assertIn("terminal", terminal_decision.reason)

        continued = copy.deepcopy(terminal); continued.update(
            event_id="owner-event-3",
            event_type="RENEW",
            generation=3,
            previous_generation=2,
            fencing_token=3,
        )
        self.assertEqual(self.decide(events=[events[0], terminal, continued]).status, "UNKNOWN")

    def test_schema_and_ledger_scope_are_explicit(self):
        path = Path(__file__).parents[1] / "schema" / "loop_owner_event.schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("fencing_token", schema["required"])
        from automation.command_bus.validation_scope import ScopeKind, classify_command_bus_path
        self.assertEqual(classify_command_bus_path("automation/command_bus/loop_owner_events/x/000001.json"), ScopeKind.LEDGER)


if __name__ == "__main__":
    unittest.main()

