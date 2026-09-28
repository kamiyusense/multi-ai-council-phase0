from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from automation.command_bus.loop_owner_authority import grant_for_event
from automation.command_bus.runtime_owner_main_policy import (
    MainPolicyAuthorityAuthenticator,
    RuntimeOwnerPolicyReadback,
    validate_runtime_owner_policy,
)
from automation.command_bus.runtime_verifier_sources import (
    SourceBoundAuthorityGrantVerifier,
    VerifiedSourceAttestation,
)
from automation.command_bus.tests.test_loop_owner import (
    first_event,
    receipt_for,
    target_for,
)
from automation.command_bus.tests.test_loop_owner_authority import prior_state


POLICY_PATH = (
    Path(__file__).parents[1] / "config" / "runtime_owner_policy.json"
)
MAIN_SHA = "c" * 40
OBSERVED = "2026-09-27T09:00:00+00:00"
EXPIRES = "2026-09-27T11:00:00+00:00"
NOW = "2026-09-27T10:00:00+00:00"


def policy_entry(**changes):
    value = {
        "policy_id": "policy-semi-pr4",
        "enabled": True,
        "loop_id": "loop-015",
        "owner_role": "SEMI_AUTO",
        "holder_id": "controller-1",
        "expected_repo": "kamiyusense/multi-ai-council-phase0",
        "expected_pr": 4,
        "allowed_event_types": ["ACQUIRE", "RENEW"],
        "max_lease_seconds": 7200,
    }
    value.update(changes)
    return value


def policy_document(*entries):
    return {
        "schema_version": 1,
        "policies": list(entries),
    }


def authority_source(event=None, **changes):
    event = event or first_event()
    verification_ref = (
        f"automation/command_bus/evidence/{event['loop_id']}/authority-1.json"
    )
    value = {
        "schema_version": 1,
        "verification_kind": "AUTHORITY_GRANT",
        "source_id": "authority-source-1",
        "source_ref": verification_ref,
        "verification_state": "VERIFIED",
        "observed_at": OBSERVED,
        "expires_at": EXPIRES,
        "authority_id": "authority-1",
        "loop_id": event["loop_id"],
        "owner_role": event["owner_role"],
        "holder_id": event["holder_id"],
        "generation": event["generation"],
        "fencing_token": event["fencing_token"],
        "previous_generation": event["previous_generation"],
        "event_type": event["event_type"],
        "expected_repo": event["expected_repo"],
        "expected_pr": event["expected_pr"],
        "expected_target_head": event["expected_target_head"],
        "command_id": event["command_id"],
        "correlation_id": event["correlation_id"],
        "proof_refs": [
            "policy:policy-semi-pr4",
            f"github-main:{MAIN_SHA}",
        ],
    }
    value.update(changes)
    return value


def expected(raw=None):
    raw = raw or authority_source()
    keys = (
        "authority_id",
        "loop_id",
        "owner_role",
        "holder_id",
        "generation",
        "fencing_token",
        "previous_generation",
        "event_type",
        "expected_repo",
        "expected_pr",
        "expected_target_head",
        "command_id",
        "correlation_id",
    )
    value = {key: raw[key] for key in keys}
    value.update(
        verification_kind="AUTHORITY_GRANT",
        source_ref=raw["source_ref"],
        expires_at=raw["expires_at"],
    )
    return value


class PolicyReader:
    def __init__(self, document, *, ref="main", sha=MAIN_SHA, path=None):
        self.readback = RuntimeOwnerPolicyReadback(
            document=copy.deepcopy(document),
            ref=ref,
            commit_sha=sha,
            path=path or "automation/command_bus/config/runtime_owner_policy.json",
        )
        self.calls = 0

    def read_policy(self):
        self.calls += 1
        return copy.deepcopy(self.readback)


class Clock:
    def __init__(self, value=NOW):
        self.value = value
        self.calls = 0

    def now(self):
        self.calls += 1
        return self.value


class SourceReader:
    def __init__(self, source):
        self.source = copy.deepcopy(source)
        self.calls = 0

    def read(self, source_ref):
        self.calls += 1
        return copy.deepcopy(self.source)


class RuntimeOwnerMainPolicyTests(unittest.TestCase):
    def test_repository_policy_is_empty_and_grants_nothing(self):
        raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
        validate_runtime_owner_policy(raw)
        self.assertEqual(raw, {"schema_version": 1, "policies": []})

        reader = PolicyReader(raw)
        auth = MainPolicyAuthorityAuthenticator(
            policy_reader=reader,
            clock=Clock(),
        )
        self.assertIsNone(
            auth.authenticate(authority_source(), expected=expected())
        )
        self.assertEqual(reader.calls, 1)

    def test_exact_enabled_main_policy_returns_attestation(self):
        raw = authority_source()
        reader = PolicyReader(policy_document(policy_entry()))
        clock = Clock()
        auth = MainPolicyAuthorityAuthenticator(
            policy_reader=reader,
            clock=clock,
        )
        result = auth.authenticate(raw, expected=expected(raw))
        self.assertEqual(
            result,
            VerifiedSourceAttestation(
                "AUTHORITY_GRANT",
                raw["source_id"],
                raw["source_ref"],
                raw["observed_at"],
            ),
        )
        self.assertEqual(reader.calls, 1)
        self.assertEqual(clock.calls, 1)

    def test_disabled_or_wrong_policy_binding_fails_closed(self):
        raw = authority_source()
        cases = [
            policy_entry(enabled=False),
            policy_entry(loop_id="other-loop"),
            policy_entry(owner_role="AUTO"),
            policy_entry(holder_id="other-holder"),
            policy_entry(expected_repo="other/repo"),
            policy_entry(expected_pr=5),
            policy_entry(allowed_event_types=["RENEW"]),
        ]
        for entry in cases:
            with self.subTest(entry=entry):
                auth = MainPolicyAuthorityAuthenticator(
                    policy_reader=PolicyReader(policy_document(entry)),
                    clock=Clock(),
                )
                self.assertIsNone(auth.authenticate(raw, expected=expected(raw)))

    def test_policy_lease_cap_is_enforced(self):
        raw = authority_source()
        auth = MainPolicyAuthorityAuthenticator(
            policy_reader=PolicyReader(
                policy_document(policy_entry(max_lease_seconds=3600))
            ),
            clock=Clock(),
        )
        self.assertIsNone(auth.authenticate(raw, expected=expected(raw)))

    def test_policy_must_be_fresh_main_exact_path_and_sha(self):
        raw = authority_source()
        readers = [
            PolicyReader(policy_document(policy_entry()), ref="feature/policy"),
            PolicyReader(policy_document(policy_entry()), sha="not-a-sha"),
            PolicyReader(policy_document(policy_entry()), path="docs/policy.json"),
        ]
        for reader in readers:
            with self.subTest(readback=reader.readback):
                auth = MainPolicyAuthorityAuthenticator(
                    policy_reader=reader,
                    clock=Clock(),
                )
                self.assertIsNone(auth.authenticate(raw, expected=expected(raw)))

    def test_required_policy_and_main_commit_proof_refs_are_enforced(self):
        raw = authority_source(proof_refs=["policy:policy-semi-pr4"])
        auth = MainPolicyAuthorityAuthenticator(
            policy_reader=PolicyReader(policy_document(policy_entry())),
            clock=Clock(),
        )
        self.assertIsNone(auth.authenticate(raw, expected=expected(raw)))

        raw = authority_source(proof_refs=[f"github-main:{MAIN_SHA}"])
        auth = MainPolicyAuthorityAuthenticator(
            policy_reader=PolicyReader(policy_document(policy_entry())),
            clock=Clock(),
        )
        self.assertIsNone(auth.authenticate(raw, expected=expected(raw)))

    def test_unknown_source_expected_mismatch_and_time_window_fail_before_policy_read(self):
        cases = []
        raw = authority_source(verification_state="UNKNOWN")
        cases.append((raw, expected(raw), NOW))

        raw = authority_source()
        exp = expected(raw)
        exp["expected_pr"] = 5
        cases.append((raw, exp, NOW))

        raw = authority_source()
        cases.append((raw, expected(raw), "2026-09-27T08:59:59+00:00"))

        raw = authority_source()
        cases.append((raw, expected(raw), EXPIRES))

        for raw, exp, now in cases:
            with self.subTest(raw=raw, exp=exp, now=now):
                reader = PolicyReader(policy_document(policy_entry()))
                auth = MainPolicyAuthorityAuthenticator(
                    policy_reader=reader,
                    clock=Clock(now),
                )
                self.assertIsNone(auth.authenticate(raw, expected=exp))
                self.assertEqual(reader.calls, 0)

    def test_duplicate_policy_ids_or_enabled_bindings_fail_closed(self):
        duplicate_id = policy_document(
            policy_entry(),
            policy_entry(expected_pr=5),
        )
        with self.assertRaisesRegex(ValueError, "duplicate runtime owner policy_id"):
            validate_runtime_owner_policy(duplicate_id)

        duplicate_binding = policy_document(
            policy_entry(policy_id="policy-a"),
            policy_entry(policy_id="policy-b"),
        )
        with self.assertRaisesRegex(ValueError, "duplicate enabled"):
            validate_runtime_owner_policy(duplicate_binding)

    def test_source_bound_authority_verifier_accepts_policy_authenticated_source(self):
        event = first_event()
        raw = authority_source(event)
        grant = grant_for_event(
            event,
            authority_id="authority-1",
            issued_at="2026-09-27T08:55:00+00:00",
            verification_ref=raw["source_ref"],
        )
        source_reader = SourceReader(raw)
        authenticator = MainPolicyAuthorityAuthenticator(
            policy_reader=PolicyReader(policy_document(policy_entry())),
            clock=Clock(),
        )
        verifier = SourceBoundAuthorityGrantVerifier(
            source_reader,
            authenticator,
        )
        proof = verifier.verify(
            grant,
            event,
            prior_state(event),
            target_for(event),
            receipt_for(event),
            [],
        )
        self.assertIsNotNone(proof)
        self.assertEqual(proof.source_ref, raw["source_ref"])
        self.assertEqual(source_reader.calls, 1)

    def test_empty_repository_policy_keeps_source_bound_authority_not_wired(self):
        event = first_event()
        raw = authority_source(event)
        grant = grant_for_event(
            event,
            authority_id="authority-1",
            issued_at="2026-09-27T08:55:00+00:00",
            verification_ref=raw["source_ref"],
        )
        verifier = SourceBoundAuthorityGrantVerifier(
            SourceReader(raw),
            MainPolicyAuthorityAuthenticator(
                policy_reader=PolicyReader(
                    {"schema_version": 1, "policies": []}
                ),
                clock=Clock(),
            ),
        )
        self.assertIsNone(
            verifier.verify(
                grant,
                event,
                prior_state(event),
                target_for(event),
                receipt_for(event),
                [],
            )
        )


if __name__ == "__main__":
    unittest.main()
