from __future__ import annotations

import copy
import unittest

from automation.command_bus.github_oidc_claims_policy import (
    GitHubOidcExpectedContext,
    evaluate_github_oidc_claims_policy,
)


NOW = 1_800_000_100


def expected(**changes):
    value = dict(
        audience="phase0-verifier",
        subject="repo:owner/repo:ref:refs/heads/runtime-data",
        repository="owner/repo",
        repository_id="123456789",
        repository_owner_id="987654321",
        ref="refs/heads/runtime-data",
        sha="a" * 40,
        workflow_ref="owner/repo/.github/workflows/provider-readback.yml@refs/heads/runtime-data",
        workflow_sha="b" * 40,
        event_name="push",
        run_id="424242",
        repository_visibility="public",
        job_workflow_ref=None,
        job_workflow_sha=None,
    )
    value.update(changes)
    return GitHubOidcExpectedContext(**value)


def claims(**changes):
    value = {
        "iss": "https://token.actions.githubusercontent.com",
        "aud": "phase0-verifier",
        "sub": "repo:owner/repo:ref:refs/heads/runtime-data",
        "repository": "owner/repo",
        "repository_id": "123456789",
        "repository_owner_id": "987654321",
        "ref": "refs/heads/runtime-data",
        "sha": "a" * 40,
        "workflow_ref": "owner/repo/.github/workflows/provider-readback.yml@refs/heads/runtime-data",
        "workflow_sha": "b" * 40,
        "event_name": "push",
        "run_id": "424242",
        "run_attempt": "1",
        "runner_environment": "github-hosted",
        "repository_visibility": "public",
        "jti": "token-unique-id",
        "nbf": NOW - 120,
        "iat": NOW - 60,
        "exp": NOW + 300,
        "actor": "example",
        "actor_id": "123",
        "workflow": "Provider readback",
    }
    value.update(changes)
    return value


class GitHubOidcClaimsPolicyTests(unittest.TestCase):
    def test_exact_verified_claim_context_matches_policy(self):
        result = evaluate_github_oidc_claims_policy(
            claims(),
            expected(),
            now_epoch=NOW,
        )
        self.assertEqual(result.status, "MATCH", result)

    def test_each_exact_identity_claim_mismatch_blocks(self):
        cases = {
            "iss": "https://issuer.example",
            "aud": "wrong-audience",
            "sub": "repo:other/repo:ref:refs/heads/runtime-data",
            "repository": "other/repo",
            "repository_id": "111",
            "repository_owner_id": "222",
            "ref": "refs/heads/other",
            "sha": "c" * 40,
            "workflow_ref": "owner/repo/.github/workflows/other.yml@refs/heads/runtime-data",
            "workflow_sha": "d" * 40,
            "event_name": "workflow_dispatch",
            "run_id": "999",
            "run_attempt": "2",
            "runner_environment": "self-hosted",
            "repository_visibility": "private",
        }
        for field, value in cases.items():
            with self.subTest(field=field):
                result = evaluate_github_oidc_claims_policy(
                    claims(**{field: value}),
                    expected(),
                    now_epoch=NOW,
                )
                self.assertEqual(result.status, "BLOCKED", result)
                self.assertIn(field, result.reason)

    def test_missing_required_claim_blocks(self):
        value = claims()
        value.pop("workflow_sha")
        result = evaluate_github_oidc_claims_policy(
            value,
            expected(),
            now_epoch=NOW,
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("missing", result.reason)

    def test_temporal_claims_fail_closed(self):
        cases = [
            (claims(nbf=NOW + 1), "nbf"),
            (claims(iat=NOW + 1), "future"),
            (claims(exp=NOW), "expired"),
            (claims(iat=NOW - 10, exp=NOW - 11), "exp"),
            (claims(nbf=NOW - 1, iat=NOW - 2), "nbf"),
        ]
        for value, message in cases:
            with self.subTest(message=message):
                result = evaluate_github_oidc_claims_policy(
                    value,
                    expected(),
                    now_epoch=NOW,
                )
                self.assertEqual(result.status, "BLOCKED", result)
                self.assertIn(message, result.reason)

    def test_temporal_claims_must_be_integer_numeric_dates(self):
        for field in ("nbf", "iat", "exp"):
            with self.subTest(field=field):
                value = claims()
                value[field] = str(value[field])
                result = evaluate_github_oidc_claims_policy(
                    value,
                    expected(),
                    now_epoch=NOW,
                )
                self.assertEqual(result.status, "BLOCKED")
                self.assertIn(field, result.reason)

    def test_jti_is_required_but_extra_claims_are_ignored(self):
        missing = claims()
        missing.pop("jti")
        self.assertEqual(
            evaluate_github_oidc_claims_policy(
                missing,
                expected(),
                now_epoch=NOW,
            ).status,
            "BLOCKED",
        )

        extra = claims(custom_future_claim="safe-extra")
        self.assertEqual(
            evaluate_github_oidc_claims_policy(
                extra,
                expected(),
                now_epoch=NOW,
            ).status,
            "MATCH",
        )

    def test_reusable_workflow_identity_must_be_explicit_ref_sha_pair(self):
        reusable_ref = "owner/reusable/.github/workflows/verify.yml@refs/heads/main"
        reusable_sha = "c" * 40
        value = claims(
            job_workflow_ref=reusable_ref,
            job_workflow_sha=reusable_sha,
        )
        result = evaluate_github_oidc_claims_policy(
            value,
            expected(),
            now_epoch=NOW,
        )
        self.assertEqual(result.status, "BLOCKED")
        self.assertIn("explicit ref and sha", result.reason)

        for incomplete in (
            expected(job_workflow_ref=reusable_ref),
            expected(job_workflow_sha=reusable_sha),
        ):
            with self.subTest(incomplete=incomplete):
                self.assertEqual(
                    evaluate_github_oidc_claims_policy(
                        value, incomplete, now_epoch=NOW,
                    ).status,
                    "BLOCKED",
                )

        exp = expected(
            job_workflow_ref=reusable_ref,
            job_workflow_sha=reusable_sha,
        )
        self.assertEqual(
            evaluate_github_oidc_claims_policy(
                value,
                exp,
                now_epoch=NOW,
            ).status,
            "MATCH",
        )

        for field, changed in (
            ("job_workflow_ref", "owner/reusable/.github/workflows/other.yml@refs/heads/main"),
            ("job_workflow_sha", "d" * 40),
        ):
            with self.subTest(field=field):
                candidate = {
                    "job_workflow_ref": reusable_ref,
                    "job_workflow_sha": reusable_sha,
                }
                candidate[field] = changed
                result = evaluate_github_oidc_claims_policy(
                    claims(**candidate),
                    exp,
                    now_epoch=NOW,
                )
                self.assertEqual(result.status, "BLOCKED")
                self.assertIn(field, result.reason)

    def test_subject_is_exact_policy_input_not_inferred(self):
        immutable_style = (
            "repo:owner-id:987654321:repository-id:123456789:"
            "ref:refs/heads/runtime-data"
        )
        value = claims(sub=immutable_style)

        old_policy = evaluate_github_oidc_claims_policy(
            value,
            expected(),
            now_epoch=NOW,
        )
        self.assertEqual(old_policy.status, "BLOCKED")

        exact_policy = evaluate_github_oidc_claims_policy(
            value,
            expected(subject=immutable_style),
            now_epoch=NOW,
        )
        self.assertEqual(exact_policy.status, "MATCH")

    def test_invalid_expected_context_fails_closed(self):
        cases = [
            expected(repository="not-a-repo"),
            expected(repository_id="abc"),
            expected(repository_owner_id="abc"),
            expected(run_id="abc"),
            expected(sha="A" * 40),
            expected(workflow_sha="short"),
            expected(repository_visibility="UNKNOWN"),
        ]
        for exp in cases:
            with self.subTest(exp=exp):
                result = evaluate_github_oidc_claims_policy(
                    claims(),
                    exp,
                    now_epoch=NOW,
                )
                self.assertEqual(result.status, "BLOCKED")

    def test_policy_does_not_mutate_claims(self):
        value = claims()
        before = copy.deepcopy(value)
        evaluate_github_oidc_claims_policy(
            value,
            expected(),
            now_epoch=NOW,
        )
        self.assertEqual(value, before)

    def test_policy_result_is_not_provider_or_owner_authority_proof(self):
        result = evaluate_github_oidc_claims_policy(
            claims(),
            expected(),
            now_epoch=NOW,
        )
        self.assertEqual(result.status, "MATCH")
        self.assertFalse(hasattr(result, "verified"))
        self.assertFalse(hasattr(result, "authority"))
        self.assertFalse(hasattr(result, "observation"))


if __name__ == "__main__":
    unittest.main()
