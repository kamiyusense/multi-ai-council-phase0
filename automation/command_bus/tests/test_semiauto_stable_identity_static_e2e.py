"""Offline composition proof; fixture identity and authorities are NOT live."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from automation.command_bus.control_tower_durable_collector import ControlTowerDurableCollector
from automation.command_bus.control_tower_registration import assess_registration_readiness
from automation.command_bus.jules_direct_readback_authenticator import JulesDirectReadbackAuthenticator
from automation.command_bus.jules_provider_readback_candidate import (
    bind_jules_active_provider_readback,
    prepare_jules_provider_readback_candidate,
)
from automation.command_bus.jules_provider_verification_source import prepare_jules_provider_verification_source
from automation.command_bus.semiauto_stable_identity import prepare_adopted_semiauto_acquire
from automation.command_bus.runtime_state_initializer import RuntimeStateInitializer
from automation.command_bus.runtime_transition_coordinator import AuthorizedOwnerContext, RuntimeTransitionPublisher
from automation.command_bus.runtime_verifier_sources import SourceBoundProviderVerifier
from automation.command_bus.semiauto_stable_identity import validate_semiauto_stable_identity
from automation.command_bus.tests.test_jules_semiauto_owner_prepare import (
    NOW, REPO, HEAD, BRANCH, context, request, session, target,
)
from automation.command_bus.tests.test_runtime_transition_publisher import Client

LOOP_ID = "chatgpt-semi-auto-v1"
READBACK_TIME = "2026-09-28T04:05:00Z"
CURRENT_TIME = "2026-09-28T04:10:00+00:00"
REGISTRY_PATH = Path(__file__).parents[1] / "config" / "control_tower_registry.json"


def fixture_registry(*, loop_id=LOOP_ID, identity_state="DURABLE"):
    return {"schema_version": 1, "loops": [{
        "loop_id": loop_id, "display_name": "STATIC fixture lane", "mode": "SEMI_AUTO",
        "controller_kind": "CHATGPT", "worker_kind": "JULES", "display_order": 10,
        "enabled": True, "safe_detail_ref": "issue:33", "identity_state": identity_state,
    }]}


class Clock:
    def now(self):
        return CURRENT_TIME


class TargetReader:
    def __init__(self, value):
        self.value = copy.deepcopy(value)

    def read_target(self, repository, pr_number):
        return copy.deepcopy(self.value)


class SessionReader:
    def __init__(self, value):
        self.value = copy.deepcopy(value)

    def read_session(self, session_id):
        return copy.deepcopy(self.value)


class SourceReader:
    def __init__(self, value):
        self.value = copy.deepcopy(value)

    def read(self, source_ref):
        return copy.deepcopy(self.value) if self.value["source_ref"] == source_ref else None


class FixtureOwnerAuthority:
    """A test-only injected authority; never a production grant."""

    def authorize(self, event, prior_state, target, receipt, chain):
        return AuthorizedOwnerContext(**{
            key: event[key] for key in AuthorizedOwnerContext.__dataclass_fields__
        })


class PrepareOnlyStatus:
    def __init__(self):
        self.plans = []

    def prepare(self, plan):
        self.plans.append(plan)


def build_chain(*, registry=None, req=None, ctx=None, session_get=None, rich_target=None):
    registry = registry or fixture_registry()
    req = req or request(
        profile="JULES_CHAT_SEMIAUTO_V2", origin_loop_id="human-origin-039",
        origin_round=3, origin_correlation_id="semi-durable-001", origin_generation=1,
    )
    if ctx is None:
        ctx = context()
        ctx.pop("loop_id", None)
    rich_target = rich_target or target()
    prepared = prepare_adopted_semiauto_acquire(
        registry=registry,
        request=req, durable_context=ctx, session_response=session(),
        target_pr_readback=rich_target, now=NOW,
    )
    session_get = session_get or {
        **session(), "state": "RUNNING", "updateTime": READBACK_TIME,
        "sourceContext": {
            "source": f"sources/github/{REPO}",
            "githubRepoContext": {"startingBranch": BRANCH},
        },
    }
    candidate = prepare_jules_provider_readback_candidate(
        bundle=prepared, session_readback=session_get,
    )
    binding = bind_jules_active_provider_readback(bundle=prepared, candidate=candidate)
    normalized = prepare_jules_provider_verification_source(
        provider_observation_input=binding.provider_observation_input,
        evidence_document=binding.evidence_document,
        source_receipt=prepared.source_receipt,
        session_id=prepared.acceptance_session_id,
        proof_refs=list(candidate.proof_refs),
    )
    # Test fixture simulates a separately verified source; the normalizer
    # itself can only produce UNKNOWN and cannot issue this assertion.
    source = {**normalized, "verification_state": "VERIFIED"}
    authenticator = JulesDirectReadbackAuthenticator(
        session_reader=SessionReader(session_get),
        target_reader=TargetReader(rich_target), clock=Clock(),
        expected_session_create_time=prepared.owner_event["claimed_at"],
    )
    verifier = SourceBoundProviderVerifier(SourceReader(source), authenticator)
    client = Client()
    initialized = RuntimeStateInitializer(client, branch="fixture/runtime-data").create(prepared.initial_state)
    assert initialized.status == "ACCEPTED", initialized
    client.put(prepared.owner_event["source_receipt_ref"], prepared.source_receipt)
    flat_target = {
        "repo": REPO, "pr": 4, "head": HEAD, "state": "open", "merged": False,
    }
    status = PrepareOnlyStatus()
    publisher = RuntimeTransitionPublisher(
        client, branch="fixture/runtime-data", target_reader=TargetReader(flat_target),
        owner_authority=FixtureOwnerAuthority(), provider_verifier=verifier,
        status_boundary=status, clock=Clock(),
    )
    return prepared, binding, normalized, source, client, publisher, status, flat_target


class SemiAutoStableIdentityStaticE2ETests(unittest.TestCase):
    def test_full_static_chain_and_registration_gate(self):
        prepared, binding, normalized, source, client, publisher, status, flat_target = build_chain()
        self.assertEqual(normalized["verification_state"], "UNKNOWN")
        self.assertEqual(prepared.initial_state["state"], "PREPARED")
        self.assertEqual(prepared.owner_event["generation"], 1)
        self.assertEqual(prepared.owner_event["loop_id"], LOOP_ID)
        self.assertEqual(prepared.source_receipt["retry_count"], 0)
        self.assertFalse(prepared.source_receipt["fallback_used"])
        published = publisher.publish(binding.transition_request)
        self.assertEqual(published.status, "READY", published)
        self.assertEqual(published.status_plan.display_state, "SEMI_AUTO")
        self.assertEqual(len(status.plans), 1)
        collector = ControlTowerDurableCollector(
            client, ref="fixture/runtime-data", target_reader=TargetReader(flat_target),
            clock=Clock(),
        )
        collected = collector.collect_transition(LOOP_ID)
        self.assertEqual(collected.status, "COLLECTED", collected)
        self.assertEqual(collected.transition.status, "VALID")
        self.assertEqual(collected.transition.projection.display_state, "SEMI_AUTO")
        self.assertEqual(
            assess_registration_readiness(fixture_registry(), {LOOP_ID: collected.transition}).status,
            "READY",
        )
        production_registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        self.assertEqual(assess_registration_readiness(production_registry, None).status, "NOT_WIRED")

    def test_identity_is_injected_not_derived_from_request(self):
        req = request(
            profile="JULES_CHAT_SEMIAUTO_V2", origin_loop_id="human-origin-039",
            origin_round=3, origin_correlation_id="semi-durable-001", origin_generation=1,
        )
        # Any caller-provided loop_id is rejected by the adopted prepare path.
        for bad_context in (
            context(loop_id="other-lane"), context(loop_id="human-origin-039"),
            context(loop_id=req["command_id"]), context(loop_id="semi-durable-001"),
            context(loop_id=LOOP_ID),
        ):
            with self.subTest(bad_context=bad_context):
                with self.assertRaisesRegex(ValueError, "caller cannot supply loop_id"):
                    build_chain(req=req, ctx=bad_context)
        with self.assertRaisesRegex(ValueError, "not DURABLE"):
            build_chain(registry=fixture_registry(identity_state="PLACEHOLDER"))
        production_registry = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
        with self.assertRaises(ValueError):
            validate_semiauto_stable_identity(
                registry=production_registry, request=req, durable_context=context(loop_id=LOOP_ID),
            )

    def test_v2_origin_target_session_and_provider_mismatch_fail_before_publication(self):
        bad_requests = [request(
            profile="JULES_CHAT_SEMIAUTO_V2", origin_loop_id="human-origin-039",
            origin_round=3, origin_correlation_id="wrong", origin_generation=1,
        ), request(
            profile="JULES_CHAT_SEMIAUTO_V2", origin_loop_id="human-origin-039",
            origin_round=3, origin_correlation_id="semi-durable-001", origin_generation=1,
            expected_target_head="b" * 40,
        )]
        for bad in bad_requests:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    build_chain(req=bad)
        for bad in (
            target(number=5), target(head={"ref": BRANCH, "sha": "b" * 40}),
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    build_chain(rich_target=bad)
        base = {**session(), "state": "RUNNING", "updateTime": READBACK_TIME}
        for bad in (
            {**base, "name": "sessions/other"},
            {**base, "updateTime": "2026-09-28T06:00:00Z"},
        ):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    build_chain(session_get=bad)
        with self.assertRaisesRegex(ValueError, "explicit RUNNING"):
            build_chain(session_get={**base, "state": "COMPLETED"})

    def test_missing_source_or_independent_authenticator_never_publishes(self):
        prepared, binding, normalized, source, client, publisher, status, _ = build_chain()
        publisher.provider_verifier = SourceBoundProviderVerifier(SourceReader(source), None)
        self.assertNotEqual(publisher.publish(binding.transition_request).status, "READY")
        self.assertEqual((client.creates, client.updates), (1, 0))
        self.assertEqual(status.plans, [])
        publisher.provider_verifier = SourceBoundProviderVerifier(SourceReader(normalized), None)
        self.assertNotEqual(publisher.publish(binding.transition_request).status, "READY")

    def test_collector_missing_durable_material_is_unknown(self):
        for missing in ("receipt", "evidence", "owner", "observation"):
            with self.subTest(missing=missing):
                prepared, binding, _, _, client, publisher, _, flat_target = build_chain()
                self.assertEqual(publisher.publish(binding.transition_request).status, "READY")
                if missing == "receipt":
                    key = prepared.owner_event["source_receipt_ref"]
                elif missing == "evidence":
                    key = prepared.owner_event["evidence_refs"][0]
                elif missing == "owner":
                    key = f"automation/command_bus/loop_owner_events/{LOOP_ID}/000001.json"
                else:
                    key = f"automation/command_bus/loop_owner_observations/{LOOP_ID}/000001.json"
                client.data.pop(key)
                result = ControlTowerDurableCollector(
                    client, ref="fixture/runtime-data", target_reader=TargetReader(flat_target),
                    clock=Clock(),
                ).collect_transition(LOOP_ID)
                self.assertNotEqual(result.status, "COLLECTED", result)

    def test_independent_authenticator_rejects_drift_and_unfresh_source(self):
        prepared, binding, normalized, source, client, publisher, status, _ = build_chain()
        authenticator = publisher.provider_verifier.authenticator
        expected = dict(source)
        self.assertIsNotNone(authenticator.authenticate(source, expected=expected))
        original_session = copy.deepcopy(authenticator.session_reader.value)
        original_target = copy.deepcopy(authenticator.target_reader.value)
        for changed in (
            {**original_session, "createTime": "2026-09-28T03:58:00Z"},
            {**original_session, "updateTime": "2026-09-28T04:06:00Z"},
            {**original_session, "state": "COMPLETED"},
            {**original_session, "name": "sessions/other"},
        ):
            with self.subTest(changed=changed):
                authenticator.session_reader.value = changed
                self.assertIsNone(authenticator.authenticate(source, expected=expected))
        authenticator.session_reader.value = original_session
        authenticator.target_reader.value = target(head={"ref": BRANCH, "sha": "b" * 40})
        self.assertIsNone(authenticator.authenticate(source, expected=expected))
        authenticator.target_reader.value = original_target
        for bad_source in (
            {**source, "observed_at": "2026-09-28T04:20:00Z"},
            {**source, "expires_at": CURRENT_TIME},
            {**source, "proof_refs": [source["source_ref"]]},
        ):
            with self.subTest(bad_source=bad_source):
                self.assertIsNone(authenticator.authenticate(bad_source, expected=bad_source))
        self.assertEqual((client.creates, client.updates), (1, 0))
        self.assertEqual(status.plans, [])

    def test_identity_is_lane_scoped_across_request_turns(self):
        registry = fixture_registry()
        cases = (
            (
                request(
                    command_id="static-command-001",
                    profile="JULES_CHAT_SEMIAUTO_V2",
                    origin_loop_id="human-origin-039",
                    origin_round=3,
                    origin_correlation_id="semi-durable-001",
                    origin_generation=1,
                ),
                context(correlation_id="semi-durable-001"),
            ),
            (
                request(
                    command_id="static-command-002",
                    profile="JULES_CHAT_SEMIAUTO_V2",
                    origin_loop_id="human-origin-040",
                    origin_round=4,
                    origin_correlation_id="semi-durable-002",
                    origin_generation=2,
                ),
                context(correlation_id="semi-durable-002"),
            ),
        )
        observed_correlations = []
        for req, ctx in cases:
            ctx.pop("loop_id", None)
            bundle = prepare_adopted_semiauto_acquire(
                registry=registry, request=req, durable_context=ctx,
                session_response=session(), target_pr_readback=target(), now=NOW,
            )
            self.assertEqual(bundle.owner_event["loop_id"], LOOP_ID)
            self.assertEqual(
                bundle.owner_event["correlation_id"],
                req["origin_correlation_id"],
            )
            observed_correlations.append(bundle.owner_event["correlation_id"])
        self.assertNotEqual(cases[0][0]["command_id"], cases[1][0]["command_id"])
        self.assertEqual(
            observed_correlations,
            ["semi-durable-001", "semi-durable-002"],
        )

    def test_numeric_session_or_human_number_cannot_be_adopted(self):
        for numeric in ("039", "31415926535897932384", "4"):
            with self.subTest(numeric=numeric):
                with self.assertRaises(ValueError):
                    validate_semiauto_stable_identity(
                        registry=fixture_registry(loop_id=numeric), request=request(),
                        durable_context=context(loop_id=numeric),
                    )

    def test_duplicate_chatgpt_lane_is_not_an_identity_source(self):
        registry = fixture_registry()
        duplicate = copy.deepcopy(registry["loops"][0])
        duplicate["loop_id"] = "fixture-other-chatgpt-lane"
        duplicate["display_order"] = 11
        registry["loops"].append(duplicate)
        with self.assertRaises(ValueError):
            validate_semiauto_stable_identity(
                registry=registry, request=request(),
                durable_context=context(loop_id=LOOP_ID),
            )
