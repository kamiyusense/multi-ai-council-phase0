from __future__ import annotations

import copy
import unittest

from automation.command_bus.jules_direct_readback_authenticator import (
    JulesDirectReadbackAuthenticator,
)
from automation.command_bus.runtime_verifier_sources import VerifiedSourceAttestation


HEAD = "a" * 40
REPO = "kamiyusense/multi-ai-council-phase0"
SESSION_ID = "31415926535897932384"
TARGET_BRANCH = TARGET_BRANCH
WORK_BRANCH = "jules-work/relay-dev-loop-900-current-runtime-binding"
OBSERVED = "2026-09-28T03:59:00+00:00"
EXPIRES = "2026-09-28T06:00:00+00:00"


def source(**changes):
    value = {
        "schema_version": 1,
        "verification_kind": "PROVIDER_OBSERVATION",
        "source_id": "jules-source-31415926535897932384",
        "source_ref": f"jules-session:{SESSION_ID}",
        "verification_state": "VERIFIED",
        "observed_at": OBSERVED,
        "expires_at": EXPIRES,
        "provider_kind": "JULES",
        "provider_state": "RUNNING",
        "observation_id": "jules-session-31415926535897932384",
        "loop_id": "chatgpt-semi-auto-v1",
        "owner_role": "SEMI_AUTO",
        "holder_id": "chatgpt-controller",
        "generation": 1,
        "fencing_token": 1,
        "expected_repo": REPO,
        "expected_pr": 4,
        "expected_target_head": HEAD,
        "command_id": "relay-dev-durable-smoke-001",
        "correlation_id": "semi-durable-001",
        "source_receipt_ref": (
            "automation/command_bus/receipts/chatgpt-semi-auto-v1/"
            "dispatch-relay-dev-durable-smoke-001.json"
        ),
        "evidence_ref": (
            "automation/command_bus/evidence/chatgpt-semi-auto-v1/"
            "dispatch-relay-dev-durable-smoke-001.json"
        ),
        "proof_refs": [
            f"jules-session:{SESSION_ID}",
            "github-pr:4",
            f"github-head:{HEAD}",
        ],
    }
    value.update(changes)
    return value


def expected(value=None):
    value = value or source()
    keys = (
        "verification_kind",
        "source_ref",
        "provider_kind",
        "provider_state",
        "observation_id",
        "loop_id",
        "owner_role",
        "holder_id",
        "generation",
        "fencing_token",
        "expected_repo",
        "expected_pr",
        "expected_target_head",
        "command_id",
        "correlation_id",
        "source_receipt_ref",
        "evidence_ref",
        "observed_at",
        "expires_at",
    )
    return {key: value[key] for key in keys}


def session(**changes):
    value = {
        "name": f"sessions/{SESSION_ID}",
        "id": SESSION_ID,
        "state": "IN_PROGRESS",
        "createTime": OBSERVED,
        "sourceContext": {
            "source": f"sources/github/{REPO}",
            "githubRepoContext": {
                "startingBranch": TARGET_BRANCH,
            },
        },
    }
    value.update(changes)
    return value


def target(**changes):
    value = {
        "number": 4,
        "state": "open",
        "merged": False,
        "head": {
            "ref": TARGET_BRANCH,
            "sha": HEAD,
        },
        "repo": {"full_name": REPO},
    }
    value.update(changes)
    return value


class SessionReader:
    def __init__(self, value):
        self.value = copy.deepcopy(value)
        self.calls = []

    def read_session(self, session_id):
        self.calls.append(session_id)
        return copy.deepcopy(self.value)


class TargetReader:
    def __init__(self, value):
        self.value = copy.deepcopy(value)
        self.calls = []

    def read_target(self, repository, pr_number):
        self.calls.append((repository, pr_number))
        return copy.deepcopy(self.value)


class Clock:
    def __init__(self, value="2026-09-28T04:10:00+00:00"):
        self.value = value
        self.calls = 0

    def now(self):
        self.calls += 1
        return self.value


def authenticator(*, raw_session=None, raw_target=None, now=None):
    session_reader = SessionReader(raw_session or session())
    target_reader = TargetReader(raw_target or target())
    clock = Clock(now or "2026-09-28T04:10:00+00:00")
    auth = JulesDirectReadbackAuthenticator(
        session_reader=session_reader,
        target_reader=target_reader,
        clock=clock,
    )
    return auth, session_reader, target_reader, clock


class JulesDirectReadbackAuthenticatorTests(unittest.TestCase):
    def test_fresh_provider_and_target_readbacks_return_attestation(self):
        auth, sessions, targets, clock = authenticator()
        raw = source()
        result = auth.authenticate(raw, expected=expected(raw))
        self.assertEqual(
            result,
            VerifiedSourceAttestation(
                "PROVIDER_OBSERVATION",
                raw["source_id"],
                raw["source_ref"],
                raw["observed_at"],
            ),
        )
        self.assertEqual(sessions.calls, [SESSION_ID])
        self.assertEqual(targets.calls, [(REPO, 4)])
        self.assertEqual(clock.calls, 1)

    def test_missing_any_independent_reader_fails_closed(self):
        raw = source()
        for kwargs in (
            {"session_reader": None, "target_reader": TargetReader(target()), "clock": Clock()},
            {"session_reader": SessionReader(session()), "target_reader": None, "clock": Clock()},
            {"session_reader": SessionReader(session()), "target_reader": TargetReader(target()), "clock": None},
        ):
            with self.subTest(kwargs=kwargs):
                auth = JulesDirectReadbackAuthenticator(**kwargs)
                self.assertIsNone(auth.authenticate(raw, expected=expected(raw)))

    def test_only_conservative_active_jules_states_map_to_running(self):
        raw = source()
        for state_value in ("QUEUED", "PLANNING", "IN_PROGRESS"):
            auth, _, _, _ = authenticator(raw_session=session(state=state_value))
            self.assertIsNotNone(
                auth.authenticate(raw, expected=expected(raw)),
                state_value,
            )
        for state_value in (
            "COMPLETED",
            "FAILED",
            "PAUSED",
            "AWAITING_PLAN_APPROVAL",
            "AWAITING_USER_FEEDBACK",
        ):
            auth, _, _, _ = authenticator(raw_session=session(state=state_value))
            self.assertIsNone(
                auth.authenticate(raw, expected=expected(raw)),
                state_value,
            )

    def test_session_identity_create_time_repo_and_branch_must_match(self):
        raw = source()
        bad_sessions = [
            session(name="sessions/999"),
            session(id="999"),
            session(createTime="2026-09-28T04:00:00+00:00"),
            session(sourceContext={
                "source": "sources/github/other/repo",
                "githubRepoContext": {
                    "startingBranch": TARGET_BRANCH
                },
            }),
            session(sourceContext={
                "source": f"sources/github/{REPO}",
                "githubRepoContext": {"startingBranch": "feature/other"},
            }),
        ]
        for raw_session in bad_sessions:
            with self.subTest(raw_session=raw_session):
                auth, _, _, _ = authenticator(raw_session=raw_session)
                self.assertIsNone(auth.authenticate(raw, expected=expected(raw)))

    def test_fresh_target_repo_pr_head_branch_and_open_state_must_match(self):
        raw = source()
        cases = [
            target(number=5),
            target(repo={"full_name": "other/repo"}),
            target(head={
                "ref": TARGET_BRANCH,
                "sha": "b" * 40,
            }),
            target(head={"ref": "feature/other", "sha": HEAD}),
            target(state="closed"),
            target(merged=True),
        ]
        for raw_target in cases:
            with self.subTest(raw_target=raw_target):
                auth, _, _, _ = authenticator(raw_target=raw_target)
                self.assertIsNone(auth.authenticate(raw, expected=expected(raw)))

    def test_current_carrier_separates_target_and_provider_branch_proofs(self):
        refs = [
            f"jules-session:{SESSION_ID}",
            "github-pr:4",
            f"github-head:{HEAD}",
            f"github-branch:{TARGET_BRANCH}",
            f"jules-branch:{WORK_BRANCH}",
        ]
        raw = source(proof_refs=refs)
        raw_session = session(sourceContext={
            "source": f"sources/github/{REPO}",
            "githubRepoContext": {"startingBranch": WORK_BRANCH},
        })
        raw_target = target(head={"ref": TARGET_BRANCH, "sha": HEAD})
        auth, _, _, _ = authenticator(
            raw_session=raw_session,
            raw_target=raw_target,
        )
        self.assertIsNotNone(auth.authenticate(raw, expected=expected(raw)))

        for bad_refs in (
            [ref for ref in refs if not ref.startswith("github-branch:")],
            [ref for ref in refs if not ref.startswith("jules-branch:")],
            [ref if not ref.startswith("github-branch:") else "github-branch:feature/other" for ref in refs],
            [ref if not ref.startswith("jules-branch:") else "jules-branch:jules-work/other" for ref in refs],
        ):
            with self.subTest(bad_refs=bad_refs):
                bad = source(proof_refs=bad_refs)
                auth, _, _, _ = authenticator(
                    raw_session=raw_session,
                    raw_target=raw_target,
                )
                self.assertIsNone(auth.authenticate(bad, expected=expected(bad)))

    def test_source_must_be_verified_before_authentication_is_attempted(self):
        raw = source(verification_state="UNKNOWN")
        auth, sessions, targets, clock = authenticator()
        self.assertIsNone(auth.authenticate(raw, expected=expected(raw)))
        self.assertEqual(sessions.calls, [])
        self.assertEqual(targets.calls, [])
        self.assertEqual(clock.calls, 0)

    def test_expected_context_mismatch_fails_before_direct_readback(self):
        raw = source()
        exp = expected(raw)
        exp["expected_target_head"] = "b" * 40
        auth, sessions, targets, _ = authenticator()
        self.assertIsNone(auth.authenticate(raw, expected=exp))
        self.assertEqual(sessions.calls, [])
        self.assertEqual(targets.calls, [])

    def test_expired_or_future_source_fails_before_provider_read(self):
        raw = source()
        for now in (
            "2026-09-28T03:58:59+00:00",
            "2026-09-28T06:00:00+00:00",
        ):
            auth, sessions, targets, _ = authenticator(now=now)
            self.assertIsNone(auth.authenticate(raw, expected=expected(raw)))
            self.assertEqual(sessions.calls, [])
            self.assertEqual(targets.calls, [])

    def test_required_direct_readback_proof_refs_must_be_present(self):
        raw = source(proof_refs=[f"jules-session:{SESSION_ID}"])
        auth, _, _, _ = authenticator()
        self.assertIsNone(auth.authenticate(raw, expected=expected(raw)))

        raw = source(proof_refs=[
            f"jules-session:{SESSION_ID}",
            "github-pr:4",
            f"github-head:{HEAD}",
        ])
        auth, _, _, _ = authenticator()
        self.assertIsNotNone(auth.authenticate(raw, expected=expected(raw)))

    def test_non_running_provider_state_is_not_invented(self):
        raw = source(provider_state="PAUSED")
        exp = expected(raw)
        auth, _, _, _ = authenticator(raw_session=session(state="PAUSED"))
        self.assertIsNone(auth.authenticate(raw, expected=exp))


if __name__ == "__main__":
    unittest.main()
