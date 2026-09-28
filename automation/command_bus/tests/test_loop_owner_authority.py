from __future__ import annotations

import copy
import json
import unittest

from automation.command_bus.github_backend import GitHubContent
from automation.command_bus.loop_owner_authority import (
    AuthorityGrantGitHubBackend,
    AuthorityGrantProof,
    DurableOwnerAuthority,
    authority_grant_path,
    grant_for_event,
    validate_authority_grant,
)
from automation.command_bus.tests.test_loop_owner import (
    NOW,
    first_event,
    next_event,
    receipt_for,
    target_for,
)
from automation.command_bus.tests.test_loop_status_issue import state


VERIFICATION_REF = "automation/command_bus/evidence/loop-015/authority-1.json"


class FakeClient:
    def __init__(self):
        self.data: dict[str, GitHubContent] = {}
        self.creates = 0
        self.fail_after_write = False

    def get(self, path: str, ref: str):
        return self.data.get(path)

    def create(self, path: str, text: str, message: str, branch: str):
        self.creates += 1
        if path in self.data:
            raise RuntimeError("create-only conflict")
        content = GitHubContent(path=path, text=text, sha=f"sha-{self.creates}")
        self.data[path] = content
        if self.fail_after_write:
            raise OSError("ambiguous create")
        return content


class Clock:
    def __init__(self, now=NOW):
        self.value = now

    def now(self):
        return self.value


class Verifier:
    def __init__(self, *, accept=True, source_ref=VERIFICATION_REF):
        self.accept = accept
        self.source_ref = source_ref
        self.calls = 0

    def verify(self, grant, event, prior_state, target, receipt, chain):
        self.calls += 1
        if not self.accept:
            return None
        return AuthorityGrantProof(copy.deepcopy(grant), self.source_ref)


def grant(event=None, **changes):
    event = event or first_event()
    value = grant_for_event(
        event,
        authority_id=f"authority-{event['generation']}",
        issued_at="2026-09-27T08:55:00+00:00",
        verification_ref=(
            f"automation/command_bus/evidence/{event['loop_id']}/"
            f"authority-{event['generation']}.json"
        ),
    )
    value.update(changes)
    return value


def prior_state(event=None):
    event = event or first_event()
    return state(
        last_command_id=event["command_id"],
        last_receipt_id=event["source_receipt_id"],
        expected_target=target_for(event),
    )


class DurableOwnerAuthorityTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.event = first_event()
        self.grant = grant(self.event)
        self.path = authority_grant_path(self.event["loop_id"], self.event["generation"])

    def put_grant(self, value=None):
        record = value or self.grant
        self.client.data[self.path] = GitHubContent(
            path=self.path,
            text=json.dumps(record, sort_keys=True, separators=(",", ":")),
            sha="grant-sha",
        )

    def authority(self, verifier=None, clock=None):
        return DurableOwnerAuthority(
            self.client,
            branch="runtime-ledger",
            verifier=verifier,
            clock=clock or Clock(),
        )

    def authorize(self, verifier=None, event=None, chain=None, clock=None):
        event = event or self.event
        chain = [] if chain is None else chain
        return self.authority(verifier, clock).authorize(
            event,
            prior_state(event),
            target_for(event),
            receipt_for(event),
            chain,
        )

    def test_grant_record_alone_is_not_authority(self):
        self.put_grant()
        self.assertIsNone(self.authorize(verifier=None))

    def test_exact_grant_plus_independent_proof_returns_authorized_context(self):
        self.put_grant()
        verifier = Verifier()
        result = self.authorize(verifier)
        self.assertIsNotNone(result)
        self.assertEqual(
            (result.owner_role, result.holder_id, result.generation, result.fencing_token),
            ("SEMI_AUTO", "controller-1", 1, 1),
        )
        self.assertEqual(verifier.calls, 1)

    def test_missing_rejected_or_wrong_source_proof_fails_closed(self):
        self.put_grant()
        self.assertIsNone(self.authorize(Verifier(accept=False)))
        wrong = Verifier(source_ref="automation/command_bus/evidence/loop-015/other.json")
        self.assertIsNone(self.authorize(wrong))

    def test_expired_future_or_short_grant_fails_closed(self):
        self.put_grant()
        self.assertIsNone(self.authorize(Verifier(), clock=Clock("2026-09-27T11:00:00+00:00")))

        future = grant(self.event, issued_at="2026-09-27T09:05:00+00:00")
        self.put_grant(future)
        self.assertIsNone(self.authorize(Verifier()))

        short = grant(self.event, expires_at="2026-09-27T10:30:00+00:00")
        self.put_grant(short)
        self.assertIsNone(self.authorize(Verifier()))

    def test_grant_event_context_mismatch_fails_closed(self):
        for key, value in (
            ("owner_role", "AUTO"),
            ("holder_id", "other-holder"),
            ("expected_target_head", "b" * 40),
            ("command_id", "other-command"),
            ("correlation_id", "other-correlation"),
        ):
            with self.subTest(key=key):
                bad = grant(self.event)
                bad[key] = value
                self.put_grant(bad)
                self.assertIsNone(self.authorize(Verifier()))

    def test_chain_frontier_and_handoff_are_checked(self):
        first = self.event
        second = next_event(
            first,
            event_type="HANDOFF",
            owner_role="AUTO",
            holder_id="controller-2",
            head="b" * 40,
        )
        second_grant = grant(second)
        path = authority_grant_path(second["loop_id"], second["generation"])
        self.client.data[path] = GitHubContent(
            path=path,
            text=json.dumps(second_grant, sort_keys=True, separators=(",", ":")),
            sha="g2",
        )
        verifier = Verifier(
            source_ref="automation/command_bus/evidence/loop-015/authority-2.json"
        )
        authority = self.authority(verifier)
        bound = state(
            state="RUNNING",
            last_command_id=first["command_id"],
            last_receipt_id=first["source_receipt_id"],
            expected_target=target_for(first),
        )
        result = authority.authorize(
            second,
            bound,
            target_for(second),
            receipt_for(second),
            [first],
        )
        self.assertIsNotNone(result)
        self.assertEqual((result.owner_role, result.generation), ("AUTO", 2))

        self.assertIsNone(
            authority.authorize(
                second,
                prior_state(second),
                target_for(second),
                receipt_for(second),
                [],
            )
        )

    def test_generation_two_authority_requires_state_bound_to_frontier(self):
        first = self.event
        second = next_event(
            first,
            event_type="HANDOFF",
            owner_role="AUTO",
            holder_id="controller-2",
            head="b" * 40,
        )
        second_grant = grant(second)
        path = authority_grant_path(second["loop_id"], second["generation"])
        self.client.data[path] = GitHubContent(
            path=path,
            text=json.dumps(second_grant, sort_keys=True, separators=(",", ":")),
            sha="g2",
        )
        verifier = Verifier(
            source_ref="automation/command_bus/evidence/loop-015/authority-2.json"
        )
        authority = self.authority(verifier)
        stale = state(state="PREPARED")
        result = authority.authorize(
            second,
            stale,
            target_for(second),
            receipt_for(second),
            [first],
        )
        self.assertIsNone(result)

        bound = state(
            state="RUNNING",
            last_command_id=first["command_id"],
            last_receipt_id=first["source_receipt_id"],
            expected_target=target_for(first),
        )
        result = authority.authorize(
            second,
            bound,
            target_for(second),
            receipt_for(second),
            [first],
        )
        self.assertIsNotNone(result)

    def test_existing_generation_recovery_is_supported(self):
        self.put_grant()
        result = self.authority(Verifier()).authorize(
            self.event,
            prior_state(self.event),
            target_for(self.event),
            receipt_for(self.event),
            [self.event],
        )
        self.assertIsNotNone(result)

    def test_writer_accepts_recovery_conflict_and_ambiguous_create_without_retry(self):
        backend = AuthorityGrantGitHubBackend(self.client, branch="runtime-ledger")
        first = backend.write(self.grant)
        self.assertEqual(first.status, "ACCEPTED")
        self.assertEqual(self.client.creates, 1)
        recovered = backend.write(copy.deepcopy(self.grant))
        self.assertEqual(recovered.status, "RECOVERED")
        self.assertEqual(self.client.creates, 1)

        conflict = copy.deepcopy(self.grant)
        conflict["authority_id"] = "authority-conflict"
        self.assertEqual(backend.write(conflict).status, "BLOCKED")
        self.assertEqual(self.client.creates, 1)

        client = FakeClient()
        client.fail_after_write = True
        backend = AuthorityGrantGitHubBackend(client, branch="runtime-ledger")
        result = backend.write(self.grant)
        self.assertEqual(result.status, "ACCEPTED")
        self.assertEqual(client.creates, 1)

    def test_schema_rejects_unknown_bool_generation_and_cross_loop_verification(self):
        for mutate in (
            lambda value: value.update(untrusted=True),
            lambda value: value.update(generation=True, fencing_token=True),
            lambda value: value.update(
                verification_ref="automation/command_bus/evidence/other-loop/authority.json"
            ),
        ):
            bad = grant(self.event)
            mutate(bad)
            with self.assertRaises(ValueError):
                validate_authority_grant(bad)

    def test_path_is_canonical(self):
        self.assertEqual(
            authority_grant_path("loop-015", 1),
            "automation/command_bus/loop_owner_authorities/loop-015/000001.json",
        )
        with self.assertRaises(ValueError):
            authority_grant_path("../bad", 1)


if __name__ == "__main__":
    unittest.main()
