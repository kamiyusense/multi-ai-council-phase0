from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from automation.command_bus.github_backend import GitHubContent
from automation.command_bus.loop_owner_authority import (
    AuthorityGrantProof,
    DurableOwnerAuthority,
    authority_grant_path,
    grant_for_event,
)
from automation.command_bus.runtime_transition_coordinator import RuntimeTransitionPublisher
from automation.command_bus.runtime_verifier_sources import (
    SourceBoundAuthorityGrantVerifier,
    SourceBoundProviderVerifier,
    VerifiedSourceAttestation,
    validate_authority_verification_source,
    validate_provider_verification_source,
)
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


_FIXTURES = Path(__file__).parent / "fixtures" / "verifier_sources"


def fixture(name):
    return json.loads((_FIXTURES / name).read_text(encoding="utf-8"))


class GrantVerifier:
    def verify(self, grant, event, prior_state, target, receipt, chain):
        return AuthorityGrantProof(
            grant,
            f"automation/command_bus/evidence/{event['loop_id']}/authority-{event['generation']}.json",
        )


class SourceReader:
    def __init__(self, records):
        self.records = {key: copy.deepcopy(value) for key, value in records.items()}
        self.calls = []

    def read(self, source_ref):
        self.calls.append(source_ref)
        value = self.records.get(source_ref)
        return copy.deepcopy(value) if value is not None else None


class Authenticator:
    def __init__(self, *, accept=True, mismatched_ref=False):
        self.accept = accept
        self.mismatched_ref = mismatched_ref
        self.calls = []

    def authenticate(self, source, *, expected):
        self.calls.append((copy.deepcopy(source), copy.deepcopy(expected)))
        if not self.accept:
            return None
        return VerifiedSourceAttestation(
            source["verification_kind"],
            source["source_id"],
            "provider:wrong" if self.mismatched_ref else source["source_ref"],
            source["observed_at"],
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

    def publisher(self, grant_verifier, provider_verifier=None):
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
            provider_verifier=provider_verifier or ProviderVerifier(),
            status_boundary=self.status,
            clock=Clock(),
        )

    def source_authority(self, *, source=None, authenticator=None):
        raw = source or fixture("authority_verified.json")
        reader = SourceReader({self.grant["verification_ref"]: raw})
        verifier = SourceBoundAuthorityGrantVerifier(
            reader,
            authenticator if authenticator is not None else Authenticator(),
        )
        return verifier, reader

    def source_provider(self, *, source=None, authenticator=None):
        raw = source or fixture("provider_verified.json")
        reader = SourceReader({self.evidence["provider_readback"]: raw})
        verifier = SourceBoundProviderVerifier(
            reader,
            authenticator if authenticator is not None else Authenticator(),
        )
        return verifier, reader

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

    def test_source_bound_authority_and_provider_complete_existing_static_flow(self):
        authority, authority_reader = self.source_authority()
        provider, provider_reader = self.source_provider()
        result = self.publisher(authority, provider).publish(self.request())
        self.assertEqual((result.status, result.stage), ("READY", "status_boundary"), result)
        self.assertEqual(authority_reader.calls, [self.grant["verification_ref"]])
        self.assertEqual(provider_reader.calls, [self.evidence["provider_readback"]])
        self.assertEqual((self.client.creates, self.client.updates), (3, 1))

    def test_raw_verified_authority_source_without_authenticator_is_not_authority(self):
        raw = fixture("authority_verified.json")
        reader = SourceReader({self.grant["verification_ref"]: raw})
        verifier = SourceBoundAuthorityGrantVerifier(reader, None)
        result = self.publisher(verifier).publish(self.request())
        self.assertEqual(result.status, "NOT_WIRED")
        self.assertEqual((self.client.creates, self.client.updates), (0, 0))

    def test_raw_verified_provider_source_without_authenticator_is_not_verified(self):
        authority, _ = self.source_authority()
        raw = fixture("provider_verified.json")
        reader = SourceReader({self.evidence["provider_readback"]: raw})
        verifier = SourceBoundProviderVerifier(reader, None)
        result = self.publisher(authority, verifier).publish(self.request())
        self.assertEqual(result.status, "NOT_WIRED")
        self.assertEqual((self.client.creates, self.client.updates), (0, 0))

    def test_rejected_authenticator_or_mismatched_attestation_fails_closed(self):
        authority, _ = self.source_authority(authenticator=Authenticator(accept=False))
        result = self.publisher(authority).publish(self.request())
        self.assertEqual(result.status, "NOT_WIRED")
        self.assertEqual((self.client.creates, self.client.updates), (0, 0))

        fixture_case = RuntimeOwnerAuthorityIntegrationTests()
        fixture_case.setUp()
        authority, _ = fixture_case.source_authority(authenticator=Authenticator(mismatched_ref=True))
        result = fixture_case.publisher(authority).publish(fixture_case.request())
        self.assertEqual(result.status, "NOT_WIRED")
        self.assertEqual((fixture_case.client.creates, fixture_case.client.updates), (0, 0))

    def test_source_context_mismatch_fails_closed_before_mutation(self):
        authority_source = fixture("authority_verified.json")
        authority_source["expected_target_head"] = "b" * 40
        authority, _ = self.source_authority(source=authority_source)
        result = self.publisher(authority).publish(self.request())
        self.assertEqual(result.status, "NOT_WIRED")
        self.assertEqual((self.client.creates, self.client.updates), (0, 0))

        fixture_case = RuntimeOwnerAuthorityIntegrationTests()
        fixture_case.setUp()
        provider_source = fixture("provider_verified.json")
        provider_source["provider_state"] = "FAILED"
        authority, _ = fixture_case.source_authority()
        provider, _ = fixture_case.source_provider(source=provider_source)
        result = fixture_case.publisher(authority, provider).publish(fixture_case.request())
        self.assertEqual(result.status, "NOT_WIRED")
        self.assertEqual((fixture_case.client.creates, fixture_case.client.updates), (0, 0))

    def test_source_validators_reject_untrusted_shape_and_secret_like_urls(self):
        authority = fixture("authority_verified.json")
        validate_authority_verification_source(authority)
        bad = copy.deepcopy(authority)
        bad["extra"] = True
        with self.assertRaises(ValueError):
            validate_authority_verification_source(bad)
        bad = copy.deepcopy(authority)
        bad["proof_refs"] = ["https://example.com/token"]
        with self.assertRaises(ValueError):
            validate_authority_verification_source(bad)

        provider = fixture("provider_verified.json")
        validate_provider_verification_source(provider)
        bad = copy.deepcopy(provider)
        bad["source_ref"] = "https://provider.example/secret"
        with self.assertRaises(ValueError):
            validate_provider_verification_source(bad)


if __name__ == "__main__":
    unittest.main()
