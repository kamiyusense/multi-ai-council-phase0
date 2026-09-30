import copy
import json
import unittest
from typing import Any
from unittest.mock import Mock, call

from automation.command_bus.semiauto_bootstrap_persistence import (
    persist_semiauto_bootstrap_bundle,
    BootstrapPersistenceResult,
)
from automation.command_bus.jules_semiauto_owner_prepare import JulesSemiAutoAcquireBundle
from automation.command_bus.github_backend import GitHubContentsClient
from automation.command_bus.runtime_transition_coordinator import TransitionRequest

from automation.command_bus.tests.test_jules_semiauto_owner_prepare import request as base_request, context as base_context, session as base_session, target as base_target, NOW
from automation.command_bus.semiauto_identity_bootstrap import prepare_bootstrap_semiauto_acquire
from automation.command_bus.semiauto_runtime_identity import get_canonical_semiauto_loop_id

def fixture_registry() -> dict[str, Any]:
    lane = {
        "loop_id": "fixture-semi-auto",
        "display_name": "ChatGPT Semi-Auto",
        "mode": "SEMI_AUTO",
        "controller_kind": "CHATGPT",
        "worker_kind": "JULES",
        "display_order": 10,
        "enabled": True,
        "safe_detail_ref": "issue:33",
        "identity_state": "PLACEHOLDER",
    }
    return {"schema_version": 1, "loops": [lane]}

def request(**overrides):
    r = base_request()
    default_extras = {
        "origin_generation": 1,
        "origin_loop_id": "human-origin-039",
        "origin_round": 3,
    }
    for key, value in default_extras.items():
        if key not in r:
            r[key] = value
    r.update(overrides)
    r["profile"] = "JULES_CHAT_SEMIAUTO_V2"
    r["origin_correlation_id"] = "req-1"
    return r

def get_valid_bundle() -> JulesSemiAutoAcquireBundle:
    req = request()
    ctx = base_context()
    ctx.pop("loop_id", None)
    ctx["correlation_id"] = req["origin_correlation_id"]
    bundle = prepare_bootstrap_semiauto_acquire(
        registry=fixture_registry(),
        request=req,
        durable_context=ctx,
        session_response=base_session(),
        target_pr_readback=base_target(),
        now=NOW,
    )
    bundle.transition_request.expected_prior_state["expected_target"]["head"] = bundle.owner_event["expected_target_head"]
    return bundle

class MockContentsClient(GitHubContentsClient):
    def __init__(self):
        self.files = {}
        self.create_calls = []

    def get(self, path: str, branch: str = "main"):
        content = self.files.get(path)
        if content is None:
            return None
        mock = Mock()
        mock.text = content
        return mock

    def create(self, path: str, content: str, message: str, branch: str = "main", sha: str = None) -> Any:
        self.create_calls.append((path, content))
        self.files[path] = content

    def list(self, prefix: str, ref: str) -> list[Any]:
        return []

class TestSemiautoBootstrapPersistence(unittest.TestCase):
    def setUp(self):
        self.client = MockContentsClient()
        self.branch = "jules-work/test-branch"

    def test_happy_path_seeded(self):
        bundle = get_valid_bundle()
        result = persist_semiauto_bootstrap_bundle(bundle, self.client, self.branch)

        self.assertEqual(result.status, "READY_FOR_TRUST_PROOF")
        self.assertEqual(len(self.client.create_calls), 2)

        state_path = "automation/command_bus/state/chatgpt-semi-auto-v1.json"
        receipt_path = bundle.owner_event["source_receipt_ref"]
        self.assertEqual(self.client.create_calls[0][0], state_path)
        self.assertEqual(self.client.create_calls[1][0], receipt_path)

    def test_both_recovered_zero_writes(self):
        bundle = get_valid_bundle()
        state_path = "automation/command_bus/state/chatgpt-semi-auto-v1.json"
        receipt_path = bundle.owner_event["source_receipt_ref"]

        self.client.files[state_path] = json.dumps(bundle.initial_state, sort_keys=True, separators=(",", ":"))
        self.client.files[receipt_path] = json.dumps(bundle.source_receipt, sort_keys=True, separators=(",", ":"))

        result = persist_semiauto_bootstrap_bundle(bundle, self.client, self.branch)
        self.assertEqual(result.status, "READY_FOR_TRUST_PROOF")
        self.assertEqual(len(self.client.create_calls), 0)

    def test_conflicting_state_blocks_zero_receipt_writes(self):
        bundle = get_valid_bundle()
        state_path = "automation/command_bus/state/chatgpt-semi-auto-v1.json"

        conflicting_state = copy.deepcopy(bundle.initial_state)
        conflicting_state["stop_requested"] = True
        self.client.files[state_path] = json.dumps(conflicting_state)

        result = persist_semiauto_bootstrap_bundle(bundle, self.client, self.branch)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(len(self.client.create_calls), 0)

    def test_ambiguous_state_create_blocks_zero_receipt_writes(self):
        class BrokenClient(MockContentsClient):
            def create(self, path, content, message, branch="main", sha=None):
                self.create_calls.append((path, content))
                # Do not set self.files[path] to simulate create success but readback fail

        client = BrokenClient()
        bundle = get_valid_bundle()

        result = persist_semiauto_bootstrap_bundle(bundle, client, self.branch)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(len(client.create_calls), 1)
        state_path = "automation/command_bus/state/chatgpt-semi-auto-v1.json"
        self.assertEqual(client.create_calls[0][0], state_path)

    def test_accepted_state_then_conflicting_receipt_blocks_state_untouched(self):
        bundle = get_valid_bundle()
        receipt_path = bundle.owner_event["source_receipt_ref"]

        conflicting_receipt = copy.deepcopy(bundle.source_receipt)
        conflicting_receipt["round"] = 999
        self.client.files[receipt_path] = json.dumps(conflicting_receipt)

        result = persist_semiauto_bootstrap_bundle(bundle, self.client, self.branch)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(len(self.client.create_calls), 1)
        state_path = "automation/command_bus/state/chatgpt-semi-auto-v1.json"
        self.assertEqual(self.client.create_calls[0][0], state_path)

    def test_accepted_state_then_ambiguous_receipt_unknown(self):
        class AmbiguousReceiptClient(MockContentsClient):
            def create(self, path, content, message, branch="main", sha=None):
                self.create_calls.append((path, content))
                if "receipts" not in path:
                    self.files[path] = content

        client = AmbiguousReceiptClient()
        bundle = get_valid_bundle()

        result = persist_semiauto_bootstrap_bundle(bundle, client, self.branch)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(len(client.create_calls), 2)

    def test_later_recovery_from_identical_state_missing_receipt_seeds_receipt(self):
        bundle = get_valid_bundle()
        state_path = "automation/command_bus/state/chatgpt-semi-auto-v1.json"
        self.client.files[state_path] = json.dumps(bundle.initial_state, sort_keys=True, separators=(",", ":"))

        result = persist_semiauto_bootstrap_bundle(bundle, self.client, self.branch)
        self.assertEqual(result.status, "READY_FOR_TRUST_PROOF")
        self.assertEqual(len(self.client.create_calls), 1)
        receipt_path = bundle.owner_event["source_receipt_ref"]
        self.assertEqual(self.client.create_calls[0][0], receipt_path)

    def test_fails_before_write_if_validation_fails(self):
        invalid_bundles = []

        # Tampered loop ID
        b = get_valid_bundle()
        b.initial_state["loop_id"] = "wrong"
        invalid_bundles.append(b)

        # Mismatched command
        b = get_valid_bundle()
        b.owner_event["event_type"] = "RELEASE"
        invalid_bundles.append(b)

        for idx, b in enumerate(invalid_bundles):
            with self.subTest(idx=idx):
                with self.assertRaises(ValueError):
                    persist_semiauto_bootstrap_bundle(b, self.client, self.branch)
                self.assertEqual(len(self.client.create_calls), 0)

    def test_fails_on_invalid_branch(self):
        bundle = get_valid_bundle()
        for bad_branch in ["main", "master", "", None]:
            with self.subTest(branch=bad_branch):
                with self.assertRaises(ValueError):
                    persist_semiauto_bootstrap_bundle(bundle, self.client, bad_branch)

    def test_bundle_is_immutable(self):
        bundle = get_valid_bundle()
        original_initial_state = copy.deepcopy(bundle.initial_state)
        original_owner_event = copy.deepcopy(bundle.owner_event)

        persist_semiauto_bootstrap_bundle(bundle, self.client, self.branch)

        self.assertEqual(bundle.initial_state, original_initial_state)
        self.assertEqual(bundle.owner_event, original_owner_event)

if __name__ == "__main__":
    unittest.main()
