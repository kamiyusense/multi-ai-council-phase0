"""Recorded LIVE evidence (authority run 37031275812, Jules session 301196275118188780).

Authority lineage may be reused through the production authenticator because a
finished run is immutable. Provider evidence is only a past observation: its
lineage is verified, but live authentication stays BLOCKED.
"""
from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from automation.command_bus.github_oidc_proof_policy_cli import SF8_AUTHORITY_PROFILE, SF8_PROFILE
from automation.command_bus.jules_direct_readback_authenticator import JulesDirectReadbackAuthenticator
from automation.command_bus.oidc_workflow_execution import (
    AuthorityIssuerPolicy, OidcBoundAuthorityAuthenticator, verify_oidc_workflow_execution,
)
from automation.command_bus.recorded_live_evidence import (
    RecordedRunReader, assess_recorded_provider_evidence, authority_run_is_fresh,
    digest_ok, has_reusable_workflow_call, output_matches_recorded, payload_digest,
)
from automation.command_bus.tests.test_oidc_workflow_execution import OWNER_ID
from automation.command_bus.tests.test_semiauto_stable_identity_static_e2e import (
    CURRENT_TIME, Clock, SessionReader, TargetReader, build_chain,
)
from automation.command_bus.tests import test_sf8_oidc_runtime_e2e as e2e

ROOT = Path(__file__).resolve().parents[3]
EV = ROOT / "docs/evidence"
RUN_ID = "37031275812"
AUTH_SHA = "4ddb0407001dc18c35f5f45bd37f67664fb9ff32"
ALLOWED_PATH = "docs/evidence/signal-active-proof/PROOF.md"
ALLOWED_CONTENT = "signal active proof\n"
NOW = "2026-10-03T00:00:00Z"


def load(rel):
    return json.loads((EV / rel).read_text(encoding="utf-8"))


OIDC = load("signal-authority/oidc-proof-evidence-37031275812.json")
READBACK = load("signal-authority/authority-run-readback-37031275812.json")
WORKFLOW = (EV / "signal-authority/workflow-signal-sf8-authority-issuer-at-4ddb040.yml.txt").read_text(encoding="utf-8")
PROVIDER = load("signal-active-proof/provider-active-evidence.json")
OUTPUT = load("signal-active-proof/jules-output-github-readback.json")
TERMINAL = load("signal-active-proof/terminal-receipt.json")


def rehash(doc, key, **changes):
    out = {**copy.deepcopy(doc), **changes}
    out[key] = payload_digest(out, key)
    return out


def authority_exec(readback=READBACK, workflow=WORKFLOW, oidc=OIDC, sha=AUTH_SHA, run_id=RUN_ID):
    return verify_oidc_workflow_execution(
        evidence=oidc, profile=SF8_AUTHORITY_PROFILE,
        run_reader=RecordedRunReader(readback, workflow), expected_run_id=run_id, expected_sha=sha)


def assess(**over):
    args = dict(evidence=PROVIDER, output_readback=OUTPUT, terminal_receipt=TERMINAL, now=NOW,
                max_age_seconds=900, allowed_path=ALLOWED_PATH, allowed_content=ALLOWED_CONTENT)
    args.update(over)
    return assess_recorded_provider_evidence(**args)


class RecordedAuthorityTests(unittest.TestCase):
    def test_recorded_digests_are_intact(self):
        self.assertTrue(digest_ok(OIDC, "evidence_payload_sha256"))
        self.assertTrue(digest_ok(READBACK, "readback_payload_sha256"))
        self.assertEqual(READBACK["evidence_payload_sha256"], OIDC["evidence_payload_sha256"])
        self.assertFalse(has_reusable_workflow_call(WORKFLOW))

    def test_real_run_verifies_and_authenticates_through_production_path(self):
        ex = authority_exec()
        self.assertIsNotNone(ex)
        self.assertEqual((ex.event, ex.actor_id, ex.triggering_actor_id, ex.run_id), ("workflow_dispatch", OWNER_ID, OWNER_ID, RUN_ID))
        provider_exec = e2e.execution(SF8_PROFILE, "5001")
        prepared, binding, client, publisher, status, flat = e2e.wire(provider_exec=provider_exec, authority_exec=ex)
        self.assertEqual(publisher.publish(binding.transition_request).status, "READY")  # provider side is a STATIC fixture

    def test_authority_failure_injection(self):
        cases = {
            "tampered_readback": {**copy.deepcopy(READBACK), "actor_id": "1"},
            "push_event": rehash(READBACK, "readback_payload_sha256", event="push"),
            "rerun": rehash(READBACK, "readback_payload_sha256", run_attempt=2),
            "other_workflow": rehash(READBACK, "readback_payload_sha256", workflow_path=".github/workflows/other.yml"),
            "other_branch": rehash(READBACK, "readback_payload_sha256", head_branch="claude/x"),
            "other_sha": rehash(READBACK, "readback_payload_sha256", head_sha="d" * 40),
            "failed_run": rehash(READBACK, "readback_payload_sha256", conclusion="failure"),
            "actor_flag_false": rehash(READBACK, "readback_payload_sha256", actor_matches_triggering_actor=False),
        }
        for label, rb in cases.items():
            with self.subTest(label):
                self.assertIsNone(authority_exec(readback=rb))
        with self.subTest("reusable_workflow_call"):
            self.assertIsNone(authority_exec(workflow=WORKFLOW + "\n  other:\n    uses: ./.github/workflows/x.yml\n"))
        with self.subTest("wrong_run_id"):
            self.assertIsNone(authority_exec(run_id="1"))
        with self.subTest("tampered_oidc"):
            self.assertIsNone(authority_exec(oidc={**OIDC, "run_id": "1"}))

    def test_actor_and_triggering_actor_must_match_and_be_allowlisted(self):
        split = authority_exec(readback=rehash(READBACK, "readback_payload_sha256", triggering_actor_id="7"))
        self.assertIsNotNone(split)  # shape verifies; the authenticator is the gate
        src = e2e.authority_source  # noqa: F841 (source shape used through wire below)
        provider_exec = e2e.execution(SF8_PROFILE, "5001")
        for label, ex, policy in (
            ("split", split, AuthorityIssuerPolicy(allowed_actor_ids=frozenset({OWNER_ID, "7"}))),
            ("not_allowlisted", authority_exec(), AuthorityIssuerPolicy(allowed_actor_ids=frozenset({"1"}))),
        ):
            with self.subTest(label):
                prepared, binding, client, publisher, status, flat = e2e.wire(provider_exec=provider_exec, authority_exec=ex)
                auth = publisher.owner_authority.verifier.authenticator
                auth.policy = policy
                self.assertNotEqual(publisher.publish(binding.transition_request).status, "READY")

    def test_same_run_for_provider_and_authority_rejected(self):
        ex = authority_exec()
        prepared, binding, client, publisher, status, flat = e2e.wire(provider_exec=ex, authority_exec=ex)
        self.assertNotEqual(publisher.publish(binding.transition_request).status, "READY")

    def test_stale_authority_run_rule(self):
        ex = authority_exec()
        self.assertTrue(authority_run_is_fresh(ex.created_at, now="2026-10-02T16:30:00Z", max_age_seconds=3600))
        self.assertFalse(authority_run_is_fresh(ex.created_at, now="2026-10-03T00:00:00Z", max_age_seconds=3600))
        self.assertFalse(authority_run_is_fresh(ex.created_at, now="2026-10-02T15:00:00Z", max_age_seconds=3600))
        self.assertFalse(authority_run_is_fresh("garbage", now=NOW, max_age_seconds=3600))


class RecordedProviderTests(unittest.TestCase):
    def test_lineage_verified_but_live_authentication_blocked(self):
        a = assess()
        self.assertEqual((a.recorded_lineage, a.live_authentication), ("VERIFIED", "BLOCKED"), a)
        self.assertEqual(a.lineage_failures, ())
        for blocker in ("NO_TARGET_PR_AT_OBSERVATION", "NO_DURABLE_OWNER_EVENT_AT_OBSERVATION",
                        "NO_SANITIZED_PROVIDER_SOURCE_CONTEXT", "FRESH_SESSION_READ_REQUIRED_BY_AUTHENTICATOR",
                        "OBSERVATION_STALE"):
            self.assertIn(blocker, a.blockers)

    def test_live_is_blocked_even_when_recent(self):
        a = assess(now="2026-10-02T10:23:00Z")
        self.assertNotIn("OBSERVATION_STALE", a.blockers)
        self.assertEqual(a.live_authentication, "BLOCKED")

    def test_lineage_failure_injection(self):
        cases = {
            "tampered_provider": dict(evidence={**PROVIDER, "session_state": "COMPLETED"}),
            "wrong_session": dict(output_readback=rehash(OUTPUT, "readback_payload_sha256", session_id="1")),
            "unexpected_path": dict(output_readback=rehash(OUTPUT, "readback_payload_sha256", changed_files=[ALLOWED_PATH, "x.md"])),
            "wrong_content": dict(output_readback=rehash(OUTPUT, "readback_payload_sha256", changed_file_content="other\n")),
            "merged": dict(output_readback=rehash(OUTPUT, "readback_payload_sha256", merged=True)),
            "head_equals_base": dict(output_readback=rehash(OUTPUT, "readback_payload_sha256", head_sha=OUTPUT["base_sha"])),
            "target_head_moved": dict(evidence=rehash(PROVIDER, "evidence_payload_sha256", target_head_after_readback="e" * 40)),
            "retry_used": dict(evidence=rehash(PROVIDER, "evidence_payload_sha256", retry=1)),
            "two_sessions": dict(evidence=rehash(PROVIDER, "evidence_payload_sha256", session_create_post_count=2)),
            "get_math": dict(evidence=rehash(PROVIDER, "evidence_payload_sha256", jules_get_count_total=9)),
            "terminal_allows_get": dict(terminal_receipt=rehash(TERMINAL, "receipt_payload_sha256", additional_jules_get_allowed=True)),
            "inactive_state": dict(evidence=rehash(PROVIDER, "evidence_payload_sha256", session_state="COMPLETED")),
            "missing_doc": dict(evidence={}),
        }
        for label, over in cases.items():
            with self.subTest(label):
                a = assess(**over)
                self.assertEqual((a.recorded_lineage, a.live_authentication), ("INVALID", "BLOCKED"), (label, a))
                self.assertTrue(a.lineage_failures)

    def test_output_pr_head_change_is_detected(self):
        self.assertTrue(output_matches_recorded(OUTPUT, copy.deepcopy(OUTPUT)))
        self.assertFalse(output_matches_recorded(OUTPUT, {**OUTPUT, "head_sha": "f" * 40}))
        self.assertFalse(output_matches_recorded(OUTPUT, {**OUTPUT, "changed_files": [ALLOWED_PATH, "x"]}))
        self.assertFalse(output_matches_recorded(OUTPUT, {}))

    def test_production_authenticator_rejects_a_recorded_shape_session(self):
        prepared, binding, normalized, source, client, publisher, status, flat = build_chain()
        recorded_shape = {  # all the recorded evidence can supply: name, createTime, state (no updateTime/sourceContext)
            "name": f"sessions/{PROVIDER['session_id']}", "createTime": PROVIDER["session_create_time"], "state": "IN_PROGRESS",
        }
        auth = JulesDirectReadbackAuthenticator(
            session_reader=SessionReader(recorded_shape), target_reader=TargetReader(flat), clock=Clock(),
            expected_session_create_time=prepared.owner_event["claimed_at"])
        self.assertIsNone(auth.authenticate(source, expected={}))
        self.assertIsNone(JulesDirectReadbackAuthenticator(
            session_reader=None, target_reader=TargetReader(flat), clock=Clock()).authenticate(source, expected={}))


if __name__ == "__main__":
    unittest.main()
