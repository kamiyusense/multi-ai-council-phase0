from __future__ import annotations

import copy
import json
import unittest

from automation.command_bus.github_backend import GitHubContent
from automation.command_bus.loop_owner_authority import (
    DurableOwnerAuthority,
    authority_grant_path,
    grant_for_event,
)
from automation.command_bus.loop_owner_backend import owner_event_path
from automation.command_bus.runtime_takeover_prepare import prepare_takeover_transition
from automation.command_bus.runtime_transition_coordinator import RuntimeTransitionPublisher
from automation.command_bus.runtime_verifier_sources import (
    SourceBoundAuthorityGrantVerifier,
    SourceBoundProviderVerifier,
    VerifiedSourceAttestation,
)
from automation.command_bus.tests.test_runtime_takeover import (
    NOW,
    authority_for,
    current_state,
    proposed,
    provider_for,
)
from automation.command_bus.tests.test_runtime_takeover_prepare import (
    desired_state_for,
    evidence_for,
    provider_input_for,
)
from automation.command_bus.tests.test_loop_owner import (
    first_event,
    observation_for,
    receipt_for,
    target_for,
)
from automation.command_bus.tests.test_runtime_transition_publisher import (
    Client,
    Status,
    Target,
)


BRANCH = "runtime-ledger"


class Reader:
    def __init__(self, records):
        self.records = {key: copy.deepcopy(value) for key, value in records.items()}
        self.calls = []

    def read(self, source_ref):
        self.calls.append(source_ref)
        value = self.records.get(source_ref)
        return copy.deepcopy(value) if value is not None else None


class Authenticator:
    def __init__(self):
        self.calls = []

    def authenticate(self, source, *, expected):
        self.calls.append((copy.deepcopy(source), copy.deepcopy(expected)))
        return VerifiedSourceAttestation(
            source["verification_kind"],
            source["source_id"],
            source["source_ref"],
            source["observed_at"],
        )


class Clock:
    def now(self):
        return NOW


def authority_source(grant):
    return {
        "schema_version": 1,
        "verification_kind": "AUTHORITY_GRANT",
        "source_id": f"authority-source-{grant['generation']}",
        "source_ref": grant["verification_ref"],
        "verification_state": "VERIFIED",
        "observed_at": "2026-09-27T11:00:00+00:00",
        "expires_at": grant["expires_at"],
        "authority_id": grant["authority_id"],
        "loop_id": grant["loop_id"],
        "owner_role": grant["owner_role"],
        "holder_id": grant["holder_id"],
        "generation": grant["generation"],
        "fencing_token": grant["fencing_token"],
        "previous_generation": grant["previous_generation"],
        "event_type": grant["event_type"],
        "expected_repo": grant["expected_repo"],
        "expected_pr": grant["expected_pr"],
        "expected_target_head": grant["expected_target_head"],
        "command_id": grant["command_id"],
        "correlation_id": grant["correlation_id"],
        "proof_refs": [f"attestation:authority-{grant['generation']}"],
    }


def provider_source(event, evidence, observation):
    return {
        "schema_version": 1,
        "verification_kind": "PROVIDER_OBSERVATION",
        "source_id": f"provider-source-{event['generation']}",
        "source_ref": evidence["provider_readback"],
        "verification_state": "VERIFIED",
        "observed_at": observation["observed_at"],
        "expires_at": observation["expires_at"],
        "provider_kind": evidence["provider_kind"],
        "provider_state": evidence["provider_state"],
        "observation_id": observation["observation_id"],
        "loop_id": event["loop_id"],
        "owner_role": event["owner_role"],
        "holder_id": event["holder_id"],
        "generation": event["generation"],
        "fencing_token": event["fencing_token"],
        "expected_repo": event["expected_repo"],
        "expected_pr": event["expected_pr"],
        "expected_target_head": event["expected_target_head"],
        "command_id": event["command_id"],
        "correlation_id": event["correlation_id"],
        "source_receipt_ref": event["source_receipt_ref"],
        "evidence_ref": event["evidence_refs"][0],
        "proof_refs": [f"attestation:provider-{event['generation']}"],
    }


class RuntimeTakeoverStaticE2ETests(unittest.TestCase):
    def setUp(self):
        self.first = first_event()
        self.handoff = proposed(self.first)
        self.prior = current_state(self.first)
        self.desired = desired_state_for(self.handoff)
        self.evidence = evidence_for(self.handoff)
        self.provider_input = provider_input_for(self.handoff)
        self.verified_provider = provider_for(self.handoff)
        self.proposed_receipt = receipt_for(self.handoff)

        self.client = Client()
        self.client.put(f"automation/command_bus/state/{self.first['loop_id']}.json", self.prior)
        self.client.put(self.handoff["source_receipt_ref"], self.proposed_receipt)
        self.client.data[owner_event_path(self.first["loop_id"], 1)] = GitHubContent(
            path=owner_event_path(self.first["loop_id"], 1),
            text=json.dumps(self.first, sort_keys=True, separators=(",", ":")),
            sha="owner-1",
        )

        self.grant = grant_for_event(
            self.handoff,
            authority_id="takeover-authority-2",
            issued_at="2026-09-27T10:59:30+00:00",
            verification_ref="automation/command_bus/evidence/loop-015/authority-2.json",
        )
        grant_path = authority_grant_path(self.handoff["loop_id"], self.handoff["generation"])
        self.client.data[grant_path] = GitHubContent(
            path=grant_path,
            text=json.dumps(self.grant, sort_keys=True, separators=(",", ":")),
            sha="grant-2",
        )

        self.authority_reader = Reader(
            {self.grant["verification_ref"]: authority_source(self.grant)}
        )
        self.provider_reader = Reader(
            {
                self.evidence["provider_readback"]: provider_source(
                    self.handoff,
                    self.evidence,
                    self.verified_provider.observation,
                )
            }
        )
        self.authority_authenticator = Authenticator()
        self.provider_authenticator = Authenticator()

        self.authority = DurableOwnerAuthority(
            self.client,
            branch=BRANCH,
            verifier=SourceBoundAuthorityGrantVerifier(
                self.authority_reader,
                self.authority_authenticator,
            ),
            clock=Clock(),
        )
        self.provider_verifier = SourceBoundProviderVerifier(
            self.provider_reader,
            self.provider_authenticator,
        )
        self.status = Status()

    def prepare(self):
        return prepare_takeover_transition(
            state=self.prior,
            owner_events=[self.first],
            current_receipt=receipt_for(self.first),
            current_evidence_refs=set(self.first["evidence_refs"]),
            current_provider_observation=observation_for(self.first),
            target=target_for(self.first),
            proposed_event=self.handoff,
            proposed_receipt=self.proposed_receipt,
            authorized_owner=authority_for(self.handoff),
            verified_provider=self.verified_provider,
            evidence_document=self.evidence,
            provider_observation_input=self.provider_input,
            desired_state=self.desired,
            now=NOW,
        )

    def publisher(self):
        return RuntimeTransitionPublisher(
            self.client,
            branch=BRANCH,
            target_reader=Target(target_for(self.handoff)),
            owner_authority=self.authority,
            provider_verifier=self.provider_verifier,
            status_boundary=self.status,
            clock=Clock(),
        )

    def test_full_static_takeover_pipeline_reaches_status_prepare(self):
        prepared = self.prepare()
        self.assertEqual((prepared.status, prepared.stage), ("READY", "complete"), prepared)
        self.assertIsNotNone(prepared.request)

        result = self.publisher().publish(prepared.request)
        self.assertEqual((result.status, result.stage), ("READY", "status_boundary"), result)
        self.assertIsNotNone(result.status_plan)
        self.assertEqual(result.status_plan.display_state, "AUTO")
        self.assertEqual(result.status_plan.generation, 2)
        self.assertEqual(len(self.status.plans), 1)

        self.assertEqual((self.client.creates, self.client.updates), (3, 1))
        self.assertIn(owner_event_path("loop-015", 2), self.client.data)
        self.assertEqual(
            json.loads(
                self.client.data[owner_event_path("loop-015", 2)].text
            ),
            self.handoff,
        )
        final_state = json.loads(
            self.client.data["automation/command_bus/state/loop-015.json"].text
        )
        self.assertEqual(final_state, self.desired)

        self.assertEqual(self.authority_reader.calls, [self.grant["verification_ref"]])
        self.assertEqual(self.provider_reader.calls, [self.evidence["provider_readback"]])
        self.assertEqual(len(self.authority_authenticator.calls), 1)
        self.assertEqual(len(self.provider_authenticator.calls), 1)

    def test_missing_independent_authority_authenticator_stops_before_writes(self):
        prepared = self.prepare()
        self.assertEqual(prepared.status, "READY")

        authority = DurableOwnerAuthority(
            self.client,
            branch=BRANCH,
            verifier=SourceBoundAuthorityGrantVerifier(self.authority_reader, None),
            clock=Clock(),
        )
        publisher = RuntimeTransitionPublisher(
            self.client,
            branch=BRANCH,
            target_reader=Target(target_for(self.handoff)),
            owner_authority=authority,
            provider_verifier=self.provider_verifier,
            status_boundary=self.status,
            clock=Clock(),
        )
        result = publisher.publish(prepared.request)
        self.assertEqual((result.status, result.stage), ("NOT_WIRED", "authority"), result)
        self.assertEqual((self.client.creates, self.client.updates), (0, 0))
        self.assertEqual(self.status.plans, [])

    def test_missing_independent_provider_authenticator_stops_before_writes(self):
        prepared = self.prepare()
        self.assertEqual(prepared.status, "READY")

        publisher = RuntimeTransitionPublisher(
            self.client,
            branch=BRANCH,
            target_reader=Target(target_for(self.handoff)),
            owner_authority=self.authority,
            provider_verifier=SourceBoundProviderVerifier(self.provider_reader, None),
            status_boundary=self.status,
            clock=Clock(),
        )
        result = publisher.publish(prepared.request)
        self.assertEqual((result.status, result.stage), ("NOT_WIRED", "authority"), result)
        # Authority readback occurs first but no durable mutation is allowed before
        # provider verification. The publisher remains fail-closed.
        self.assertEqual((self.client.creates, self.client.updates), (0, 0))
        self.assertEqual(self.status.plans, [])

    def test_stale_target_stops_pipeline_before_writes(self):
        prepared = self.prepare()
        self.assertEqual(prepared.status, "READY")
        moved = {**target_for(self.handoff), "head": "b" * 40}
        publisher = RuntimeTransitionPublisher(
            self.client,
            branch=BRANCH,
            target_reader=Target(moved),
            owner_authority=self.authority,
            provider_verifier=self.provider_verifier,
            status_boundary=self.status,
            clock=Clock(),
        )
        result = publisher.publish(prepared.request)
        self.assertEqual((result.status, result.stage), ("BLOCKED", "fresh_readback"), result)
        self.assertEqual((self.client.creates, self.client.updates), (0, 0))
        self.assertEqual(self.status.plans, [])


if __name__ == "__main__":
    unittest.main()
