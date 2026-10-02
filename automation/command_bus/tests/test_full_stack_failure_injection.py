"""Failure injection against the REAL durable records of the integrated stack.

The matrix below mutates a real schema-v3 claim and its real numbered command
(Loop 131, committed on the carrier) one field at a time.  Every mutation must be
rejected (fail closed) and every case is counted, so the test cannot pass by
silently running zero mutations.  No network, no Jules, no GitHub.

It covers the "durable record" half of the failure list: malformed claim,
malformed command, moved target head, changed target tree, wrong work branch,
wrong lane, stale/legacy claim schema, claim not in the pre-dispatch state,
retry/fallback tampering, a blended origin+carrier request shape, and expiry.
Owner / generation / lease / receipt / budget failures are exercised on a real
git remote in ``test_cross_lane_isolation`` and ``test_claude_jules_*``.
"""
from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from automation.command_bus.jules_api_request import REQUIRED_KEYS, validate_request
from automation.command_bus.loop_id_claim import validate_claim, verify_command_claim

ROOT = Path(__file__).resolve().parents[3]
BUS = ROOT / "automation" / "command_bus"
LOOP = "131"
CLAIM = json.loads((BUS / "loop_id_claims" / f"{LOOP}.json").read_text(encoding="utf-8"))
COMMAND = json.loads(
    (BUS / "jules_api_requests" / f"{CLAIM['command_id']}.json").read_text(encoding="utf-8")
)
NOW = datetime.fromisoformat(COMMAND["created_at"]) + timedelta(minutes=1)
OTHER_SHA = "0123456789abcdef0123456789abcdef01234567"


def command(**changes):
    value = copy.deepcopy(COMMAND)
    value.update(changes)
    return value


def claim(**changes):
    value = copy.deepcopy(CLAIM)
    value.update(changes)
    return value


class RealRecordsAreValidBaseline(unittest.TestCase):
    def test_the_real_pair_is_accepted(self):
        validate_request(COMMAND, now=NOW)
        validated = verify_command_claim(COMMAND, CLAIM)
        self.assertEqual(validated["loop_id"], LOOP)


class MalformedRequestsFailClosed(unittest.TestCase):
    def test_every_missing_key_is_rejected(self):
        cases = 0
        for key in sorted(REQUIRED_KEYS):
            broken = command()
            del broken[key]
            with self.subTest(removed=key):
                with self.assertRaises(ValueError):
                    validate_request(broken, now=NOW)
            cases += 1
        self.assertEqual(cases, len(REQUIRED_KEYS))

    def test_unknown_keys_and_blended_origin_shape_are_rejected(self):
        blends = {
            "extra key": {"surprise": 1},
            "origin identity inside the dispatch request": {
                "origin_loop_id": "loop-1", "origin_round": 1,
                "origin_correlation_id": "c", "origin_generation": 1,
            },
        }
        for label, extra in blends.items():
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    validate_request(command(**extra), now=NOW)

    def test_field_corruptions_are_rejected(self):
        corruptions = {
            "profile": "JULES_CHAT_SEMIAUTO_V1",
            "schema_version": 3,
            "target_repo": "someone/else",
            "target_branch": "main",
            "work_branch": "feature/chat-work-command-bus",
            "expected_target_head": "not-a-sha",
            "expected_target_tree": "XYZ",
            "allowed_paths": [],
            "prompt": "",
            "retry": 1,
            "fallback": "enabled",
            "merge_allowed": True,
            "force_push_allowed": True,
            "expires_at": COMMAND["created_at"],
        }
        for field, value in corruptions.items():
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    validate_request(command(**{field: value}), now=NOW)
        self.assertEqual(len(corruptions), 14)

    def test_expired_and_traversal_requests_are_rejected(self):
        with self.assertRaises(ValueError):
            validate_request(COMMAND, now=datetime.fromisoformat(COMMAND["expires_at"]) + timedelta(seconds=1))
        with self.assertRaises(ValueError):
            validate_request(command(allowed_paths=["../outside.txt"]), now=NOW)


class MalformedClaimsFailClosed(unittest.TestCase):
    def test_every_missing_or_extra_claim_key_is_rejected(self):
        for key in sorted(CLAIM):
            broken = claim()
            del broken[key]
            with self.subTest(removed=key):
                with self.assertRaises(ValueError):
                    validate_claim(broken)
        with self.assertRaises(ValueError):
            validate_claim(claim(surprise=True))

    def test_claim_field_corruptions_are_rejected(self):
        corruptions = {
            "schema_version": 9,
            "loop_number": -1,
            "loop_id": "13",
            "lane_id": "J-PURPLE",
            "lane_display": "💜",
            "task_id": "another-task",
            "command_id": "relay-dev-loop-132-autoloop-operator-quickstart",
            "work_branch": "jules-work/other",
            "target_branch": "",
            "expected_target_head": "zz",
            "expected_target_tree": "zz",
            "state": "DISPATCHED",
            "claimed_at": "yesterday",
            "duplicate_guard": "anything goes",
            "retry": 1,
            "fallback": "enabled",
        }
        for field, value in corruptions.items():
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    validate_claim(claim(**{field: value}))
        self.assertEqual(len(corruptions), 16)


class CommandClaimBindingFailsClosed(unittest.TestCase):
    def test_moved_head_changed_tree_wrong_branch_wrong_command_are_rejected(self):
        mismatches = {
            "candidate head moved": command(expected_target_head=OTHER_SHA),
            "target tree changed": command(expected_target_tree=OTHER_SHA),
            "different target branch": command(target_branch="claude/another-target"),
            "different work branch": command(work_branch="jules-work/relay-dev-loop-131-other"),
            "different command": command(command_id="relay-dev-loop-132-autoloop-operator-quickstart"),
            "retry tampered": command(retry=1),
            "fallback tampered": command(fallback="enabled"),
        }
        for label, request in mismatches.items():
            with self.subTest(label):
                with self.assertRaises(ValueError):
                    verify_command_claim(request, CLAIM)
        self.assertEqual(len(mismatches), 7)

    def test_claim_that_is_not_a_fresh_dispatchable_claim_is_rejected(self):
        with self.assertRaises(ValueError):  # already past CLAIMED
            verify_command_claim(COMMAND, claim(state="HISTORICAL_BACKFILL"))
        legacy = {**claim(), "schema_version": 2, "lane_id": "J-RED", "lane_display": "❤️"}
        with self.assertRaises(ValueError):  # legacy schema cannot authorise a new dispatch
            verify_command_claim(COMMAND, legacy)
        with self.assertRaises(ValueError):  # claim of another loop number
            verify_command_claim(COMMAND, json.loads((BUS / "loop_id_claims" / "130.json").read_text(encoding="utf-8")))

    def test_a_non_numbered_request_cannot_borrow_a_claim(self):
        with self.assertRaises(ValueError):
            verify_command_claim(command(command_id="chat-jules-001"), CLAIM)


if __name__ == "__main__":
    unittest.main()
