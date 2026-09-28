from __future__ import annotations

import copy
import unittest

from automation.command_bus.runtime_takeover import preflight_takeover
from automation.command_bus.runtime_transition_coordinator import AuthorizedOwnerContext, VerifiedProviderObservation
from automation.command_bus.tests.test_loop_owner import (
    HEAD,
    first_event,
    next_event,
    observation_for,
    receipt_for,
    target_for,
)
from automation.command_bus.tests.test_loop_status_issue import state


NOW = "2026-09-27T11:01:00+00:00"


def proposed(first=None, *, owner_role="AUTO", holder_id="controller-2"):
    first = first or first_event()
    event = next_event(
        first,
        event_type="HANDOFF",
        owner_role=owner_role,
        holder_id=holder_id,
        head=first["expected_target_head"],
    )
    event["claimed_at"] = "2026-09-27T11:00:00+00:00"
    event["expires_at"] = "2026-09-27T12:00:00+00:00"
    return event


def current_state(first=None):
    first = first or first_event()
    return state(
        state="RUNNING",
        stop_requested=False,
        last_command_id=first["command_id"],
        last_receipt_id=first["source_receipt_id"],
        expected_target=target_for(first),
    )


def authority_for(event):
    return AuthorizedOwnerContext(
        **{key: event[key] for key in AuthorizedOwnerContext.__dataclass_fields__}
    )


def provider_for(event):
    observation = observation_for(event)
    observation["observed_at"] = "2026-09-27T11:00:30+00:00"
    observation["expires_at"] = "2026-09-27T11:30:00+00:00"
    return VerifiedProviderObservation(observation, "provider:takeover-2")


def evaluate(**changes):
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
        "now": NOW,
    }
    values.update(changes)
    return preflight_takeover(**values)


class RuntimeTakeoverPreflightTests(unittest.TestCase):
    def test_expired_owner_plus_explicit_authority_and_provider_proof_is_ready(self):
        result = evaluate()
        self.assertEqual((result.status, result.stage), ("READY", "complete"), result)
        self.assertIsNotNone(result.plan)
        self.assertEqual(result.plan.from_owner_role, "SEMI_AUTO")
        self.assertEqual(result.plan.to_owner_role, "AUTO")
        self.assertEqual((result.plan.from_generation, result.plan.generation), (1, 2))
        self.assertEqual(result.plan.fencing_token, 2)

    def test_reverse_auto_to_semiauto_role_switch_is_supported(self):
        first = first_event()
        first["owner_role"] = "AUTO"
        handoff = proposed(first, owner_role="SEMI_AUTO", holder_id="controller-human")
        result = evaluate(first=first, proposed_event=handoff)
        self.assertEqual(result.status, "READY", result)
        self.assertEqual((result.plan.from_owner_role, result.plan.to_owner_role), ("AUTO", "SEMI_AUTO"))

    def test_lease_expiry_is_required_but_not_sufficient(self):
        before = evaluate(now="2026-09-27T10:59:59+00:00")
        self.assertEqual((before.status, before.stage), ("BLOCKED", "expiry"))

        no_authority = evaluate(authorized_owner=None)
        self.assertEqual((no_authority.status, no_authority.stage), ("NOT_WIRED", "authority"))

        no_provider = evaluate(verified_provider=None)
        self.assertEqual((no_provider.status, no_provider.stage), ("NOT_WIRED", "provider"))

    def test_state_and_fresh_target_must_still_bind_previous_owner(self):
        first = first_event()
        bad_state = current_state(first)
        bad_state["last_command_id"] = "other-command"
        self.assertEqual(evaluate(first=first, state=bad_state).status, "BLOCKED")

        moved = {**target_for(first), "head": "b" * 40}
        result = evaluate(first=first, target=moved)
        self.assertEqual((result.status, result.stage), ("BLOCKED", "target"))

    def test_stop_or_nonactive_state_blocks_takeover(self):
        first = first_event()
        stopped = current_state(first)
        stopped["stop_requested"] = True
        self.assertEqual(evaluate(first=first, state=stopped).status, "BLOCKED")

        blocked = current_state(first)
        blocked["state"] = "BLOCKED"
        self.assertEqual(evaluate(first=first, state=blocked).status, "BLOCKED")

    def test_release_or_terminal_chain_cannot_be_taken_over(self):
        for event_type in ("RELEASE", "TERMINAL"):
            first = first_event()
            closed = next_event(first, event_type=event_type, head=HEAD)
            closed["claimed_at"] = "2026-09-27T10:30:00+00:00"
            closed["expires_at"] = "2026-09-27T11:00:00+00:00"
            raw_state = state(
                state="RUNNING",
                last_command_id=closed["command_id"],
                last_receipt_id=closed["source_receipt_id"],
                expected_target=target_for(closed),
            )
            result = preflight_takeover(
                state=raw_state,
                owner_events=[first, closed],
                current_receipt=receipt_for(closed),
                current_evidence_refs=set(closed["evidence_refs"]),
                current_provider_observation=observation_for(first),
                target=target_for(closed),
                proposed_event=proposed(first),
                proposed_receipt=receipt_for(proposed(first)),
                authorized_owner=authority_for(proposed(first)),
                verified_provider=provider_for(proposed(first)),
                now=NOW,
            )
            self.assertEqual((result.status, result.stage), ("BLOCKED", "current_owner"))

    def test_handoff_must_be_exact_next_generation_and_fence_previous_owner(self):
        first = first_event()
        cases = []

        stale = proposed(first)
        stale["generation"] = 3
        stale["fencing_token"] = 3
        stale["previous_generation"] = 2
        cases.append(stale)

        wrong_previous = proposed(first)
        wrong_previous["previous_holder_id"] = "stranger"
        cases.append(wrong_previous)

        same_role = proposed(first, owner_role="SEMI_AUTO", holder_id="controller-2")
        cases.append(same_role)

        changed_head = proposed(first)
        changed_head["expected_target_head"] = "b" * 40
        cases.append(changed_head)

        for event in cases:
            with self.subTest(event=event):
                result = evaluate(first=first, proposed_event=event)
                self.assertEqual(result.status, "BLOCKED")

    def test_takeover_claim_cannot_overlap_previous_lease_or_be_future(self):
        first = first_event()
        overlap = proposed(first)
        overlap["claimed_at"] = "2026-09-27T10:59:59+00:00"
        self.assertEqual(evaluate(first=first, proposed_event=overlap).status, "BLOCKED")

        future = proposed(first)
        future["claimed_at"] = "2026-09-27T11:02:00+00:00"
        future["expires_at"] = "2026-09-27T12:02:00+00:00"
        self.assertEqual(evaluate(first=first, proposed_event=future).status, "BLOCKED")

    def test_current_receipt_evidence_and_provider_history_are_required(self):
        first = first_event()
        bad_receipt = receipt_for(first)
        bad_receipt["receipt_id"] = "other-receipt"
        self.assertEqual(evaluate(first=first, current_receipt=bad_receipt).status, "BLOCKED")

        self.assertEqual(evaluate(first=first, current_evidence_refs=set()).status, "UNKNOWN")

        bad_observation = observation_for(first)
        bad_observation["holder_id"] = "other-holder"
        self.assertEqual(
            evaluate(first=first, current_provider_observation=bad_observation).status,
            "BLOCKED",
        )

    def test_proposed_receipt_must_bind_new_generation(self):
        first = first_event()
        handoff = proposed(first)
        bad = receipt_for(handoff)
        bad["evidence_refs"] = list(first["evidence_refs"])
        result = evaluate(first=first, proposed_event=handoff, proposed_receipt=bad)
        self.assertEqual((result.status, result.stage), ("BLOCKED", "proposed_receipt"))

    def test_authority_mismatch_and_provider_mismatch_fail_closed(self):
        first = first_event()
        handoff = proposed(first)
        wrong_authority_event = copy.deepcopy(handoff)
        wrong_authority_event["holder_id"] = "other-controller"
        authority = authority_for(wrong_authority_event)
        result = evaluate(first=first, proposed_event=handoff, authorized_owner=authority)
        self.assertEqual((result.status, result.stage), ("BLOCKED", "authority"))

        proof = provider_for(handoff)
        wrong = copy.deepcopy(proof.observation)
        wrong["expected_target_head"] = "b" * 40
        result = evaluate(
            first=first,
            proposed_event=handoff,
            verified_provider=VerifiedProviderObservation(wrong, proof.source_ref),
        )
        self.assertEqual((result.status, result.stage), ("BLOCKED", "provider"))

    def test_new_provider_proof_must_be_fresh_for_takeover_generation(self):
        first = first_event()
        handoff = proposed(first)

        proof = provider_for(handoff)
        early = copy.deepcopy(proof.observation)
        early["observed_at"] = "2026-09-27T10:59:59+00:00"
        result = evaluate(
            first=first,
            proposed_event=handoff,
            verified_provider=VerifiedProviderObservation(early, proof.source_ref),
        )
        self.assertEqual(result.status, "BLOCKED")

        expired = copy.deepcopy(proof.observation)
        expired["expires_at"] = "2026-09-27T11:00:59+00:00"
        result = evaluate(
            first=first,
            proposed_event=handoff,
            verified_provider=VerifiedProviderObservation(expired, proof.source_ref),
        )
        self.assertEqual(result.status, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
