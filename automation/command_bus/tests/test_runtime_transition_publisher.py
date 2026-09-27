from __future__ import annotations

import copy
import json
import unittest

from automation.command_bus.github_backend import GitHubContent
from automation.command_bus.loop_owner_backend import owner_event_path
from automation.command_bus.runtime_transition_coordinator import (
    AuthorizedOwnerContext, RuntimeTransitionPublisher, TransitionRequest,
    VerifiedProviderObservation,
)
from automation.command_bus.runtime_transition_evidence import evidence_path, validate_evidence_document
from automation.command_bus.runtime_transition_writers import CanonicalEvidenceGitHubBackend
from automation.command_bus.tests.test_loop_owner import (
    NOW, first_event, observation_for, receipt_for, target_for,
)
from automation.command_bus.tests.test_loop_status_issue import state


class Client:
    def __init__(self):
        self.data = {}
        self.creates = 0
        self.updates = 0
        self.fail_create_after_write = False
        self.fail_update_after_write = False
        self.fail_update_before_write = False

    def put(self, path, record):
        self.data[path] = GitHubContent(path, json.dumps(record, sort_keys=True, separators=(",", ":")), "initial")

    def get(self, path, ref):
        return self.data.get(path)

    def list(self, prefix, ref):
        return [self.data[key] for key in sorted(self.data) if key.startswith(prefix)]

    def create(self, path, text, message, branch):
        self.creates += 1
        if path in self.data:
            raise RuntimeError("already exists")
        self.data[path] = GitHubContent(path, text, f"create-{self.creates}")
        if self.fail_create_after_write:
            raise RuntimeError("ambiguous create")
        return self.data[path]

    def update(self, path, text, sha, message, branch):
        self.updates += 1
        if self.fail_update_before_write:
            raise RuntimeError("ambiguous update")
        if self.data[path].sha != sha:
            raise RuntimeError("CAS conflict")
        self.data[path] = GitHubContent(path, text, f"update-{self.updates}")
        if self.fail_update_after_write:
            raise RuntimeError("ambiguous update")
        return self.data[path]


class Target:
    def __init__(self, target):
        self.value = target

    def read_target(self, repository, pr_number):
        return self.value


class Authority:
    def authorize(self, event, prior_state, target, receipt, chain):
        return AuthorizedOwnerContext(**{key: event[key] for key in AuthorizedOwnerContext.__dataclass_fields__})


class Verifier:
    def verify(self, candidate, evidence, receipt):
        return VerifiedProviderObservation({**candidate, "verified": True}, evidence["provider_readback"])


class Status:
    def __init__(self):
        self.plans = []

    def prepare(self, plan):
        self.plans.append(plan)


class Clock:
    def now(self):
        return NOW


def evidence(event):
    return {
        "schema_version": 1, "evidence_id": "owner-1", "loop_id": event["loop_id"],
        "generation": event["generation"], "command_id": event["command_id"],
        "correlation_id": event["correlation_id"], "expected_repo": event["expected_repo"],
        "expected_pr": event["expected_pr"], "expected_target_head": event["expected_target_head"],
        "source_receipt_ref": event["source_receipt_ref"], "provider_kind": "JULES",
        "provider_state": "RUNNING", "observed_at": "2026-09-27T09:30:00+00:00",
        "external_refs": [], "test_results": [], "provider_readback": "provider:observation-1",
        "publication_evidence": None,
    }


class RuntimeTransitionPublisherTests(unittest.TestCase):
    def setUp(self):
        self.event = first_event()
        self.client = Client()
        self.target = Target(target_for(self.event))
        self.status = Status()
        self.prior = state(state="PREPARED")
        self.desired = state(
            state="RUNNING", last_command_id=self.event["command_id"],
            last_receipt_id=self.event["source_receipt_id"], expected_target=target_for(self.event),
        )
        self.evidence = evidence(self.event)
        self.observation = observation_for(self.event)
        self.observation.pop("verified")
        self.client.put("automation/command_bus/state/loop-015.json", self.prior)
        self.client.put(self.event["source_receipt_ref"], receipt_for(self.event))

    def publisher(self, *, authority=True, verifier=True, status=True):
        return RuntimeTransitionPublisher(
            self.client, branch="runtime-ledger", target_reader=self.target,
            owner_authority=Authority() if authority else None,
            provider_verifier=Verifier() if verifier else None,
            status_boundary=self.status if status else None, clock=Clock(),
        )

    def request(self):
        return TransitionRequest(self.event, self.evidence, self.observation, self.prior, self.desired)

    def test_evidence_path_rejects_traversal_and_secret_url(self):
        self.assertEqual(validate_evidence_document(self.evidence), evidence_path("loop-015", "owner-1"))
        bad = copy.deepcopy(self.evidence)
        bad["source_receipt_ref"] = "automation/command_bus/receipts/loop-015/../other.json"
        with self.assertRaises(ValueError):
            validate_evidence_document(bad)
        bad = copy.deepcopy(self.evidence)
        bad["external_refs"] = ["https://example.com/token"]
        with self.assertRaises(ValueError):
            validate_evidence_document(bad)

    def test_create_only_evidence_readback_recovery_and_conflict(self):
        writer = CanonicalEvidenceGitHubBackend(self.client, branch="runtime-ledger")
        self.client.fail_create_after_write = True
        self.assertEqual(writer.write(self.evidence).status, "ACCEPTED")
        self.assertEqual(writer.write(self.evidence).status, "RECOVERED")
        self.assertEqual(self.client.creates, 1)
        changed = copy.deepcopy(self.evidence)
        changed["provider_state"] = "FAILED"
        self.assertEqual(writer.write(changed).status, "BLOCKED")

    def test_success_after_all_readbacks_and_replay_prepares_status(self):
        publisher = self.publisher()
        result = publisher.publish(self.request())
        self.assertEqual((result.status, result.status_plan.display_state), ("READY", "SEMI_AUTO"), result)
        self.assertEqual((self.client.creates, self.client.updates), (3, 1))
        self.assertIn(owner_event_path("loop-015", 1), self.client.data)
        replay = publisher.publish(self.request())
        self.assertEqual(replay.status, "READY", replay)
        self.assertEqual((self.client.creates, self.client.updates), (3, 1))
        self.assertEqual(len(self.status.plans), 2)

    def test_no_authority_or_verifier_makes_no_writes(self):
        for kwargs in ({"authority": False}, {"verifier": False}):
            with self.subTest(kwargs=kwargs):
                result = self.publisher(**kwargs).publish(self.request())
                self.assertEqual(result.status, "NOT_WIRED", result)
                self.assertEqual((self.client.creates, self.client.updates), (0, 0))

    def test_target_or_receipt_mismatch_makes_no_writes(self):
        self.target.value = {**target_for(self.event), "head": "b" * 40}
        self.assertEqual(self.publisher().publish(self.request()).status, "BLOCKED")
        self.target.value = target_for(self.event)
        self.client.put(self.event["source_receipt_ref"], {**receipt_for(self.event), "retry_count": 1})
        self.assertEqual(self.publisher().publish(self.request()).status, "UNKNOWN")
        self.assertEqual((self.client.creates, self.client.updates), (0, 0))

    def test_ambiguous_state_write_readback_and_no_retry(self):
        self.client.fail_update_after_write = True
        result = self.publisher().publish(self.request())
        self.assertEqual(result.status, "READY", result)
        self.assertEqual(self.client.updates, 1)

    def test_unresolved_state_write_requires_recovery_not_resend(self):
        self.client.fail_update_before_write = True
        result = self.publisher().publish(self.request())
        self.assertEqual(result.status, "UNKNOWN", result)
        self.assertEqual(self.client.updates, 1)
        self.assertEqual(len(self.status.plans), 0)
        self.client.fail_update_before_write = False
        recovered = self.publisher().publish(self.request())
        self.assertEqual(recovered.status, "READY", recovered)
        self.assertEqual(self.client.creates, 3)
        self.assertEqual(self.client.updates, 2)


if __name__ == "__main__":
    unittest.main()
