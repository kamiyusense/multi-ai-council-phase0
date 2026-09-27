from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from automation.command_bus.loop_owner import decide_owner, project_with_durable_owner
from automation.command_bus.tests.test_loop_status_issue import state


NOW = "2026-09-27T10:00:00+00:00"
HEAD = "a" * 40
EVIDENCE = "automation/command_bus/evidence/loop-015/owner-1.json"


def first_event():
    return {
        "schema_version": 1,
        "event_id": "owner-event-1",
        "event_type": "ACQUIRE",
        "loop_id": "loop-015",
        "owner_role": "SEMI_AUTO",
        "holder_id": "controller-1",
        "generation": 1,
        "fencing_token": 1,
        "previous_generation": None,
        "claimed_at": "2026-09-27T09:00:00+00:00",
        "expires_at": "2026-09-27T11:00:00+00:00",
        "expected_repo": "kamiyusense/multi-ai-council-phase0",
        "expected_pr": 4,
        "expected_target_head": HEAD,
        "command_id": "cmd-015-g1",
        "correlation_id": "corr-015-g1",
        "source_receipt_id": "receipt-owner-1",
        "source_receipt_ref": "automation/command_bus/receipts/loop-015/000001.json",
        "evidence_refs": [EVIDENCE],
    }


def next_event(
    previous: dict,
    *,
    event_type: str = "RENEW",
    owner_role: str | None = None,
    holder_id: str | None = None,
    head: str | None = None,
):
    generation = previous["generation"] + 1
    event = copy.deepcopy(previous)
    event.update(
        event_id=f"owner-event-{generation}",
        event_type=event_type,
        generation=generation,
        fencing_token=generation,
        previous_generation=previous["generation"],
        claimed_at=f"2026-09-27T09:{generation * 5:02d}:00+00:00",
        expires_at=f"2026-09-27T11:{generation * 5:02d}:00+00:00",
        expected_target_head=head or (hex(generation)[2:] * 40)[:40],
        command_id=f"cmd-015-g{generation}",
        correlation_id=f"corr-015-g{generation}",
        source_receipt_id=f"receipt-owner-{generation}",
        source_receipt_ref=f"automation/command_bus/receipts/loop-015/{generation:06d}.json",
        evidence_refs=[f"automation/command_bus/evidence/loop-015/owner-{generation}.json"],
    )
    if owner_role is not None:
        event["owner_role"] = owner_role
    if holder_id is not None:
        event["holder_id"] = holder_id
    if event_type == "HANDOFF":
        event["previous_owner_role"] = previous["owner_role"]
        event["previous_holder_id"] = previous["holder_id"]
    else:
        event.pop("previous_owner_role", None)
        event.pop("previous_holder_id", None)
    if event_type == "TERMINAL":
        event["terminal_receipt_id"] = event["source_receipt_id"]
    else:
        event.pop("terminal_receipt_id", None)
    return event


def receipt_for(event: dict):
    return {
        "schema_version": 1,
        "receipt_id": event["source_receipt_id"],
        "loop_id": event["loop_id"],
        "command_id": event["command_id"],
        "correlation_id": event["correlation_id"],
        "state": "DONE",
        "executed_once": True,
        "retry_count": 0,
        "fallback_used": False,
        "evidence_refs": list(event["evidence_refs"]),
    }


def target_for(event: dict):
    return {
        "repo": event["expected_repo"],
        "pr": event["expected_pr"],
        "head": event["expected_target_head"],
    }


def observation_for(event: dict):
    return {
        "schema_version": 1,
        "observation_id": f"provider-observation-{event['generation']}",
        "verified": True,
        "loop_id": event["loop_id"],
        "owner_role": event["owner_role"],
        "holder_id": event["holder_id"],
        "generation": event["generation"],
        "fencing_token": event["fencing_token"],
        "expected_repo": event["expected_repo"],
        "expected_pr": event["expected_pr"],
        "expected_target_head": event["expected_target_head"],
        "state": "RUNNING",
        "evidence_ref": event["evidence_refs"][0],
        "observed_at": "2026-09-27T09:30:00+00:00",
        "expires_at": "2026-09-27T10:30:00+00:00",
    }


def records():
    event = first_event()
    return [event], receipt_for(event), target_for(event), observation_for(event)


def decision(
    events: list[dict] | None = None,
    *,
    receipt=None,
    target=None,
    evidence=None,
    raw_state=None,
    observation=None,
    now=NOW,
):
    events = [first_event()] if events is None else events
    latest = events[-1] if events else first_event()
    default_receipt = receipt_for(latest)
    default_target = target_for(latest)
    default_observation = observation_for(latest)
    default_state = state(
        last_command_id=latest["command_id"],
        last_receipt_id=latest["source_receipt_id"],
        expected_target=default_target,
    )
    return decide_owner(
        events,
        raw_state or default_state,
        target=default_target if target is None else target,
        receipt=default_receipt if receipt is None else receipt,
        evidence_refs=set(latest["evidence_refs"]) if evidence is None else evidence,
        provider_observation=default_observation if observation is None else observation,
        now=now,
    )


class LoopOwnerTests(unittest.TestCase):
    def test_valid_durable_semiauto_projects_green(self):
        result = decision()
        self.assertEqual((result.status, result.owner, result.generation), ("VALID", "SEMI_AUTO", 1))
        self.assertEqual(project_with_durable_owner(state(), result).display_state, "SEMI_AUTO")

    def test_valid_auto_projects_purple(self):
        event = first_event()
        event["owner_role"] = "AUTO"
        result = decision([event])
        self.assertEqual(result.owner, "AUTO")
        self.assertEqual(project_with_durable_owner(state(), result).display_state, "AUTO")

    def test_ownerless_or_unreadable_evidence_fails_closed(self):
        self.assertEqual(decision([]).owner, "NONE")
        result = decision(evidence=set())
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(project_with_durable_owner(state(), result).display_state, "BLOCKED")

    def test_paths_head_and_loop_are_strict(self):
        event = first_event()
        for field, value in (
            ("loop_id", "../bad"),
            ("expected_target_head", "z" * 40),
            ("source_receipt_ref", "../receipt.json"),
            ("source_receipt_ref", "automation/command_bus/execution_receipts/loop-015/000001.json"),
            ("source_receipt_ref", "automation/command_bus/receipts/other-loop/000001.json"),
            ("evidence_refs", ["automation/command_bus/evidence/other-loop/owner-1.json"]),
        ):
            bad = copy.deepcopy(event)
            bad[field] = value
            with self.subTest(field=field, value=value):
                self.assertEqual(decision([bad], evidence=set(bad.get("evidence_refs", []))).status, "UNKNOWN")

    def test_expired_future_target_and_receipt_are_rejected(self):
        event = first_event()
        expired = copy.deepcopy(event)
        expired["expires_at"] = "2026-09-27T09:59:00+00:00"
        self.assertEqual(decision([expired]).status, "UNKNOWN")
        future = copy.deepcopy(event)
        future["claimed_at"] = "2026-09-27T10:01:00+00:00"
        self.assertEqual(decision([future]).status, "UNKNOWN")
        self.assertEqual(decision(target={**target_for(event), "head": "b" * 40}).status, "UNKNOWN")
        self.assertEqual(decision(receipt={**receipt_for(event), "retry_count": 1}).status, "UNKNOWN")

    def test_generation_order_and_replay_are_rejected(self):
        first = first_event()
        second = next_event(first)
        skipped = copy.deepcopy(second)
        skipped.update(generation=3, fencing_token=3)
        self.assertEqual(decision([first, skipped]).status, "UNKNOWN")
        reordered = next_event(second)
        self.assertEqual(decision([first, reordered, second]).status, "UNKNOWN")

        duplicate_command = next_event(first)
        duplicate_command["command_id"] = first["command_id"]
        self.assertEqual(decision([first, duplicate_command]).status, "UNKNOWN")
        duplicate_receipt = next_event(first)
        duplicate_receipt["source_receipt_id"] = first["source_receipt_id"]
        self.assertEqual(decision([first, duplicate_receipt]).status, "UNKNOWN")

    def test_only_loop_repo_and_pr_are_chain_invariants(self):
        first = first_event()
        second = next_event(first, head="b" * 40)
        self.assertEqual(decision([first, second]).status, "VALID")

        for key, value in (
            ("loop_id", "other-loop"),
            ("expected_repo", "elsewhere/repo"),
            ("expected_pr", 25),
        ):
            bad = copy.deepcopy(second)
            bad[key] = value
            if key == "loop_id":
                bad["source_receipt_ref"] = "automation/command_bus/receipts/other-loop/000002.json"
                bad["evidence_refs"] = ["automation/command_bus/evidence/other-loop/owner-2.json"]
            self.assertEqual(decision([first, bad], evidence=set(bad["evidence_refs"])).status, "UNKNOWN", key)

    def test_latest_state_receipt_and_evidence_must_match(self):
        event = first_event()
        wrong_state = state(
            last_command_id="other-command",
            last_receipt_id=event["source_receipt_id"],
            expected_target=target_for(event),
        )
        self.assertEqual(decision(raw_state=wrong_state).status, "UNKNOWN")
        wrong_state = state(
            last_command_id=event["command_id"],
            last_receipt_id="other-receipt",
            expected_target=target_for(event),
        )
        self.assertEqual(decision(raw_state=wrong_state).status, "UNKNOWN")
        self.assertEqual(decision(receipt={**receipt_for(event), "receipt_id": "other-receipt"}).status, "UNKNOWN")
        self.assertEqual(decision(evidence={"automation/command_bus/evidence/loop-015/other.json"}).status, "UNKNOWN")

    def test_provider_observation_must_be_fresh_and_generation_bound(self):
        event = first_event()
        obs = observation_for(event)
        self.assertEqual(decision(observation=None).status, "VALID")
        stale = {**obs, "expires_at": "2026-09-27T09:59:00+00:00"}
        self.assertEqual(decision(observation=stale).status, "UNKNOWN")
        mismatch = {**obs, "generation": 2}
        self.assertEqual(decision(observation=mismatch).status, "UNKNOWN")
        stale_time = {**obs, "observed_at": "2026-09-27T08:59:00+00:00"}
        self.assertEqual(decision(observation=stale_time).status, "UNKNOWN")
        target_mismatch = {**obs, "expected_target_head": "b" * 40}
        self.assertEqual(decision(observation=target_mismatch).status, "UNKNOWN")

    def test_handoff_uses_new_generation_proof_and_fences_previous_owner(self):
        first = first_event()
        handoff = next_event(first, event_type="HANDOFF", owner_role="AUTO", holder_id="controller-2", head="b" * 40)
        result = decision([first, handoff])
        self.assertEqual((result.status, result.owner, result.generation), ("VALID", "AUTO", 2))

        invalid = copy.deepcopy(handoff)
        invalid["previous_holder_id"] = "stranger"
        self.assertEqual(decision([first, invalid]).status, "UNKNOWN")
        same_owner = copy.deepcopy(handoff)
        same_owner.update(owner_role="SEMI_AUTO", holder_id="controller-1")
        self.assertEqual(decision([first, same_owner]).status, "UNKNOWN")

    def test_release_and_terminal_close_chain(self):
        first = first_event()
        released = next_event(first, event_type="RELEASE")
        result = decision([first, released])
        self.assertEqual((result.status, result.owner), ("BLOCKED", "NONE"))
        self.assertIn("release", result.reason)
        blocked_release = {**receipt_for(released), "state": "BLOCKED"}
        self.assertEqual(decision([first, released], receipt=blocked_release).status, "UNKNOWN")

        terminal = next_event(first, event_type="TERMINAL")
        result = decision([first, terminal])
        self.assertEqual((result.status, result.owner), ("BLOCKED", "NONE"))
        self.assertIn("terminal", result.reason)

        blocked_receipt = {**receipt_for(terminal), "state": "BLOCKED"}
        result = decision([first, terminal], receipt=blocked_receipt)
        self.assertEqual((result.status, result.owner), ("BLOCKED", "NONE"))

        unsafe_receipt = {**receipt_for(terminal), "retry_count": 1}
        self.assertEqual(decision([first, terminal], receipt=unsafe_receipt).status, "UNKNOWN")

        bad_terminal = copy.deepcopy(terminal)
        bad_terminal["terminal_receipt_id"] = "different-receipt"
        self.assertEqual(decision([first, bad_terminal]).status, "UNKNOWN")

        continued = next_event(terminal)
        self.assertEqual(decision([first, terminal, continued]).status, "UNKNOWN")

    def test_boolean_generation_and_unknown_fields_are_rejected(self):
        event = first_event()
        bad = copy.deepcopy(event)
        bad["generation"] = True
        bad["fencing_token"] = True
        self.assertEqual(decision([bad]).status, "UNKNOWN")
        bad = copy.deepcopy(event)
        bad["untrusted_extra"] = True
        self.assertEqual(decision([bad]).status, "UNKNOWN")

    def test_schema_and_ledger_scope_are_explicit(self):
        path = Path(__file__).parents[1] / "schema" / "loop_owner_event.schema.json"
        schema = json.loads(path.read_text(encoding="utf-8"))
        self.assertIn("fencing_token", schema["required"])
        self.assertIn("source_receipt_ref", schema["required"])
        from automation.command_bus.validation_scope import ScopeKind, classify_command_bus_path
        self.assertEqual(
            classify_command_bus_path("automation/command_bus/loop_owner_events/x/000001.json"),
            ScopeKind.LEDGER,
        )


if __name__ == "__main__":
    unittest.main()
