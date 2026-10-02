from __future__ import annotations

import unittest
from pathlib import Path

from automation.command_bus.github_oidc_proof_policy_cli import (
    PROFILES, RUN7_PROFILE, SF8_AUTHORITY_PROFILE, SF8_PROFILE, REPOSITORY, REPOSITORY_ID, OWNER_ID,
    diagnose_verified_claims, expected_from_runner,
)
from automation.command_bus.tests.test_github_oidc_proof_policy_cli import NOW, SHA, claims, runner

NODE_PROFILES_SOURCE = Path(__file__).parents[1] / "github_oidc_signature_proof.mjs"


def sf8_runner(**changes):
    return runner(**{
        "GITHUB_REF": SF8_PROFILE.branch_ref,
        "GITHUB_WORKFLOW_REF": SF8_PROFILE.workflow_ref,
        "GITHUB_WORKFLOW": SF8_PROFILE.workflow_name,
        **changes,
    })


def sf8_claims(**changes):
    return claims(**{
        "aud": SF8_PROFILE.audience, "sub": SF8_PROFILE.subject,
        "ref": SF8_PROFILE.branch_ref, "workflow_ref": SF8_PROFILE.workflow_ref,
        "job_workflow_ref": SF8_PROFILE.workflow_ref, **changes,
    })


class OidcProofProfileTests(unittest.TestCase):
    def test_default_profile_is_unchanged_run7(self):
        self.assertEqual(expected_from_runner(runner()).audience, RUN7_PROFILE.audience)
        self.assertEqual(diagnose_verified_claims(claims(), runner(), now_epoch=NOW), "PASS")

    def test_sf8_profile_is_exact_and_separate(self):
        self.assertEqual(set(PROFILES), {"run7", "sf8", "sf8-authority"})
        self.assertNotEqual(RUN7_PROFILE.audience, SF8_PROFILE.audience)
        self.assertNotEqual(RUN7_PROFILE.workflow_ref, SF8_PROFILE.workflow_ref)
        self.assertEqual(
            SF8_PROFILE.workflow_ref,
            f"{REPOSITORY}/.github/workflows/signal-sf8-oidc-proof.yml@{SF8_PROFILE.branch_ref}",
        )
        self.assertEqual(
            SF8_PROFILE.subject,
            f"repo:kamiyusense@{OWNER_ID}/multi-ai-council-phase0@{REPOSITORY_ID}:ref:{SF8_PROFILE.branch_ref}",
        )
        self.assertEqual(
            diagnose_verified_claims(sf8_claims(), sf8_runner(), now_epoch=NOW, profile=SF8_PROFILE),
            "PASS",
        )

    def test_profiles_do_not_accept_each_others_context(self):
        # run7 runner/claims under the sf8 profile, and the reverse, are rejected.
        self.assertNotEqual(
            diagnose_verified_claims(claims(), runner(), now_epoch=NOW, profile=SF8_PROFILE), "PASS")
        self.assertNotEqual(
            diagnose_verified_claims(sf8_claims(), sf8_runner(), now_epoch=NOW), "PASS")
        # sf8 runner with run7 audience is rejected.
        self.assertEqual(
            diagnose_verified_claims(
                sf8_claims(aud=RUN7_PROFILE.audience), sf8_runner(), now_epoch=NOW, profile=SF8_PROFILE),
            "AUDIENCE")

    def test_sf8_rejects_wrong_sha_ref_run_attempt_event(self):
        for bad_env in (
            sf8_runner(GITHUB_RUN_ATTEMPT="2"), sf8_runner(GITHUB_EVENT_NAME="workflow_dispatch"),
            sf8_runner(GITHUB_REF="refs/heads/main"), sf8_runner(GITHUB_WORKFLOW_SHA="b" * 40),
        ):
            with self.subTest(bad_env=bad_env):
                self.assertNotEqual(
                    diagnose_verified_claims(sf8_claims(), bad_env, now_epoch=NOW, profile=SF8_PROFILE),
                    "PASS")

    def test_node_profile_table_matches_python_table(self):
        text = NODE_PROFILES_SOURCE.read_text(encoding="utf-8")
        for profile in (RUN7_PROFILE, SF8_PROFILE, SF8_AUTHORITY_PROFILE):
            self.assertIn(f"event: '{profile.event}'", text)
            self.assertIn(profile.audience.replace(REPOSITORY, "${REPO}"), text)
            self.assertIn(
                profile.workflow_ref.replace(REPOSITORY, "${REPO}"), text)

    def test_authority_profile_is_manual_dispatch_on_main_only(self):
        self.assertEqual(SF8_AUTHORITY_PROFILE.event, "workflow_dispatch")
        self.assertEqual(SF8_AUTHORITY_PROFILE.branch_ref, "refs/heads/main")
        env = runner(**{
            "GITHUB_REF": "refs/heads/main", "GITHUB_EVENT_NAME": "workflow_dispatch",
            "GITHUB_WORKFLOW_REF": SF8_AUTHORITY_PROFILE.workflow_ref,
            "GITHUB_WORKFLOW": SF8_AUTHORITY_PROFILE.workflow_name,
        })
        good = claims(**{
            "aud": SF8_AUTHORITY_PROFILE.audience, "sub": SF8_AUTHORITY_PROFILE.subject,
            "ref": "refs/heads/main", "event_name": "workflow_dispatch",
            "workflow_ref": SF8_AUTHORITY_PROFILE.workflow_ref,
            "job_workflow_ref": SF8_AUTHORITY_PROFILE.workflow_ref,
        })
        self.assertEqual(diagnose_verified_claims(good, env, now_epoch=NOW, profile=SF8_AUTHORITY_PROFILE), "PASS")
        # A push-triggered run (what the implementing session can produce) never matches.
        self.assertNotEqual(diagnose_verified_claims(
            {**good, "event_name": "push"}, {**env, "GITHUB_EVENT_NAME": "push"},
            now_epoch=NOW, profile=SF8_AUTHORITY_PROFILE), "PASS")


if __name__ == "__main__":
    unittest.main()
