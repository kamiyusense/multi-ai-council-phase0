"""STATIC checks of the per-lane identity contract (hypothetical DURABLE fixtures only)."""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from automation.command_bus.lane_stable_identity import LANE_SHAPES, validate_lane_stable_identity as validate

ROOT = Path(__file__).resolve().parents[3]
PROD = json.loads((ROOT / "automation/command_bus/config/control_tower_registry.json").read_text(encoding="utf-8"))
IDS = {"chat-work": "chat-work-semi-auto", "claude-jules": "claude-jules-auto", "symphony-codex": "symphony-codex-auto"}
REQUEST = {"origin_loop_id": "relay-dev-loop-137", "command_id": "cmd-1", "target_branch": "b", "target_repo": "r/r"}


def durable(lane):
    registry = copy.deepcopy(PROD)
    next(e for e in registry["loops"] if e["loop_id"] == IDS[lane])["identity_state"] = "DURABLE"
    return registry


def context(lane, **extra):
    return {"loop_id": IDS[lane], "correlation_id": "corr-1", "target_pr": 1, **extra}


class ContractTests(unittest.TestCase):
    def test_a_hypothetical_durable_lane_passes_with_its_own_id_only(self):
        for lane in LANE_SHAPES:
            self.assertEqual(validate(lane, registry=durable(lane), request=REQUEST, durable_context=context(lane)), IDS[lane])

    def test_reserved_placeholder_names_never_pass(self):
        for lane in LANE_SHAPES:
            with self.assertRaises(ValueError):
                validate(lane, registry=PROD, request=REQUEST, durable_context=context(lane))

    def test_production_registry_fails_closed_for_every_lane(self):
        for lane in LANE_SHAPES:
            with self.assertRaises(ValueError):
                validate(lane, registry=PROD, request=REQUEST, durable_context=context(lane))

    def test_a_context_naming_another_lane_or_a_numeric_or_request_identity_is_rejected(self):
        for lane in LANE_SHAPES:
            registry = durable(lane)
            for bad in ("chatgpt-semi-auto", "1234", REQUEST["command_id"], REQUEST["origin_loop_id"], "corr-1"):
                ctx = context(lane, loop_id=bad)
                req = dict(REQUEST)
                with self.assertRaises(ValueError, msg=(lane, bad)):
                    validate(lane, registry=registry, request=req, durable_context=ctx)

    def test_two_lanes_of_the_same_shape_or_a_disabled_lane_fail(self):
        registry = durable("claude-jules")
        twin = copy.deepcopy(next(e for e in registry["loops"] if e["loop_id"] == "claude-jules-auto"))
        twin.update(loop_id="claude-jules-two", display_order=99)
        registry["loops"].append(twin)
        with self.assertRaises(ValueError):
            validate("claude-jules", registry=registry, request=REQUEST, durable_context=context("claude-jules"))
        disabled = durable("symphony-codex")
        next(e for e in disabled["loops"] if e["loop_id"] == "symphony-codex-auto")["enabled"] = False
        with self.assertRaises(ValueError):
            validate("symphony-codex", registry=disabled, request=REQUEST, durable_context=context("symphony-codex"))

    def test_the_frozen_claude_claude_lane_has_no_contract(self):
        self.assertNotIn("claude-claude", LANE_SHAPES)
        with self.assertRaises(ValueError):
            validate("claude-claude", registry=PROD, request=REQUEST, durable_context=context("claude-jules"))

    def test_the_contract_does_not_touch_the_registry_or_the_chat_jules_lane(self):
        before = json.dumps(PROD, sort_keys=True)
        with self.assertRaises(ValueError):
            validate("claude-jules", registry=PROD, request=REQUEST, durable_context=context("claude-jules"))
        self.assertEqual(before, json.dumps(PROD, sort_keys=True))
        self.assertNotIn("chat-jules", LANE_SHAPES)


if __name__ == "__main__":
    unittest.main()
