from datetime import datetime, timedelta, timezone
import json
import unittest

from automation.command_bus.github_backend import (
    GitHubContent,
    GitHubRecordBackend,
    record_path,
)
from automation.command_bus.reviewer import (
    ReviewerLedger,
    claim_request,
    consume_response,
    make_request_v2,
    submit_response,
)

NOW = datetime(2026, 9, 23, 0, 0, tzinfo=timezone.utc)
EXP = (NOW + timedelta(hours=1)).isoformat()
HEAD = "a" * 40
TREE = "b" * 40
LOOP = "hybrid-backend-001"


class FakeGitHub:
    def __init__(self):
        self.files = {}
        self.counter = 0

    def _content(self, path, text):
        self.counter += 1
        return GitHubContent(path, text, f"sha-{self.counter}")

    def get(self, path, ref):
        return self.files.get(path)

    def list(self, prefix, ref):
        return [value for path, value in self.files.items() if path.startswith(prefix)]

    def create(self, path, text, message, branch):
        if path in self.files:
            raise ValueError("exists")
        value = self._content(path, text)
        self.files[path] = value
        return value

    def update(self, path, text, sha, message, branch):
        if path not in self.files or self.files[path].sha != sha:
            raise ValueError("stale")
        value = self._content(path, text)
        self.files[path] = value
        return value


def state():
    return {
        "schema_version": 1,
        "loop_id": LOOP,
        "state": "RUNNING",
        "round": 0,
        "max_rounds": 6,
        "expires_at": EXP,
        "stop_requested": False,
        "last_command_id": None,
        "last_receipt_id": None,
        "expected_target": "work",
        "retry_policy": 0,
    }


def build():
    ledger = ReviewerLedger()
    req = make_request_v2(
        request_id="req-001",
        loop_id=LOOP,
        round=1,
        correlation_id=f"{LOOP}-round-1",
        expected_target_head=HEAD,
        expected_target_tree=TREE,
        reviewer_role="semantic-reviewer",
        review_kind="RELAY_SAFETY_DIFF",
        evidence_refs=["evidence://relay"],
        allowed_decisions=["APPROVE", "CHANGES_REQUIRED", "UNKNOWN"],
        expires_at=EXP,
    )
    ledger.append_request(req)
    assert claim_request(
        ledger,
        "req-001",
        claim_id="claim-001",
        reviewer_instance_id="sol-reviewer",
        reviewer_generation=1,
        role="semantic-reviewer",
        claimed_at=NOW,
    ).status == "CLAIMED"
    assert submit_response(
        ledger,
        "req-001",
        response_id="resp-001",
        reviewer_instance_id="sol-reviewer",
        reviewer_generation=1,
        decision="APPROVE",
        evidence_refs=["evidence://relay", "evidence://diff"],
        loop_id=LOOP,
        round=1,
        correlation_id=f"{LOOP}-round-1",
        expected_target_head=HEAD,
        expected_target_tree=TREE,
        rationale_summary="Safety invariants preserved in static diff.",
        next_command_proposal={"action": "STATIC_VALIDATE_COMMAND_BUS"},
        model_route_evidence={
            "route": "direct",
            "response_source": "GITHUB_DURABLE_ONLY",
            "live_browser_used": False,
        },
        submitted_at=NOW,
    ).status == "ACCEPTED"
    return ledger


class ReviewerV2BackendTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeGitHub()
        self.backend = GitHubRecordBackend(
            self.client, branch="feature/chat-work-command-bus"
        )

    def persist(self, ledger):
        for kind, records in (
            ("request", ledger.requests),
            ("claim", ledger.claims),
            ("response", ledger.responses),
        ):
            for record in records:
                self.assertEqual(
                    self.backend.append(kind, LOOP, record).status, "ACCEPTED"
                )
        self.assertEqual(self.backend.write_state(LOOP, state()).status, "ACCEPTED")

    def test_v2_records_recover_with_tree_identity(self):
        ledger = build()
        self.persist(ledger)
        recovered = self.backend.recover(
            LOOP,
            expected_ids={
                "request": ["req-001"],
                "claim": ["claim-001"],
                "response": ["resp-001"],
            },
        )
        self.assertEqual(recovered.status, "RECOVERED")
        req = recovered.record["ledger"].requests[0]
        self.assertEqual(req["expected_target_tree"], TREE)

    def test_v2_receipt_recovery_preserves_tree_identity(self):
        ledger = build()
        consumed = consume_response(
            ledger,
            "req-001",
            loop_id=LOOP,
            round=1,
            correlation_id=f"{LOOP}-round-1",
            expected_target_head=HEAD,
            expected_target_tree=TREE,
            now=NOW,
        )
        self.assertEqual(consumed.status, "VALID")
        self.persist(ledger)
        self.assertEqual(
            self.backend.append("receipt", LOOP, ledger.receipts[0]).status,
            "ACCEPTED",
        )
        recovered = self.backend.recover(
            LOOP, expected_ids={"receipt": ["review-resp-001"]}
        )
        self.assertEqual(recovered.status, "RECOVERED")
        receipt = recovered.record["ledger"].receipts[0]
        self.assertEqual(receipt["expected_target_tree"], TREE)

    def test_response_tree_mismatch_fails_append(self):
        ledger = build()
        req = ledger.requests[0]
        claim = ledger.claims[0]
        self.assertEqual(self.backend.append("request", LOOP, req).status, "ACCEPTED")
        self.assertEqual(self.backend.append("claim", LOOP, claim).status, "ACCEPTED")
        bad = dict(ledger.responses[0])
        bad["expected_target_tree"] = "c" * 40
        self.assertEqual(self.backend.append("response", LOOP, bad).status, "UNKNOWN")

    def test_wrong_claim_role_fails_append(self):
        ledger = build()
        req = ledger.requests[0]
        self.assertEqual(self.backend.append("request", LOOP, req).status, "ACCEPTED")
        bad = dict(ledger.claims[0])
        bad["role"] = "browser-transport"
        self.assertEqual(self.backend.append("claim", LOOP, bad).status, "UNKNOWN")

    def test_disallowed_decision_fails_durable_append(self):
        ledger = build()
        req = ledger.requests[0]
        claim = ledger.claims[0]
        self.assertEqual(self.backend.append("request", LOOP, req).status, "ACCEPTED")
        self.assertEqual(self.backend.append("claim", LOOP, claim).status, "ACCEPTED")
        bad = dict(ledger.responses[0])
        bad["decision"] = "MERGE_NOW"
        self.assertEqual(self.backend.append("response", LOOP, bad).status, "UNKNOWN")

    def test_fresh_recovery_rejects_corrupted_v2_tree(self):
        ledger = build()
        self.persist(ledger)
        path = record_path("response", LOOP, "resp-001")
        corrupted = dict(ledger.responses[0])
        corrupted["expected_target_tree"] = "c" * 40
        self.client.files[path] = GitHubContent(
            path, json.dumps(corrupted), "corrupted"
        )
        self.assertEqual(self.backend.recover(LOOP).status, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
