from __future__ import annotations

import copy
import json
import unittest
from datetime import datetime, timezone

from automation.command_bus.github_backend import GitHubContent
from automation.command_bus.jules_semiauto_owner_prepare import (
    prepare_jules_semiauto_acquire,
)
from automation.command_bus.runtime_transition_coordinator import (
    RuntimeTransitionPublisher,
)


NOW = datetime(2026, 9, 28, 4, 0, tzinfo=timezone.utc)
HEAD = "a" * 40
TREE = "b" * 40
BRANCH = "feature/relay-transport-7070955470193506982"
REPO = "kamiyusense/multi-ai-council-phase0"


def request(**changes):
    value = {
        "schema_version": 1,
        "profile": "JULES_CHAT_SEMIAUTO_V1",
        "command_id": "relay-dev-durable-smoke-001",
        "target_repo": REPO,
        "target_branch": BRANCH,
        "expected_target_head": HEAD,
        "expected_target_tree": TREE,
        "allowed_paths": ["tests/relay/test_dispatcher.py"],
        "prompt": "Prepare one bounded static regression test.",
        "created_at": "2026-09-28T03:30:00+00:00",
        "expires_at": "2026-09-28T05:30:00+00:00",
        "retry": 0,
        "fallback": "disabled",
        "merge_allowed": False,
        "force_push_allowed": False,
    }
    value.update(changes)
    return value


def context(**changes):
    value = {
        "loop_id": "chatgpt-semi-auto-v1",
        "correlation_id": "semi-durable-001",
        "holder_id": "chatgpt-controller",
        "target_pr": 4,
        "owner_expires_at": "2026-09-28T06:00:00+00:00",
    }
    value.update(changes)
    return value


def session(**changes):
    value = {
        "name": "sessions/31415926535897932384",
        "createTime": "2026-09-28T03:59:00Z",
        "sourceContext": {
            "githubRepoContext": {
                "startingBranch": BRANCH,
            }
        },
    }
    value.update(changes)
    return value


def target(**changes):
    value = {
        "number": 4,
        "state": "open",
        "merged": False,
        "head": {"ref": BRANCH, "sha": HEAD},
        "repo": {"full_name": REPO},
    }
    value.update(changes)
    return value


def bundle(**kwargs):
    return prepare_jules_semiauto_acquire(
        request=kwargs.pop("request", request()),
        durable_context=kwargs.pop("durable_context", context()),
        session_response=kwargs.pop("session_response", session()),
        target_pr_readback=kwargs.pop("target_pr_readback", target()),
        now=NOW,
        **kwargs,
    )


class Client:
    def __init__(self, prepared):
        self.data = {}
        self.creates = 0
        self.updates = 0
        loop_id = prepared.owner_event["loop_id"]
        state_path = f"automation/command_bus/state/{loop_id}.json"
        self.data[state_path] = GitHubContent(
            state_path,
            json.dumps(
                prepared.initial_state,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "1" * 40,
        )
        receipt_path = prepared.owner_event["source_receipt_ref"]
        self.data[receipt_path] = GitHubContent(
            receipt_path,
            json.dumps(
                prepared.source_receipt,
                sort_keys=True,
                separators=(",", ":"),
            ),
            "2" * 40,
        )

    def get(self, path, ref):
        return self.data.get(path)

    def list(self, prefix, ref):
        return [
            value
            for path, value in sorted(self.data.items())
            if path.startswith(prefix)
        ]

    def create(self, *args, **kwargs):
        self.creates += 1
        raise AssertionError("publisher must stop before writes when authority is absent")

    def update(self, *args, **kwargs):
        self.updates += 1
        raise AssertionError("publisher must stop before writes when authority is absent")


class TargetReader:
    def read_target(self, repository, pr_number):
        return {
            "repo": REPO,
            "pr": 4,
            "head": HEAD,
            "state": "open",
            "merged": False,
        }


class JulesSemiAutoOwnerPrepareTests(unittest.TestCase):
    def test_v1_request_plus_explicit_context_prepares_exact_acquire_bundle(self):
        prepared = bundle()
        event = prepared.owner_event
        self.assertEqual(event["event_type"], "ACQUIRE")
        self.assertEqual(event["owner_role"], "SEMI_AUTO")
        self.assertEqual(event["loop_id"], "chatgpt-semi-auto-v1")
        self.assertEqual(event["expected_pr"], 4)
        self.assertEqual(event["expected_target_head"], HEAD)
        self.assertEqual(event["claimed_at"], "2026-09-28T03:59:00Z")
        self.assertEqual(event["generation"], 1)
        self.assertEqual(event["fencing_token"], 1)

        self.assertEqual(prepared.source_receipt["state"], "DONE")
        self.assertEqual(prepared.source_receipt["retry_count"], 0)
        self.assertFalse(prepared.source_receipt["fallback_used"])
        self.assertEqual(
            prepared.evidence_document["provider_readback"],
            "jules-session:31415926535897932384",
        )
        self.assertEqual(
            prepared.provider_observation_input["state"],
            "RUNNING",
        )
        self.assertNotIn("verified", prepared.provider_observation_input)

        self.assertEqual(prepared.initial_state["state"], "PREPARED")
        self.assertEqual(
            prepared.transition_request.desired_state["state"],
            "RUNNING",
        )
        self.assertEqual(
            prepared.transition_request.desired_state["last_command_id"],
            request()["command_id"],
        )

    def test_v2_origin_correlation_is_bound_to_durable_context(self):
        req = request(
            profile="JULES_CHAT_SEMIAUTO_V2",
            origin_loop_id="claude-night-loop",
            origin_round=7,
            origin_correlation_id="semi-durable-001",
            origin_backend_mode="JULES_BACKEND",
        )
        prepared = bundle(request=req)
        self.assertEqual(
            prepared.owner_event["correlation_id"],
            req["origin_correlation_id"],
        )
        self.assertEqual(
            prepared.owner_event["loop_id"],
            "chatgpt-semi-auto-v1",
        )

    def test_v2_origin_correlation_mismatch_fails_closed(self):
        req = request(
            profile="JULES_CHAT_SEMIAUTO_V2",
            origin_loop_id="claude-night-loop",
            origin_round=7,
            origin_correlation_id="origin-correlation-002",
            origin_backend_mode="JULES_BACKEND",
        )
        with self.assertRaisesRegex(ValueError, "origin_correlation_id"):
            bundle(request=req)

    def test_v2_origin_loop_id_is_not_promoted_to_durable_loop_id(self):
        req = request(
            profile="JULES_CHAT_SEMIAUTO_V2",
            origin_loop_id="claude-origin-loop",
            origin_round=7,
            origin_correlation_id="semi-durable-001",
            origin_backend_mode="JULES_BACKEND",
        )
        prepared = bundle(request=req)
        self.assertEqual(prepared.owner_event["loop_id"], "chatgpt-semi-auto-v1")
        self.assertNotEqual(
            prepared.owner_event["loop_id"],
            req["origin_loop_id"],
        )

    def test_human_loop_number_is_not_used_as_durable_round_or_loop_id(self):
        prepared = bundle()
        self.assertEqual(prepared.initial_state["round"], 0)
        self.assertEqual(prepared.initial_state["max_rounds"], 1)
        self.assertNotIn("039", prepared.owner_event["loop_id"])
        self.assertNotIn("loop_number", prepared.transition_request.desired_state)

    def test_target_pr_must_match_number_branch_head_and_open_state(self):
        cases = [
            (target(number=5), "number mismatch"),
            (target(head={"ref": "feature/other", "sha": HEAD}), "head branch mismatch"),
            (target(head={"ref": BRANCH, "sha": "c" * 40}), "head SHA mismatch"),
            (target(state="closed"), "OPEN non-merged"),
            (target(merged=True), "OPEN non-merged"),
        ]
        for raw, message in cases:
            with self.subTest(message=message):
                with self.assertRaisesRegex(ValueError, message):
                    bundle(target_pr_readback=raw)

    def test_session_branch_mismatch_fails_closed(self):
        bad = session()
        bad["sourceContext"]["githubRepoContext"]["startingBranch"] = "feature/other"
        with self.assertRaisesRegex(ValueError, "branch mismatch"):
            bundle(session_response=bad)

    def test_owner_lease_is_bounded_from_provider_acceptance_time(self):
        with self.assertRaisesRegex(ValueError, "expire after"):
            bundle(
                durable_context=context(
                    owner_expires_at="2026-09-28T03:58:00+00:00"
                )
            )
        with self.assertRaisesRegex(ValueError, "bounded maximum"):
            bundle(
                durable_context=context(
                    owner_expires_at="2026-09-28T08:30:00+00:00"
                )
            )

    def test_unknown_or_extra_durable_context_fields_fail_closed(self):
        bad = context()
        bad["private_chat_url"] = "https://private.example/chat"
        with self.assertRaisesRegex(ValueError, "shape"):
            bundle(durable_context=bad)

    def test_current_v1_retry_fallback_and_safe_target_validation_is_reused(self):
        with self.assertRaisesRegex(ValueError, "retry/fallback"):
            bundle(request=request(retry=1))
        with self.assertRaisesRegex(ValueError, "default branch"):
            bundle(request=request(target_branch="main"))

    def test_live_publisher_remains_not_wired_without_owner_authority(self):
        prepared = bundle()
        client = Client(prepared)
        publisher = RuntimeTransitionPublisher(
            client,
            branch="feature/runtime-data",
            target_reader=TargetReader(),
            owner_authority=None,
            provider_verifier=None,
            status_boundary=None,
        )
        result = publisher.publish(prepared.transition_request)
        self.assertEqual((result.status, result.stage), ("NOT_WIRED", "authority"))
        self.assertEqual(client.creates, 0)
        self.assertEqual(client.updates, 0)

    def test_prepare_does_not_mutate_inputs(self):
        req = request()
        ctx = context()
        sess = session()
        tgt = target()
        originals = tuple(copy.deepcopy(x) for x in (req, ctx, sess, tgt))
        bundle(
            request=req,
            durable_context=ctx,
            session_response=sess,
            target_pr_readback=tgt,
        )
        self.assertEqual((req, ctx, sess, tgt), originals)


if __name__ == "__main__":
    unittest.main()
