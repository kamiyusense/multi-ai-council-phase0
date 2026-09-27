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
    return [event], receipt, target


class LoopOwnerTests(unittest.TestCase):
    def decide(self, events=None, receipt=None, target=None, evidence=None, raw_state=None, now=NOW):
        default_events, default_receipt, default_target = records()
        return decide_owner(default_events if events is None else events, raw_state or state(), target=default_target if target is None else target, receipt=default_receipt if receipt is None else receipt, evidence_refs={"evidence-owner-1"} if evidence is None else evidence, now=now)

    def test_valid_durable_semiauto_projects_green(self):
        decision = self.decide()
        self.assertEqual((decision.status, decision.owner, decision.generation), ("VALID", "SEMI_AUTO", 1))
        self.assertEqual(project_with_durable_owner(state(), decision).display_state, "SEMI_AUTO")

    def test_ownerless_or_unreadable_evidence_fails_closed(self):
        self.assertEqual(self.decide(events=[]).owner, "NONE")
        decision = self.decide(evidence=set())
        self.assertEqual(decision.status, "UNKNOWN")
        self.assertEqual(project_with_durable_owner(state(), decision).display_state, "BLOCKED")

    def test_expired_stale_generation_target_and_receipt_are_rejected(self):
        events, receipt, target = records()
        expired = copy.deepcopy(events); expired[0]["expires_at"] = "2026-09-27T09:59:00+00:00"
        self.assertEqual(self.decide(events=expired).status, "UNKNOWN")
        stale = copy.deepcopy(events); stale[0]["generation"] = 2
        self.assertEqual(self.decide(events=stale).status, "UNKNOWN")
        self.assertEqual(self.decide(target={**target, "head": "b" * 40}).status, "UNKNOWN")
        self.assertEqual(self.decide(receipt={**receipt, "retry_count": 1}).status, "UNKNOWN")

    def test_duplicate_competing_owner_and_malformed_chain_rejected(self):
        events, receipt, target = records()
        competing = copy.deepcopy(events[0]); competing.update(event_id="owner-event-2", event_type="ACQUIRE", generation=2, previous_generation=1, fencing_token=2, owner_role="AUTO", holder_id="controller-2")
        self.assertEqual(self.decide(events=[events[0], competing]).status, "UNKNOWN")
        self.assertEqual(self.decide(events=[events[0], events[0]]).status, "UNKNOWN")
        malformed = copy.deepcopy(events); malformed[0]["fencing_token"] = 99
        self.assertEqual(self.decide(events=malformed).status, "UNKNOWN")

    def test_release_and_terminal_generation_cannot_reuse_owner(self):
        events, receipt, target = records()
        released = copy.deepcopy(events[0]); released.update(event_id="owner-event-2", event_type="RELEASE", generation=2, previous_generation=1, fencing_token=2)
        self.assertEqual(self.decide(events=[events[0], released]).owner, "NONE")
        terminal = copy.deepcopy(released); terminal.update(event_id="owner-event-3", event_type="TERMINAL", generation=3, previous_generation=2, fencing_token=3, terminal_receipt_id="receipt-terminal")
        self.assertEqual(self.decide(events=[events[0], released, terminal]).owner, "NONE")

    def test_schema_and_ledger_scope_are_explicit(self):
        path = Path(__file__).parents[1] / "schema" / "loop_owner_event.schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("fencing_token", schema["required"])
        from automation.command_bus.validation_scope import ScopeKind, classify_command_bus_path
        self.assertEqual(classify_command_bus_path("automation/command_bus/loop_owner_events/x/000001.json"), ScopeKind.LEDGER)


if __name__ == "__main__":
    unittest.main()

