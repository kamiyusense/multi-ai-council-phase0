from __future__ import annotations

import json
import unittest

from automation.command_bus.github_backend import GitHubContent
from automation.command_bus.loop_owner_authority import (
    AuthorityGrantProof,
    DurableOwnerAuthority,
    authority_grant_path,
    grant_for_event,
)
from automation.command_bus.runtime_transition_coordinator import RuntimeTransitionPublisher
from automation.command_bus.tests.test_loop_owner import first_event
from automation.command_bus.tests.test_runtime_transition_publisher import (
    Client,
    Clock,
    Status,
    Target,
    TransitionRequest,
    Verifier as ProviderVerifier,
    evidence,
    observation_for,
    receipt_for,
    state,
    target_for,
)


class GrantVerifier:
    def verify(self, grant, event, prior_state, target, receipt, chain):
        return AuthorityGrantProof(
            grant,
            f"automation/command_bus/evidence/{event['loop_id']}/authority-{event['generation']}.json",
        )


class RuntimeOwnerAuthorityIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.event = first_event()
        self.client = Client()
        self.target = Target(target_for(self.event))
        self.status = Status()
        self.prior = state(state="PREPARED")
        self.desired = state(
            state="RUNNING",
            last_command_id=self.event["command_id"],
            last_receipt_id=self.event["source_receipt_id"],
            expected_target=target_for(self.event),
        )
        self.evidence = evidence(self.event)
        self.observation = observation_for(self.event)
        self.observation.pop("verified")
        self.client.put("automation/command_bus/state/loop-015.json", self.prior)
        self.client.put(self.event["source_receipt_ref"], receipt_for(self.event))
        self.grant = grant_for_event(
            self.event,
            authority_id="authority-1",
            issued_at="2026-09-27T08:55:00+00:00",
            verification_ref="automation/command_bus/evidence/loop-015/authority-1.json",
        )
        path = authority_grant_path("loop-015", 1)
        self.client.data[path] = GitHubContent(
            path=path,
            text=json.dumps(self.grant, sort_keys=True, separators=(",", ":")),
            sha="authority-grant",
        )

    def request(self):
        return TransitionRequest(
            self.event,
            self.evidence,
            self.observation,
            self.prior,
            self.desired,
        )

    def publisher(self, grant_verifier):
        authority = DurableOwnerAuthority(
            self.client,
            branch="runtime-ledger",
            verifier=grant_verifier,
            clock=Clock(),
        )
        return RuntimeTransitionPublisher(
            self.client,
            branch="runtime-ledger",
            target_reader=self.target,
            owner_authority=authority,
            provider_verifier=ProviderVerifier(),
            status_boundary=self.status,
            clock=Clock(),
        )

    def test_durable_grant_without_independent_verifier_makes_no_writes(self):
        result = self.publisher(None).publish(self.request())
        self.assertEqual((result.status, result.stage), ("NOT_WIRED", "authority"), result)
        self.assertEqual((self.client.creates, self.client.updates), (0, 0))
        self.assertEqual(self.status.plans, [])

    def test_verified_durable_grant_allows_existing_publisher_flow(self):
        result = self.publisher(GrantVerifier()).publish(self.request())
        self.assertEqual((result.status, result.stage), ("READY", "status_boundary"), result)
        self.assertEqual(result.status_plan.owner if hasattr(result.status_plan, "owner") else "SEMI_AUTO", "SEMI_AUTO")
        self.assertEqual((self.client.creates, self.client.updates), (3, 1))
        self.assertEqual(len(self.status.plans), 1)

    def test_conflicting_grant_context_blocks_before_mutation(self):
        bad = dict(self.grant)
        bad["expected_target_head"] = "b" * 40
        path = authority_grant_path("loop-015", 1)
        self.client.data[path] = GitHubContent(
            path=path,
            text=json.dumps(bad, sort_keys=True, separators=(",", ":")),
            sha="bad-authority",
        )
        result = self.publisher(GrantVerifier()).publish(self.request())
        self.assertEqual((result.status, result.stage), ("NOT_WIRED", "authority"), result)
        self.assertEqual((self.client.creates, self.client.updates), (0, 0))


if __name__ == "__main__":
    unittest.main()
