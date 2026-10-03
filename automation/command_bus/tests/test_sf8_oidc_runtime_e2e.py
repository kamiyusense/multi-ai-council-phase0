"""STATIC composition: OIDC-bound provider + authority authenticators in the real publisher chain.

Everything here is a fixture or mock. It proves wiring and fail-closed behaviour,
not live ownership, live OIDC trust, or a production loop id.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from automation.command_bus.control_tower_durable_collector import ControlTowerDurableCollector
from automation.command_bus.control_tower_live_preflight import (
    ControlTowerLanePresentation, prepare_verified_control_tower_migration,
)
from automation.command_bus.control_tower_registration import assess_registration_readiness
from automation.command_bus.github_oidc_proof_policy_cli import SF8_PROFILE
from automation.command_bus.loop_owner_authority import (
    AuthorityGrantGitHubBackend, DurableOwnerAuthority, grant_for_event,
)
from automation.command_bus.oidc_workflow_execution import (
    AuthorityIssuerPolicy, OidcBoundAuthorityAuthenticator, OidcBoundProviderAuthenticator,
    verify_oidc_workflow_execution,
)
from automation.command_bus.runtime_verifier_sources import (
    SourceBoundAuthorityGrantVerifier, SourceBoundProviderVerifier,
)
from automation.command_bus.sf8_readiness import (
    REQUIRED_CHECKS, CheckResult, assess_durable_promotion_candidate, issue33_migration_ready,
)
from automation.command_bus.tests.test_control_tower_live_preflight import issue
from automation.command_bus.tests.test_oidc_workflow_execution import (
    DISPATCH_PROFILE, OWNER_ID, RunReader, evidence_for, run_for,
)
from automation.command_bus.tests.test_semiauto_stable_identity_static_e2e import (
    CURRENT_TIME, LOOP_ID, Clock, SourceReader, TargetReader, build_chain, fixture_registry,
)
from automation.command_bus.tests.pre_adoption_registry import pre_adoption

REGISTRY_PATH = Path(__file__).parents[1] / "config" / "control_tower_registry.json"
SHA = "c" * 40
POLICY = AuthorityIssuerPolicy(allowed_actor_ids=frozenset({OWNER_ID}))


def execution(profile, run_id, **run_changes):
    return verify_oidc_workflow_execution(
        evidence=evidence_for(profile, run_id=run_id), profile=profile,
        run_reader=RunReader(run_for(profile, run_id=run_id, **run_changes)),
        expected_run_id=run_id, expected_sha=SHA,
    )


def authority_source(prepared, grant, exe):
    event = prepared.owner_event
    return {
        "schema_version": 1, "verification_kind": "AUTHORITY_GRANT",
        "source_id": "authority-source-1", "source_ref": grant["verification_ref"],
        "verification_state": "VERIFIED", "observed_at": "2026-09-28T04:00:00Z",
        "expires_at": grant["expires_at"], "authority_id": grant["authority_id"],
        "loop_id": event["loop_id"], "owner_role": event["owner_role"],
        "holder_id": event["holder_id"], "generation": event["generation"],
        "fencing_token": event["fencing_token"], "previous_generation": event["previous_generation"],
        "event_type": event["event_type"], "expected_repo": event["expected_repo"],
        "expected_pr": event["expected_pr"], "expected_target_head": event["expected_target_head"],
        "command_id": event["command_id"], "correlation_id": event["correlation_id"],
        "proof_refs": list(exe.proof_refs),
    }


def wire(*, provider_exec, authority_exec, write_grant=True, link_provider=True, authority_state="VERIFIED"):
    prepared, binding, normalized, source, client, publisher, status, flat = build_chain()
    inner = publisher.provider_verifier.authenticator
    linked = {**source, "proof_refs": [*source["proof_refs"], *(provider_exec.proof_refs if link_provider else ())]}
    publisher.provider_verifier = SourceBoundProviderVerifier(
        SourceReader(linked), OidcBoundProviderAuthenticator(execution=provider_exec, inner=inner))
    grant = grant_for_event(
        prepared.owner_event, authority_id="authority-1", issued_at="2026-09-28T03:58:00Z",
        verification_ref=f"automation/command_bus/evidence/{LOOP_ID}/authority-1.json")
    if write_grant:
        assert AuthorityGrantGitHubBackend(client, branch="fixture/runtime-data").write(grant).status == "ACCEPTED"
    a_source = {**authority_source(prepared, grant, authority_exec), "verification_state": authority_state}
    verifier = SourceBoundAuthorityGrantVerifier(
        SourceReader(a_source),
        OidcBoundAuthorityAuthenticator(execution=authority_exec, policy=POLICY, provider_execution=provider_exec))
    publisher.owner_authority = DurableOwnerAuthority(
        client, branch="fixture/runtime-data", verifier=verifier, clock=Clock())
    return prepared, binding, client, publisher, status, flat


class Sf8OidcRuntimeStaticE2ETests(unittest.TestCase):
    def setUp(self):
        self.provider_exec = execution(SF8_PROFILE, "5001")
        self.authority_exec = execution(DISPATCH_PROFILE, "5002")
        self.assertIsNotNone(self.provider_exec)
        self.assertIsNotNone(self.authority_exec)

    def test_full_chain_publishes_collects_and_registers_statically(self):
        prepared, binding, client, publisher, status, flat = wire(
            provider_exec=self.provider_exec, authority_exec=self.authority_exec)
        published = publisher.publish(binding.transition_request)
        self.assertEqual(published.status, "READY", published)
        self.assertEqual(len(status.plans), 1)
        collected = ControlTowerDurableCollector(
            client, ref="fixture/runtime-data", target_reader=TargetReader(flat), clock=Clock(),
        ).collect_transition(LOOP_ID)
        self.assertEqual(collected.status, "COLLECTED", collected)
        transitions = {LOOP_ID: collected.transition}
        self.assertEqual(assess_registration_readiness(fixture_registry(), transitions).status, "READY")
        preflight = prepare_verified_control_tower_migration(
            registry=fixture_registry(), verified_transitions=transitions,
            lane_presentation={LOOP_ID: ControlTowerLanePresentation()},
            generated_at=CURRENT_TIME, issue_readback=issue())
        self.assertEqual((preflight.status, preflight.stage), ("READY", "complete"), preflight)
        self.assertEqual(issue33_migration_ready(preflight.status), "YES")  # fixture only
        # A STATIC fixture chain is never a LIVE promotion candidate.
        checks = {n: CheckResult("PASS", "STATIC", f"static:{n}") for n in REQUIRED_CHECKS}
        self.assertEqual(assess_durable_promotion_candidate(checks).status, "NOT_READY")

    def test_push_triggered_authority_run_cannot_publish(self):
        push_exec = execution(SF8_PROFILE, "5002")  # what this implementation session can actually produce
        prepared, binding, client, publisher, status, flat = wire(
            provider_exec=self.provider_exec, authority_exec=push_exec)
        self.assertNotEqual(publisher.publish(binding.transition_request).status, "READY")
        self.assertEqual(status.plans, [])
        self.assertEqual(client.updates, 0)

    def test_missing_grant_unlinked_provider_or_unverified_authority_never_publish(self):
        cases = {
            "no_grant": dict(write_grant=False),
            "provider_not_linked_to_oidc_run": dict(link_provider=False),
            "authority_source_unverified": dict(authority_state="UNKNOWN"),
        }
        for label, kwargs in cases.items():
            with self.subTest(label):
                prepared, binding, client, publisher, status, flat = wire(
                    provider_exec=self.provider_exec, authority_exec=self.authority_exec, **kwargs)
                self.assertNotEqual(publisher.publish(binding.transition_request).status, "READY")
                self.assertEqual(status.plans, [])

    def test_same_run_for_provider_and_authority_is_rejected(self):
        same = execution(DISPATCH_PROFILE, "5001")
        prepared, binding, client, publisher, status, flat = wire(
            provider_exec=same, authority_exec=same)
        self.assertNotEqual(publisher.publish(binding.transition_request).status, "READY")
        self.assertEqual(status.plans, [])

    def test_stale_target_or_session_drift_blocks_provider_path(self):
        prepared, binding, client, publisher, status, flat = wire(
            provider_exec=self.provider_exec, authority_exec=self.authority_exec)
        inner = publisher.provider_verifier.authenticator.inner
        inner.target_reader.value = {**inner.target_reader.value, "head": {"ref": "x", "sha": "b" * 40}}
        self.assertNotEqual(publisher.publish(binding.transition_request).status, "READY")
        self.assertEqual(status.plans, [])

    def test_replay_after_publication_does_not_create_second_generation(self):
        prepared, binding, client, publisher, status, flat = wire(
            provider_exec=self.provider_exec, authority_exec=self.authority_exec)
        self.assertEqual(publisher.publish(binding.transition_request).status, "READY")
        creates = client.creates
        again = publisher.publish(binding.transition_request)
        self.assertEqual(client.creates, creates, again)

    def test_production_registry_stays_placeholder_and_issue33_not_ready(self):
        registry = pre_adoption(json.loads(REGISTRY_PATH.read_text(encoding="utf-8")))
        self.assertTrue(all(l["identity_state"] == "PLACEHOLDER" for l in registry["loops"]))
        pre = prepare_verified_control_tower_migration(
            registry=registry, verified_transitions=None, lane_presentation={},
            generated_at=CURRENT_TIME, issue_readback=issue())
        self.assertEqual(pre.status, "NOT_WIRED")
        self.assertEqual(issue33_migration_ready(pre.status), "NO")


if __name__ == "__main__":
    unittest.main()
