from __future__ import annotations

import unittest

from automation.command_bus.github_oidc_proof_policy_cli import (
    AUDIENCE, BRANCH_REF, OWNER_ID, REPOSITORY, REPOSITORY_ID,
    SUBJECT, WORKFLOW_REF, diagnose_verified_claims, evaluate_verified_claims, expected_from_runner,
    safe_failure_code,
)

NOW = 1_800_000_100
SHA = "a" * 40


def runner(**changes):
    value = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_REPOSITORY": REPOSITORY,
        "GITHUB_REPOSITORY_ID": REPOSITORY_ID,
        "GITHUB_REPOSITORY_OWNER_ID": OWNER_ID,
        "GITHUB_REF": BRANCH_REF,
        "GITHUB_REF_TYPE": "branch",
        "GITHUB_WORKFLOW_REF": WORKFLOW_REF,
        "GITHUB_WORKFLOW_SHA": SHA,
        "GITHUB_WORKFLOW": "Phase 0 bounded OIDC identity proof",
        "GITHUB_EVENT_NAME": "push",
        "GITHUB_RUN_ATTEMPT": "1",
        "GITHUB_RUN_ID": "424242",
        "GITHUB_SHA": SHA,
        "RUNNER_ENVIRONMENT": "github-hosted",
    }
    value.update(changes)
    return value


def claims(**changes):
    value = {
        "iss": "https://token.actions.githubusercontent.com",
        "aud": AUDIENCE,
        "sub": SUBJECT,
        "repository": REPOSITORY,
        "repository_id": REPOSITORY_ID,
        "repository_owner_id": OWNER_ID,
        "ref": BRANCH_REF,
        "sha": SHA,
        "workflow_ref": WORKFLOW_REF,
        "workflow_sha": SHA,
        "workflow": "Phase 0 bounded OIDC identity proof",
        "event_name": "push",
        "run_id": "424242",
        "run_attempt": "1",
        "runner_environment": "github-hosted",
        "repository_visibility": "private",
        "jti": "fixture-only-jti",
        "nbf": NOW - 120,
        "iat": NOW - 60,
        "exp": NOW + 300,
    }
    value.update(changes)
    return value


class OidcProofPolicyTests(unittest.TestCase):
    def test_signed_claims_matching_bounded_runner_context_pass_policy(self):
        self.assertEqual(expected_from_runner(runner()).workflow_ref, WORKFLOW_REF)
        self.assertTrue(evaluate_verified_claims(claims(), runner(), now_epoch=NOW))

    def test_runner_context_drift_is_rejected_before_claims(self):
        for field, changed in (
            ("GITHUB_REPOSITORY_ID", "1"),
            ("GITHUB_REPOSITORY_OWNER_ID", "1"),
            ("GITHUB_REF", "refs/heads/main"),
            ("GITHUB_WORKFLOW_REF", "other"),
            ("GITHUB_WORKFLOW_SHA", "b" * 40),
            ("GITHUB_RUN_ATTEMPT", "2"),
            ("RUNNER_ENVIRONMENT", "self-hosted"),
        ):
            with self.subTest(field=field):
                with self.assertRaises(ValueError):
                    expected_from_runner(runner(**{field: changed}))

    def test_signed_claim_context_and_time_mismatch_fail_closed(self):
        for field, changed in (
            ("aud", "other"), ("sub", "repo:other"),
            ("repository", "other/repo"), ("workflow_ref", "other"),
            ("sha", "b" * 40), ("run_id", "999"),
            ("exp", NOW), ("nbf", NOW + 1),
        ):
            with self.subTest(field=field):
                self.assertFalse(evaluate_verified_claims(
                    claims(**{field: changed}), runner(), now_epoch=NOW,
                ))

    def test_each_claim_failure_has_a_fixed_stage(self):
        cases = (
            ("ISSUER", "iss", "other"),
            ("AUDIENCE", "aud", "other"),
            ("TIME", "exp", NOW),
            ("REPOSITORY", "repository", "other/repo"),
            ("WORKFLOW", "workflow_ref", "other"),
            ("REF_SHA", "sha", "b" * 40),
            ("RUN_ID", "run_id", "999"),
            ("COMPLETE", "jti", ""),
        )
        for stage, field, value in cases:
            with self.subTest(stage=stage):
                self.assertEqual(
                    diagnose_verified_claims(claims(**{field: value}), runner(), now_epoch=NOW),
                    stage,
                )
        self.assertEqual(diagnose_verified_claims(claims(), runner(), now_epoch=NOW), "PASS")
        self.assertEqual(diagnose_verified_claims(claims(), runner(GITHUB_RUN_ID=""), now_epoch=NOW), "RUN_ID")

    def test_official_workflow_identity_fixture_and_fixed_failure_codes(self):
        valid_claims = claims()
        valid_runner = runner()
        self.assertEqual(valid_claims["workflow_ref"], WORKFLOW_REF)
        self.assertEqual(valid_claims["workflow_sha"], valid_runner["GITHUB_WORKFLOW_SHA"])
        self.assertEqual(valid_claims["workflow"], valid_runner["GITHUB_WORKFLOW"])
        self.assertTrue(evaluate_verified_claims(valid_claims, valid_runner, now_epoch=NOW))
        cases = (
            ("WORKFLOW", claims(), runner(GITHUB_WORKFLOW_REF="other"),
             "OIDC_WORKFLOW_RUNNER_REF_REJECTED"),
            ("WORKFLOW", claims(), runner(GITHUB_WORKFLOW="other"),
             "OIDC_WORKFLOW_RUNNER_NAME_REJECTED"),
            ("WORKFLOW", claims(workflow_ref=WORKFLOW_REF.replace("github-oidc-proof.yml", "other.yml")),
             runner(), "OIDC_WORKFLOW_CLAIM_REF_REJECTED"),
            ("WORKFLOW", claims(workflow_ref=WORKFLOW_REF.replace(BRANCH_REF, "refs/heads/other")),
             runner(), "OIDC_WORKFLOW_CLAIM_REF_REJECTED"),
            ("WORKFLOW", claims(job_workflow_ref=WORKFLOW_REF),
             runner(), "OIDC_WORKFLOW_JOB_REF_MATCHES_WORKFLOW_REF_REJECTED"),
            ("WORKFLOW", claims(job_workflow_ref="other/reusable.yml@refs/heads/main"),
             runner(), "OIDC_WORKFLOW_JOB_REF_DIFFERS_FROM_WORKFLOW_REF_REJECTED"),
            ("WORKFLOW", claims(job_workflow_ref=""),
             runner(), "OIDC_WORKFLOW_JOB_REF_EMPTY_REJECTED"),
            ("WORKFLOW", claims(job_workflow_ref="bearer header.payload.signature secret"),
             runner(), "OIDC_WORKFLOW_JOB_REF_DIFFERS_FROM_WORKFLOW_REF_REJECTED"),
            ("REF_SHA", claims(), runner(GITHUB_WORKFLOW_SHA="b" * 40),
             "OIDC_REF_SHA_RUNNER_WORKFLOW_SHA_REJECTED"),
            ("REF_SHA", claims(workflow_sha="b" * 40), runner(),
             "OIDC_REF_SHA_CLAIM_WORKFLOW_SHA_REJECTED"),
            ("REF_SHA", claims(sha="b" * 40), runner(), "OIDC_REF_SHA_REJECTED"),
            ("RUN_ID", claims(run_id="999"), runner(), "OIDC_RUN_ID_REJECTED"),
        )
        for stage, signed, context, code in cases:
            with self.subTest(code=code):
                self.assertEqual(diagnose_verified_claims(signed, context, now_epoch=NOW), stage)
                self.assertEqual(
                    safe_failure_code(stage, signed, context, now_epoch=NOW), code,
                )
                self.assertNotIn("other/reusable.yml", code)

    def test_failure_code_never_contains_claim_or_runner_secret(self):
        secret = "bearer header.payload.signature private-token-value"
        signed = claims(workflow_ref=secret)
        stage = diagnose_verified_claims(signed, runner(), now_epoch=NOW)
        code = safe_failure_code(stage, signed, runner(), now_epoch=NOW)
        self.assertEqual(code, "OIDC_WORKFLOW_CLAIM_REF_REJECTED")
        self.assertNotIn(secret, code)
