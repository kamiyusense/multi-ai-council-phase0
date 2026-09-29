from __future__ import annotations

import copy
import hashlib
import json
import unittest

from automation.command_bus.github_oidc_proof_policy_cli import BRANCH_REF, REPOSITORY, WORKFLOW_REF
from automation.command_bus.github_oidc_workflow_evidence_link import prepare_oidc_provider_source_link
from automation.command_bus.tests.test_jules_direct_readback_authenticator import source as provider_source

RUN_ID = "424242"
SHA = "a" * 40


def evidence(**changes):
    value = {
        "schema_version": 1,
        "proof_kind": "GITHUB_HOSTED_OIDC_WORKFLOW_IDENTITY",
        "status": "PASS",
        "issuer": "https://token.actions.githubusercontent.com",
        "signature_verification": "PASS",
        "issuer_binding": "PASS",
        "audience_binding": "PASS",
        "timestamp_validation": "PASS",
        "repository_binding": "PASS",
        "workflow_ref_sha_run_binding": "PASS",
        "repository": REPOSITORY,
        "ref": BRANCH_REF,
        "workflow_ref": WORKFLOW_REF,
        "run_id": RUN_ID,
        "exact_commit_sha": SHA,
        "claim_names": ["iss", "aud", "exp", "repository", "workflow_ref", "run_id"],
        "token_retained": False,
        "provider_fact_verified": False,
        "owner_authority_issued": False,
    }
    value.update(changes)
    canonical = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    value["evidence_sha256"] = hashlib.sha256(canonical.encode()).hexdigest()
    return value


def unknown_source():
    return provider_source(verification_state="UNKNOWN")


class OidcWorkflowEvidenceLinkTests(unittest.TestCase):
    def test_pass_evidence_adds_only_opaque_refs_and_keeps_provider_unknown(self):
        proof = evidence()
        linked = prepare_oidc_provider_source_link(
            evidence=proof, source=unknown_source(),
            expected_run_id=RUN_ID, expected_sha=SHA,
        )
        self.assertEqual(linked.verification_state, "UNKNOWN")
        self.assertEqual(linked.source_document["verification_state"], "UNKNOWN")
        self.assertIn(f"github-actions:run/{RUN_ID}", linked.source_document["proof_refs"])
        self.assertIn(f"github-evidence:sha256/{proof['evidence_sha256']}", linked.source_document["proof_refs"])

    def test_caller_supplied_digest_or_context_mismatch_blocks(self):
        proof = evidence()
        proof["run_id"] = "999"
        with self.assertRaises(ValueError):
            prepare_oidc_provider_source_link(
                evidence=proof, source=unknown_source(),
                expected_run_id=RUN_ID, expected_sha=SHA,
            )
        with self.assertRaises(ValueError):
            prepare_oidc_provider_source_link(
                evidence=evidence(), source=unknown_source(),
                expected_run_id=RUN_ID, expected_sha="b" * 40,
            )

    def test_unverified_provider_and_overclaiming_evidence_block(self):
        with self.assertRaises(ValueError):
            prepare_oidc_provider_source_link(
                evidence=evidence(), source=provider_source(),
                expected_run_id=RUN_ID, expected_sha=SHA,
            )
        for altered in (
            evidence(signature_verification="UNKNOWN"),
            evidence(provider_fact_verified=True),
            evidence(token_retained=True),
        ):
            with self.subTest(altered=altered):
                with self.assertRaises(ValueError):
                    prepare_oidc_provider_source_link(
                        evidence=altered, source=unknown_source(),
                        expected_run_id=RUN_ID, expected_sha=SHA,
                    )

    def test_hidden_token_field_or_bad_digest_blocks(self):
        extra = evidence()
        extra["jwt"] = "forbidden"
        changed = evidence()
        changed["claim_names"].append("actor")
        for altered in (extra, changed):
            with self.subTest(altered=altered):
                with self.assertRaises(ValueError):
                    prepare_oidc_provider_source_link(
                        evidence=altered, source=unknown_source(),
                        expected_run_id=RUN_ID, expected_sha=SHA,
                    )
