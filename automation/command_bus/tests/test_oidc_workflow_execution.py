from __future__ import annotations

import copy
import hashlib
import json
import unittest

from automation.command_bus.github_oidc_proof_policy_cli import REPOSITORY, SF8_PROFILE, OidcProofProfile
from automation.command_bus.oidc_workflow_execution import (
    AuthorityIssuerPolicy,
    OidcBoundAuthorityAuthenticator,
    OidcBoundProviderAuthenticator,
    VerifiedWorkflowExecution,
    verify_oidc_workflow_execution,
)
from automation.command_bus.runtime_verifier_sources import VerifiedSourceAttestation

RUN_ID = "424242"
SHA = "c" * 40
OWNER_ID = "20355232"
# Test-only issuer profile: a deliberate manual dispatch on a (hypothetical) default-branch workflow.
DISPATCH_PROFILE = OidcProofProfile(
    "test-authority", "refs/heads/main", ".github/workflows/test-authority-issuer.yml",
    "Test authority issuer", "urn:test:authority", event="workflow_dispatch",
)


def evidence_for(profile=SF8_PROFILE, run_id=RUN_ID, sha=SHA, **changes):
    body = {
        "schema_version": 2, "proof_kind": "GITHUB_HOSTED_OIDC_WORKFLOW_IDENTITY",
        "status": "PASS", "terminal_stage": "COMPLETE", "safe_error_code": "NONE",
        "run_id": run_id, "exact_commit_sha": sha,
        "expected_workflow_identity": profile.workflow_ref,
    }
    body.update(changes)
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return {**body, "evidence_payload_sha256": hashlib.sha256(canonical.encode()).hexdigest()}


def run_for(profile=SF8_PROFILE, run_id=RUN_ID, sha=SHA, **changes):
    value = {
        "id": int(run_id), "path": profile.workflow_path, "head_sha": sha,
        "head_branch": profile.branch_ref.removeprefix("refs/heads/"),
        "event": profile.event, "run_attempt": 1, "status": "completed", "conclusion": "success",
        "repository": {"full_name": REPOSITORY}, "head_repository": {"full_name": REPOSITORY},
        "actor": {"id": int(OWNER_ID)}, "triggering_actor": {"id": int(OWNER_ID)},
        "created_at": "2026-10-02T03:00:00Z", "referenced_workflows": [],
    }
    value.update(changes)
    return value


class RunReader:
    def __init__(self, value):
        self.value, self.calls = value, []

    def read_run(self, run_id):
        self.calls.append(run_id)
        return copy.deepcopy(self.value)


def verified(profile=SF8_PROFILE, **run_changes):
    return verify_oidc_workflow_execution(
        evidence=evidence_for(profile), run_reader=RunReader(run_for(profile, **run_changes)),
        profile=profile, expected_run_id=RUN_ID, expected_sha=SHA,
    )


class VerifyExecutionTests(unittest.TestCase):
    def test_exact_evidence_and_run_readback_verify(self):
        execution = verified()
        self.assertIsInstance(execution, VerifiedWorkflowExecution)
        self.assertEqual(execution.run_id, RUN_ID)
        self.assertEqual(execution.proof_refs[0], f"github-actions:run/{RUN_ID}")
        self.assertTrue(execution.proof_refs[1].startswith("github-evidence:sha256/"))

    def test_run_readback_mismatches_fail_closed(self):
        bad_runs = {
            "path": {"path": ".github/workflows/other.yml"},
            "sha": {"head_sha": "d" * 40},
            "branch": {"head_branch": "main"},
            "event": {"event": "workflow_dispatch"},
            "attempt": {"run_attempt": 2},
            "failed": {"conclusion": "failure"},
            "running": {"status": "in_progress", "conclusion": None},
            "repo": {"repository": {"full_name": "evil/repo"}},
            "fork": {"head_repository": {"full_name": "evil/repo"}},
            "reusable": {"referenced_workflows": [{"path": "x/y/.github/workflows/z.yml@main"}]},
            "id": {"id": 1},
            "actor": {"actor": {}},
            "no_created": {"created_at": None},
        }
        for label, changes in bad_runs.items():
            with self.subTest(label):
                self.assertIsNone(verified(**changes))

    def test_evidence_tamper_and_overclaim_fail_closed(self):
        reader = RunReader(run_for())
        good = evidence_for()
        tampered = {**good, "run_id": "1"}
        extra = {**good, "provider_fact_verified": True}
        for label, ev in {
            "tampered": tampered, "extra_key": extra,
            "blocked": evidence_for(status="BLOCKED", terminal_stage="WORKFLOW", safe_error_code="OIDC_WORKFLOW_REJECTED"),
            "other_identity": evidence_for(expected_workflow_identity="x/y/.github/workflows/z.yml@refs/heads/main"),
            "bad_digest": {**good, "evidence_payload_sha256": "0" * 64},
            "not_dict": [good], "none": None,
        }.items():
            with self.subTest(label):
                self.assertIsNone(verify_oidc_workflow_execution(
                    evidence=ev, run_reader=reader, profile=SF8_PROFILE,
                    expected_run_id=RUN_ID, expected_sha=SHA))

    def test_missing_reader_bad_ids_and_unreadable_run(self):
        args = dict(evidence=evidence_for(), profile=SF8_PROFILE, expected_run_id=RUN_ID, expected_sha=SHA)
        self.assertIsNone(verify_oidc_workflow_execution(run_reader=None, **args))
        self.assertIsNone(verify_oidc_workflow_execution(run_reader=RunReader(None), **args))
        self.assertIsNone(verify_oidc_workflow_execution(
            **{**args, "expected_run_id": "12x"}, run_reader=RunReader(run_for())))
        self.assertIsNone(verify_oidc_workflow_execution(
            **{**args, "expected_sha": "ABC"}, run_reader=RunReader(run_for())))
        self.assertIsNone(verify_oidc_workflow_execution(
            **{**args, "profile": "sf8"}, run_reader=RunReader(run_for())))


class _Inner:
    def __init__(self, result="ok"):
        self.result, self.calls = result, []

    def authenticate(self, source, *, expected):
        self.calls.append(source)
        return self.result if self.result != "ok" else VerifiedSourceAttestation(
            source["verification_kind"], source["source_id"], source["source_ref"], source["observed_at"])


def provider_source(execution, refs=True):
    from automation.command_bus.tests.test_jules_direct_readback_authenticator import source
    value = source()
    if refs:
        value = {**value, "proof_refs": [*value["proof_refs"], *execution.proof_refs]}
    return value


class ProviderAuthenticatorTests(unittest.TestCase):
    def test_requires_execution_refs_and_inner_attestation(self):
        execution = verified()
        inner = _Inner()
        auth = OidcBoundProviderAuthenticator(execution=execution, inner=inner)
        src = provider_source(execution)
        self.assertIsNotNone(auth.authenticate(src, expected=src))
        self.assertEqual(len(inner.calls), 1)

    def test_fail_closed_without_execution_refs_inner_or_matching_run(self):
        execution = verified()
        inner = _Inner()
        src_no_refs = provider_source(execution, refs=False)
        self.assertIsNone(OidcBoundProviderAuthenticator(execution=execution, inner=inner)
                          .authenticate(src_no_refs, expected=src_no_refs))
        self.assertEqual(inner.calls, [])  # inner never consulted without the OIDC link
        src = provider_source(execution)
        self.assertIsNone(OidcBoundProviderAuthenticator(execution=None, inner=inner).authenticate(src, expected=src))
        self.assertIsNone(OidcBoundProviderAuthenticator(execution=execution, inner=None).authenticate(src, expected=src))
        self.assertIsNone(OidcBoundProviderAuthenticator(execution=execution, inner=_Inner(None)).authenticate(src, expected=src))
        other = verify_oidc_workflow_execution(
            evidence=evidence_for(run_id="999"), run_reader=RunReader(run_for(run_id="999")),
            profile=SF8_PROFILE, expected_run_id="999", expected_sha=SHA)
        self.assertIsNone(OidcBoundProviderAuthenticator(execution=other, inner=inner).authenticate(src, expected=src))
        self.assertIsNone(OidcBoundProviderAuthenticator(execution=execution, inner=inner).authenticate(
            {**src, "unexpected": 1}, expected=src))

    def test_oidc_alone_never_authenticates_provider(self):
        execution = verified()
        src = provider_source(execution)
        self.assertIsNone(OidcBoundProviderAuthenticator(execution=execution, inner=_Inner(None))
                          .authenticate(src, expected=src))


def authority_source(execution, **changes):
    value = {
        "schema_version": 1, "verification_kind": "AUTHORITY_GRANT", "source_id": "authority-src-1",
        "source_ref": "automation/command_bus/evidence/lane-a/authority-1.json",
        "verification_state": "VERIFIED", "observed_at": "2026-10-02T03:01:00Z",
        "expires_at": "2026-10-02T05:00:00Z", "authority_id": "authority-1", "loop_id": "lane-a",
        "owner_role": "SEMI_AUTO", "holder_id": "chatgpt-controller", "generation": 1,
        "fencing_token": 1, "previous_generation": None, "event_type": "ACQUIRE",
        "expected_repo": REPOSITORY, "expected_pr": 4, "expected_target_head": "a" * 40,
        "command_id": "cmd-1", "correlation_id": "corr-1",
        "proof_refs": list(execution.proof_refs),
    }
    value.update(changes)
    return value


class AuthorityAuthenticatorTests(unittest.TestCase):
    def setUp(self):
        self.policy = AuthorityIssuerPolicy(allowed_actor_ids=frozenset({OWNER_ID}))
        self.execution = verified(DISPATCH_PROFILE)

    def test_manual_dispatch_by_allowlisted_actor_authenticates_exact_source(self):
        src = authority_source(self.execution)
        auth = OidcBoundAuthorityAuthenticator(execution=self.execution, policy=self.policy)
        att = auth.authenticate(src, expected=dict(src))
        self.assertIsInstance(att, VerifiedSourceAttestation)

    def test_push_triggered_run_by_the_implementing_session_cannot_issue_authority(self):
        push_exec = verified(SF8_PROFILE)  # push event, same account as the implementer
        src = authority_source(push_exec)
        auth = OidcBoundAuthorityAuthenticator(execution=push_exec, policy=self.policy)
        self.assertIsNone(auth.authenticate(src, expected=dict(src)))

    def test_policy_actor_and_source_fail_closed(self):
        src = authority_source(self.execution)
        expected = dict(src)
        no_actor = AuthorityIssuerPolicy()
        self.assertIsNone(OidcBoundAuthorityAuthenticator(execution=self.execution, policy=no_actor).authenticate(src, expected=expected))
        other = AuthorityIssuerPolicy(allowed_actor_ids=frozenset({"1"}))
        self.assertIsNone(OidcBoundAuthorityAuthenticator(execution=self.execution, policy=other).authenticate(src, expected=expected))
        split = verify_oidc_workflow_execution(
            evidence=evidence_for(DISPATCH_PROFILE), profile=DISPATCH_PROFILE,
            run_reader=RunReader(run_for(DISPATCH_PROFILE, triggering_actor={"id": 7})),
            expected_run_id=RUN_ID, expected_sha=SHA)
        self.assertIsNone(OidcBoundAuthorityAuthenticator(execution=split, policy=self.policy).authenticate(
            authority_source(split), expected=expected))
        auth = OidcBoundAuthorityAuthenticator(execution=self.execution, policy=self.policy)
        self.assertIsNone(auth.authenticate({**src, "verification_state": "UNKNOWN"}, expected={**expected, "verification_state": "UNKNOWN"}))
        self.assertIsNone(auth.authenticate({**src, "proof_refs": ["x:y"]}, expected={}))
        self.assertIsNone(auth.authenticate(src, expected={**expected, "generation": 2}))
        self.assertIsNone(auth.authenticate(src, expected={**expected, "expected_target_head": "b" * 40}))
        self.assertIsNone(OidcBoundAuthorityAuthenticator(execution=None, policy=self.policy).authenticate(src, expected=expected))

    def test_provider_and_authority_paths_must_be_distinct_executions(self):
        src = authority_source(self.execution)
        same_run = OidcBoundAuthorityAuthenticator(
            execution=self.execution, policy=self.policy, provider_execution=self.execution)
        self.assertIsNone(same_run.authenticate(src, expected=dict(src)))
        provider = verified(SF8_PROFILE)
        distinct = OidcBoundAuthorityAuthenticator(
            execution=self.execution, policy=self.policy, provider_execution=provider)
        # provider run id equals this fixture's run id, so use a different run for the provider
        provider2 = verify_oidc_workflow_execution(
            evidence=evidence_for(run_id="777"), run_reader=RunReader(run_for(run_id="777")),
            profile=SF8_PROFILE, expected_run_id="777", expected_sha=SHA)
        distinct = OidcBoundAuthorityAuthenticator(
            execution=self.execution, policy=self.policy, provider_execution=provider2)
        self.assertIsNotNone(distinct.authenticate(src, expected=dict(src)))


if __name__ == "__main__":
    unittest.main()
