from __future__ import annotations

import copy
import json
import unittest

from automation.command_bus.jules_provider_readback_candidate import (
    bind_jules_active_provider_readback,
    build_provider_verification_source,
    prepare_jules_provider_readback_candidate,
)
from automation.command_bus.runtime_verifier_sources import (
    SourceBoundProviderVerifier,
    VerifiedSourceAttestation,
)
from automation.command_bus.tests.test_jules_semiauto_owner_prepare import (
    BRANCH,
    WORK_BRANCH,
    bundle,
    current_bundle,
)


def session_get(**changes):
    value = {
        "name": "sessions/31415926535897932384",
        "state": "RUNNING",
        "createTime": "2026-09-28T03:59:00Z",
        "updateTime": "2026-09-28T04:05:00Z",
        "sourceContext": {
            "githubRepoContext": {
                "startingBranch": "feature/relay-transport-7070955470193506982",
            }
        },
    }
    value.update(changes)
    return value


class Reader:
    def __init__(self, source):
        self.source = copy.deepcopy(source)
        self.calls = []

    def read(self, source_ref):
        self.calls.append(source_ref)
        if self.source["source_ref"] != source_ref:
            return None
        return copy.deepcopy(self.source)


class Authenticator:
    def __init__(self, *, accept=True):
        self.accept = accept
        self.calls = []

    def authenticate(self, source, *, expected):
        self.calls.append((copy.deepcopy(source), copy.deepcopy(expected)))
        if not self.accept:
            return None
        return VerifiedSourceAttestation(
            verification_kind=source["verification_kind"],
            source_id=source["source_id"],
            source_ref=source["source_ref"],
            observed_at=source["observed_at"],
        )


class JulesProviderReadbackCandidateTests(unittest.TestCase):
    def test_running_session_readback_builds_unknown_candidate_source(self):
        prepared = bundle()
        candidate = prepare_jules_provider_readback_candidate(
            bundle=prepared,
            session_readback=session_get(),
        )
        self.assertEqual(candidate.provider_kind, "JULES")
        self.assertEqual(candidate.provider_state, "RUNNING")
        self.assertEqual(candidate.loop_id, "chatgpt-semi-auto-v1")
        self.assertEqual(candidate.expected_pr, 4)
        self.assertEqual(
            candidate.source_ref,
            "jules-session:31415926535897932384",
        )
        self.assertEqual(candidate.observed_at, "2026-09-28T04:05:00Z")
        source = build_provider_verification_source(
            candidate,
            verification_state="UNKNOWN",
        )
        self.assertEqual(source["verification_state"], "UNKNOWN")
        self.assertEqual(source["provider_state"], "RUNNING")

    def test_current_carrier_candidate_binds_both_branch_identities(self):
        prepared = current_bundle()
        candidate = prepare_jules_provider_readback_candidate(
            bundle=prepared,
            session_readback=session_get(sourceContext={
                "githubRepoContext": {"startingBranch": WORK_BRANCH},
            }),
        )
        self.assertIn(f"github-branch:{BRANCH}", candidate.proof_refs)
        self.assertIn(f"jules-branch:{WORK_BRANCH}", candidate.proof_refs)

    def test_raw_provider_state_is_preserved_without_mapping(self):
        prepared = bundle()
        queued = prepare_jules_provider_readback_candidate(
            bundle=prepared,
            session_readback=session_get(state="QUEUED"),
        )
        completed = prepare_jules_provider_readback_candidate(
            bundle=prepared,
            session_readback=session_get(state="COMPLETED"),
        )
        self.assertEqual(queued.provider_state, "QUEUED")
        self.assertEqual(completed.provider_state, "COMPLETED")

    def test_verified_text_alone_never_grants_provider_verification(self):
        prepared = bundle()
        candidate = prepare_jules_provider_readback_candidate(
            bundle=prepared,
            session_readback=session_get(),
        )
        binding = bind_jules_active_provider_readback(
            bundle=prepared,
            candidate=candidate,
        )
        source = build_provider_verification_source(
            candidate,
            verification_state="VERIFIED",
        )
        reader = Reader(source)

        verifier = SourceBoundProviderVerifier(reader, authenticator=None)
        self.assertIsNone(
            verifier.verify(
                binding.provider_observation_input,
                binding.evidence_document,
                prepared.source_receipt,
            )
        )
        self.assertEqual(reader.calls, [])

    def test_independent_authenticator_is_required_for_verified_observation(self):
        prepared = bundle()
        candidate = prepare_jules_provider_readback_candidate(
            bundle=prepared,
            session_readback=session_get(),
        )
        binding = bind_jules_active_provider_readback(
            bundle=prepared,
            candidate=candidate,
        )
        source = build_provider_verification_source(
            candidate,
            verification_state="VERIFIED",
        )

        rejecting = SourceBoundProviderVerifier(
            Reader(source),
            Authenticator(accept=False),
        )
        self.assertIsNone(
            rejecting.verify(
                binding.provider_observation_input,
                binding.evidence_document,
                prepared.source_receipt,
            )
        )

        auth = Authenticator(accept=True)
        verifier = SourceBoundProviderVerifier(Reader(source), auth)
        proof = verifier.verify(
            binding.provider_observation_input,
            binding.evidence_document,
            prepared.source_receipt,
        )
        self.assertIsNotNone(proof)
        self.assertEqual(proof.observation["verified"], True)
        self.assertEqual(
            proof.source_ref,
            "jules-session:31415926535897932384",
        )
        self.assertEqual(len(auth.calls), 1)

    def test_only_explicit_running_readback_can_bind_active_acquire(self):
        prepared = bundle()
        for state in ("QUEUED", "COMPLETED"):
            with self.subTest(state=state):
                candidate = prepare_jules_provider_readback_candidate(
                    bundle=prepared,
                    session_readback=session_get(state=state),
                )
                with self.assertRaisesRegex(ValueError, "explicit RUNNING"):
                    bind_jules_active_provider_readback(
                        bundle=prepared,
                        candidate=candidate,
                    )


    def test_running_binding_rebinds_evidence_and_observation_to_readback_time(self):
        prepared = bundle()
        candidate = prepare_jules_provider_readback_candidate(
            bundle=prepared,
            session_readback=session_get(),
        )
        binding = bind_jules_active_provider_readback(
            bundle=prepared,
            candidate=candidate,
        )
        self.assertEqual(
            binding.evidence_document["observed_at"],
            "2026-09-28T04:05:00Z",
        )
        self.assertEqual(
            binding.provider_observation_input["observed_at"],
            "2026-09-28T04:05:00Z",
        )
        self.assertEqual(binding.evidence_document["provider_state"], "RUNNING")
        self.assertEqual(binding.provider_observation_input["state"], "RUNNING")
        self.assertEqual(
            binding.transition_request.evidence_document,
            binding.evidence_document,
        )
        self.assertEqual(
            binding.transition_request.provider_observation_input,
            binding.provider_observation_input,
        )

    def test_session_identity_and_create_time_must_match_acquire_bundle(self):
        prepared = bundle()
        wrong_id = session_get(name="sessions/999999")
        with self.assertRaisesRegex(ValueError, "name mismatch"):
            prepare_jules_provider_readback_candidate(
                bundle=prepared,
                session_readback=wrong_id,
            )

        wrong_time = session_get(createTime="2026-09-28T04:00:00Z")
        with self.assertRaisesRegex(ValueError, "createTime does not match"):
            prepare_jules_provider_readback_candidate(
                bundle=prepared,
                session_readback=wrong_time,
            )

    def test_update_time_must_be_inside_owner_lease(self):
        prepared = bundle()
        early = session_get(updateTime="2026-09-28T03:58:00Z")
        with self.assertRaisesRegex(ValueError, "predates"):
            prepare_jules_provider_readback_candidate(
                bundle=prepared,
                session_readback=early,
            )

        expired = session_get(updateTime="2026-09-28T06:00:00Z")
        with self.assertRaisesRegex(ValueError, "outside owner lease"):
            prepare_jules_provider_readback_candidate(
                bundle=prepared,
                session_readback=expired,
            )

    def test_private_urls_are_not_preserved_in_candidate_or_source(self):
        prepared = bundle()
        value = session_get(
            url="https://jules.google.com/session/private",
            outputs=[
                {
                    "pullRequest": {
                        "url": "https://github.com/kamiyusense/private/pull/1",
                    }
                }
            ],
        )
        candidate = prepare_jules_provider_readback_candidate(
            bundle=prepared,
            session_readback=value,
        )
        source = build_provider_verification_source(
            candidate,
            verification_state="UNKNOWN",
        )
        self.assertNotIn("https://", json.dumps(candidate.__dict__))
        self.assertNotIn("https://", json.dumps(source))

    def test_unknown_or_rejected_source_cannot_verify_even_with_authenticator(self):
        prepared = bundle()
        candidate = prepare_jules_provider_readback_candidate(
            bundle=prepared,
            session_readback=session_get(),
        )
        for state in ("UNKNOWN", "REJECTED"):
            with self.subTest(state=state):
                binding = bind_jules_active_provider_readback(
                    bundle=prepared,
                    candidate=candidate,
                )
                source = build_provider_verification_source(
                    candidate,
                    verification_state=state,
                )
                auth = Authenticator()
                verifier = SourceBoundProviderVerifier(Reader(source), auth)
                self.assertIsNone(
                    verifier.verify(
                        binding.provider_observation_input,
                        binding.evidence_document,
                        prepared.source_receipt,
                    )
                )
                self.assertEqual(auth.calls, [])

    def test_prepare_does_not_mutate_session_readback(self):
        prepared = bundle()
        raw = session_get()
        before = copy.deepcopy(raw)
        prepare_jules_provider_readback_candidate(
            bundle=prepared,
            session_readback=raw,
        )
        self.assertEqual(raw, before)


if __name__ == "__main__":
    unittest.main()
