from __future__ import annotations

import copy
import unittest

from automation.command_bus.jules_provider_verification_source import (
    mark_provider_source_verified,
    prepare_jules_provider_verification_source,
)
from automation.command_bus.runtime_verifier_sources import (
    SourceBoundProviderVerifier,
)
from automation.command_bus.tests.test_jules_semiauto_owner_prepare import bundle


class Reader:
    def __init__(self, source):
        self.source = copy.deepcopy(source)
        self.calls = []

    def read(self, source_ref):
        self.calls.append(source_ref)
        return copy.deepcopy(self.source)


def prepared_source():
    prepared = bundle()
    return prepared, prepare_jules_provider_verification_source(
        provider_observation_input=prepared.provider_observation_input,
        evidence_document=prepared.evidence_document,
        source_receipt=prepared.source_receipt,
        session_id=prepared.acceptance_session_id,
        proof_refs=[
            "jules-session:31415926535897932384",
            "github-actions-run:36394238067",
        ],
    )


class JulesProviderVerificationSourceTests(unittest.TestCase):
    def test_normalized_source_is_exactly_bound_but_starts_unknown(self):
        prepared, source = prepared_source()
        self.assertEqual(source["verification_kind"], "PROVIDER_OBSERVATION")
        self.assertEqual(source["verification_state"], "UNKNOWN")
        self.assertEqual(
            source["source_ref"],
            f"jules-session:{prepared.acceptance_session_id}",
        )
        self.assertEqual(source["loop_id"], prepared.owner_event["loop_id"])
        self.assertEqual(source["generation"], 1)
        self.assertEqual(source["fencing_token"], 1)
        self.assertEqual(source["expected_pr"], 4)
        self.assertEqual(source["provider_kind"], "JULES")
        self.assertEqual(source["provider_state"], "RUNNING")
        self.assertEqual(
            source["source_receipt_ref"],
            prepared.owner_event["source_receipt_ref"],
        )
        self.assertEqual(
            source["evidence_ref"],
            prepared.owner_event["evidence_refs"][0],
        )

    def test_prepare_layer_cannot_mark_source_verified(self):
        with self.assertRaisesRegex(RuntimeError, "cannot mark"):
            mark_provider_source_verified()

    def test_source_bound_verifier_without_authenticator_never_accepts(self):
        prepared, source = prepared_source()
        reader = Reader(source)
        verifier = SourceBoundProviderVerifier(reader, None)
        result = verifier.verify(
            prepared.provider_observation_input,
            prepared.evidence_document,
            prepared.source_receipt,
        )
        self.assertIsNone(result)
        self.assertEqual(reader.calls, [source["source_ref"]])

    def test_even_caller_modified_verified_source_does_not_pass_without_authenticator(self):
        prepared, source = prepared_source()
        source["verification_state"] = "VERIFIED"
        verifier = SourceBoundProviderVerifier(Reader(source), None)
        self.assertIsNone(
            verifier.verify(
                prepared.provider_observation_input,
                prepared.evidence_document,
                prepared.source_receipt,
            )
        )

    def test_session_id_must_match_evidence_provider_readback(self):
        prepared = bundle()
        with self.assertRaisesRegex(ValueError, "source_ref mismatch"):
            prepare_jules_provider_verification_source(
                provider_observation_input=prepared.provider_observation_input,
                evidence_document=prepared.evidence_document,
                source_receipt=prepared.source_receipt,
                session_id="999999",
                proof_refs=["jules-session:999999"],
            )

    def test_unknown_or_url_proof_refs_fail_closed(self):
        prepared = bundle()
        for refs in (
            [],
            ["https://private.example/run"],
            ["github-actions-run:1", "github-actions-run:1"],
        ):
            with self.subTest(refs=refs):
                with self.assertRaises(ValueError):
                    prepare_jules_provider_verification_source(
                        provider_observation_input=prepared.provider_observation_input,
                        evidence_document=prepared.evidence_document,
                        source_receipt=prepared.source_receipt,
                        session_id=prepared.acceptance_session_id,
                        proof_refs=refs,
                    )

    def test_caller_verified_observation_is_rejected(self):
        prepared = bundle()
        bad = {
            **prepared.provider_observation_input,
            "verified": True,
        }
        with self.assertRaisesRegex(ValueError, "caller-supplied verified"):
            prepare_jules_provider_verification_source(
                provider_observation_input=bad,
                evidence_document=prepared.evidence_document,
                source_receipt=prepared.source_receipt,
                session_id=prepared.acceptance_session_id,
                proof_refs=["jules-session:31415926535897932384"],
            )

    def test_receipt_evidence_or_context_mismatch_fails_closed(self):
        prepared = bundle()

        bad_receipt = {
            **prepared.source_receipt,
            "correlation_id": "other-correlation",
        }
        with self.assertRaisesRegex(ValueError, "receipt/evidence mismatch"):
            prepare_jules_provider_verification_source(
                provider_observation_input=prepared.provider_observation_input,
                evidence_document=prepared.evidence_document,
                source_receipt=bad_receipt,
                session_id=prepared.acceptance_session_id,
                proof_refs=["jules-session:31415926535897932384"],
            )

        bad_observation = {
            **prepared.provider_observation_input,
            "expected_pr": 5,
        }
        with self.assertRaisesRegex(ValueError, "observation/evidence mismatch"):
            prepare_jules_provider_verification_source(
                provider_observation_input=bad_observation,
                evidence_document=prepared.evidence_document,
                source_receipt=prepared.source_receipt,
                session_id=prepared.acceptance_session_id,
                proof_refs=["jules-session:31415926535897932384"],
            )


if __name__ == "__main__":
    unittest.main()
