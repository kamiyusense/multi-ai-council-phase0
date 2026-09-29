from __future__ import annotations

import unittest

from automation.command_bus.github_oidc_proof_policy_cli import (
    AUDIENCE, BRANCH_REF, OWNER_ID, REPOSITORY, REPOSITORY_ID,
    SUBJECT, WORKFLOW_REF, evaluate_verified_claims, expected_from_runner,
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
