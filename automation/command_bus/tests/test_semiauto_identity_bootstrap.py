import copy
import json
import unittest
from pathlib import Path
from typing import Any

from automation.command_bus.semiauto_identity_bootstrap import prepare_bootstrap_semiauto_acquire
from automation.command_bus.semiauto_runtime_identity import get_canonical_semiauto_loop_id
from automation.command_bus.tests.test_jules_semiauto_owner_prepare import (
    NOW,
    context,
    request as base_request,
    session,
    target,
)


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

    def prepare(self, *, registry=None, req=None, ctx=None, sess=None, tgt=None):
        registry = registry or self.fixture_registry()
        req = req or request(
            profile="JULES_CHAT_SEMIAUTO_V2",
            origin_correlation_id="req-1",
        )
        if ctx is None:
            ctx = context()
            ctx.pop("loop_id", None)
            ctx["correlation_id"] = req.get(
                "origin_correlation_id",
                ctx["correlation_id"],
            )
        return prepare_bootstrap_semiauto_acquire(
            registry=registry,
            request=req,
            durable_context=ctx,
            session_response=sess or session(),
            target_pr_readback=tgt or target(),
            now=NOW,
        )

    def test_bootstrap_accepts_placeholder_registry_and_injects_canonical_id(self):
        bundle = self.prepare()
        canonical_id = get_canonical_semiauto_loop_id()
        artifacts = (
            bundle.owner_event,
            bundle.source_receipt,
            bundle.evidence_document,
            bundle.provider_observation_input,
            bundle.initial_state,
            bundle.transition_request.expected_prior_state,
            bundle.transition_request.desired_state,
        )
        for artifact in artifacts:
            self.assertEqual(artifact["loop_id"], canonical_id)
        self.assertEqual(bundle.acceptance_session_id, "31415926535897932384")
        self.assertEqual(bundle.target_pr, 4)
        self.assertEqual(bundle.owner_event["correlation_id"], "req-1")
        self.assertEqual(bundle.owner_event["expected_pr"], 4)
        self.assertEqual(
            bundle.owner_event["expected_target_head"],
            "a" * 40,
        )

    def test_bootstrap_registry_placeholder_id_is_never_identity_authority(self):
        canonical_id = get_canonical_semiauto_loop_id()
        for placeholder in (
            canonical_id,
            "chatgpt-semi-auto",
            "human-origin-039",
            "085",
        ):
            with self.subTest(placeholder=placeholder):
                bundle = self.prepare(
                    registry=self.fixture_registry(loop_id=placeholder),
                )
                self.assertEqual(bundle.owner_event["loop_id"], canonical_id)

    def test_bootstrap_rejects_durable_registry_to_prevent_bypass(self):
        ctx = context()
        ctx.pop("loop_id", None)
        with self.assertRaisesRegex(ValueError, "already DURABLE, use adopted path"):
            prepare_bootstrap_semiauto_acquire(
                registry=self.fixture_registry(identity_state="DURABLE"),
                request=request(),
                durable_context=ctx,
                session_response=session(),
                target_pr_readback=target(),
                now=NOW,
            )

    def test_bootstrap_rejects_missing_duplicate_or_wrong_lane(self):
        ctx = context()
        ctx.pop("loop_id", None)

        registry = self.fixture_registry()
        registry["loops"].pop()
        with self.assertRaisesRegex(ValueError, "exactly one enabled ChatGPT"):
            prepare_bootstrap_semiauto_acquire(
                registry=registry,
                request=request(),
                durable_context=ctx,
                session_response=session(),
                target_pr_readback=target(),
                now=NOW,
            )

        registry = self.fixture_registry()
        duplicate = copy.deepcopy(registry["loops"][0])
        duplicate["loop_id"] = "fixture-other-chatgpt-lane"
        duplicate["display_order"] = 99
        registry["loops"].append(duplicate)
        with self.assertRaisesRegex(ValueError, "exactly one enabled ChatGPT"):
            prepare_bootstrap_semiauto_acquire(
                registry=registry,
                request=request(),
                durable_context=ctx,
                session_response=session(),
                target_pr_readback=target(),
                now=NOW,
            )

        for field, value in (
            ("controller_kind", "WORK"),
            ("mode", "AUTO"),
            ("worker_kind", "CLAUDE"),
            ("enabled", False),
        ):
            with self.subTest(field=field):
                with self.assertRaisesRegex(ValueError, "exactly one enabled ChatGPT"):
                    prepare_bootstrap_semiauto_acquire(
                        registry=self.fixture_registry(**{field: value}),
                        request=request(),
                        durable_context=ctx,
                        session_response=session(),
                        target_pr_readback=target(),
                        now=NOW,
                    )

    def test_bootstrap_rejects_any_caller_supplied_loop_id(self):
        canonical_id = get_canonical_semiauto_loop_id()
        for supplied in ("some-id", canonical_id, None, ""):
            with self.subTest(supplied=supplied):
                ctx = context(loop_id=supplied)
                with self.assertRaisesRegex(ValueError, "caller cannot supply loop_id"):
                    prepare_bootstrap_semiauto_acquire(
                        registry=self.fixture_registry(),
                        request=request(),
                        durable_context=ctx,
                        session_response=session(),
                        target_pr_readback=target(),
                        now=NOW,
                    )

    def test_bootstrap_reuses_context_target_session_and_shape_validation(self):
        req = request(
            profile="JULES_CHAT_SEMIAUTO_V2",
            origin_correlation_id="req-2",
        )
        ctx = context(correlation_id="wrong")
        ctx.pop("loop_id", None)
        with self.assertRaisesRegex(ValueError, "origin_correlation_id"):
            self.prepare(req=req, ctx=ctx)

        ctx = context(correlation_id="req-2")
        ctx.pop("loop_id", None)
        ctx["private_chat_url"] = "https://private.example/chat"
        with self.assertRaisesRegex(ValueError, "shape"):
            self.prepare(req=req, ctx=ctx)

        good_ctx = context(correlation_id="req-2")
        good_ctx.pop("loop_id", None)
        with self.assertRaisesRegex(ValueError, "head SHA mismatch"):
            self.prepare(
                req=req,
                ctx=good_ctx,
                tgt=target(head={"ref": req["target_branch"], "sha": "c" * 40}),
            )
        with self.assertRaisesRegex(ValueError, "branch mismatch"):
            self.prepare(
                req=req,
                ctx=good_ctx,
                sess=session(
                    sourceContext={
                        "githubRepoContext": {"startingBranch": "feature/other"}
                    }
                ),
            )

    def test_bootstrap_does_not_mutate_inputs(self):
        registry = self.fixture_registry()
        req = request(
            profile="JULES_CHAT_SEMIAUTO_V2",
            origin_correlation_id="req-1",
        )
        ctx = context(correlation_id="req-1")
        ctx.pop("loop_id", None)
        sess = session()
        tgt = target()
        originals = tuple(
            copy.deepcopy(value)
            for value in (registry, req, ctx, sess, tgt)
        )
        self.prepare(
            registry=registry,
            req=req,
            ctx=ctx,
            sess=sess,
            tgt=tgt,
        )
        self.assertEqual((registry, req, ctx, sess, tgt), originals)

    def test_bootstrap_with_production_registry_file(self):
        reg_path = Path("automation/command_bus/config/control_tower_registry.json")
        production_registry = json.loads(reg_path.read_text(encoding="utf-8"))
        before = copy.deepcopy(production_registry)
        bundle = self.prepare(registry=production_registry)
        canonical_id = get_canonical_semiauto_loop_id()
        self.assertEqual(bundle.owner_event["loop_id"], canonical_id)
        self.assertEqual(production_registry, before)


if __name__ == "__main__":
    unittest.main()
