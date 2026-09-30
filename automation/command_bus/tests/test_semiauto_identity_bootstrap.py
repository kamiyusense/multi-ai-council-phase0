import unittest
import copy
from typing import Any
from datetime import datetime, timezone, timedelta
import json
from pathlib import Path

from automation.command_bus.semiauto_identity_bootstrap import prepare_bootstrap_semiauto_acquire
from automation.command_bus.semiauto_runtime_identity import get_canonical_semiauto_loop_id
from automation.command_bus.tests.test_jules_semiauto_owner_prepare import request as base_request, context, session, target, NOW

def request(**overrides):
    r = base_request()
    # Ensure origin_generation, origin_loop_id, origin_round are populated since base_request may miss them if it targets v1 mostly.
    default_extras = {
        "origin_generation": 1,
        "origin_loop_id": "human-origin-039",
        "origin_round": 3
    }
    for k, v in default_extras.items():
        if k not in r:
            r[k] = v
    r.update(overrides)
    return r

class TestSemiautoIdentityBootstrap(unittest.TestCase):
    def fixture_registry(self, **overrides) -> dict[str, Any]:
        lane = {
            "loop_id": "fixture-semi-auto",
            "display_name": "ChatGPT Semi-Auto",
            "mode": "SEMI_AUTO",
            "controller_kind": "CHATGPT",
            "worker_kind": "JULES",
            "display_order": 10,
            "enabled": True,
            "safe_detail_ref": "issue:33",
            "identity_state": overrides.pop("identity_state", "PLACEHOLDER"),
        }
        lane.update(overrides)
        return {"schema_version": 1, "loops": [lane]}

    def test_bootstrap_accepts_placeholder_registry_and_injects_canonical_id(self):
        registry = self.fixture_registry()
        req = request(profile="JULES_CHAT_SEMIAUTO_V2", origin_correlation_id="req-1")
        ctx = context()
        ctx.pop("loop_id", None)
        ctx["correlation_id"] = "req-1"
        bundle = prepare_bootstrap_semiauto_acquire(
            registry=registry, request=req, durable_context=ctx,
            session_response=session(), target_pr_readback=target(), now=NOW,
        )
        canonical_id = get_canonical_semiauto_loop_id()
        self.assertEqual(bundle.owner_event["loop_id"], canonical_id)
        self.assertEqual(bundle.source_receipt["loop_id"], canonical_id)
        self.assertEqual(bundle.evidence_document["loop_id"], canonical_id)
        self.assertEqual(bundle.provider_observation_input["loop_id"], canonical_id)
        self.assertEqual(bundle.initial_state["loop_id"], canonical_id)
        self.assertEqual(bundle.transition_request.desired_state["loop_id"], canonical_id)

    def test_bootstrap_rejects_durable_registry_to_prevent_bypass(self):
        registry = self.fixture_registry(identity_state="DURABLE")
        ctx = context()
        ctx.pop("loop_id", None)
        with self.assertRaisesRegex(ValueError, "already DURABLE, use adopted path"):
            prepare_bootstrap_semiauto_acquire(
                registry=registry, request=request(), durable_context=ctx,
                session_response=session(), target_pr_readback=target(), now=NOW,
            )

    def test_bootstrap_rejects_missing_or_duplicate_lane(self):
        registry = self.fixture_registry()
        registry["loops"].pop()
        ctx = context()
        ctx.pop("loop_id", None)
        with self.assertRaisesRegex(ValueError, "exactly one enabled ChatGPT"):
            prepare_bootstrap_semiauto_acquire(
                registry=registry, request=request(), durable_context=ctx,
                session_response=session(), target_pr_readback=target(), now=NOW,
            )

        registry = self.fixture_registry()
        duplicate = copy.deepcopy(registry["loops"][0])
        duplicate["loop_id"] = "fixture-other-chatgpt-lane"
        duplicate["display_order"] = 99
        registry["loops"].append(duplicate)
        with self.assertRaisesRegex(ValueError, "exactly one enabled ChatGPT"):
            prepare_bootstrap_semiauto_acquire(
                registry=registry, request=request(), durable_context=ctx,
                session_response=session(), target_pr_readback=target(), now=NOW,
            )

    def test_bootstrap_rejects_caller_supplied_loop_id(self):
        ctx = context()
        ctx["loop_id"] = "some-id"
        with self.assertRaisesRegex(ValueError, "caller cannot supply loop_id"):
            prepare_bootstrap_semiauto_acquire(
                registry=self.fixture_registry(), request=request(), durable_context=ctx,
                session_response=session(), target_pr_readback=target(), now=NOW,
            )

    def test_bootstrap_with_production_registry_file(self):
        reg_path = Path("automation/command_bus/config/control_tower_registry.json")
        production_registry = json.loads(reg_path.read_text(encoding="utf-8"))

        req = request(profile="JULES_CHAT_SEMIAUTO_V2", origin_correlation_id="req-1")
        ctx = context()
        ctx.pop("loop_id", None)
        ctx["correlation_id"] = "req-1"

        bundle = prepare_bootstrap_semiauto_acquire(
            registry=production_registry, request=req, durable_context=ctx,
            session_response=session(), target_pr_readback=target(), now=NOW,
        )
        canonical_id = get_canonical_semiauto_loop_id()
        self.assertEqual(bundle.owner_event["loop_id"], canonical_id)
