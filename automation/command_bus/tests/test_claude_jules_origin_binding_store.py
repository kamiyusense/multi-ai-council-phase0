import copy
import json
import unittest
from datetime import datetime, timezone

from automation.command_bus.claude_jules_origin_binding import build_binding_record
from automation.command_bus.claude_jules_origin_binding_store import (
    BindingStoreResult,
    ClaudeJulesOriginBindingStore,
    _get_path,
)
from automation.command_bus.github_backend import GitHubContent


class FakeGitHubContentsClient:
    def __init__(self):
        self.files: dict[tuple[str, str], GitHubContent] = {}
        self.create_calls = 0
        self.create_should_raise = False
        self.create_but_store = False

    def get(self, path: str, ref: str) -> GitHubContent | None:
        return self.files.get((path, ref))

    def list(self, prefix: str, ref: str) -> list[GitHubContent]:
        return [content for (path, _ref), content in self.files.items() if _ref == ref and path.startswith(prefix)]

    def create(self, path: str, text: str, message: str, branch: str) -> GitHubContent:
        self.create_calls += 1
        if self.create_should_raise:
            if self.create_but_store:
                self.files[(path, branch)] = GitHubContent(path, text, "fake-sha")
            raise RuntimeError("Fake create error")
        content = GitHubContent(path, text, "fake-sha")
        self.files[(path, branch)] = content
        return content

    def update(self, path: str, text: str, sha: str, message: str, branch: str) -> GitHubContent:
        raise NotImplementedError("update must never be called on immutable bindings")


class TestClaudeJulesOriginBindingStore(unittest.TestCase):
    def setUp(self) -> None:
        self.client = FakeGitHubContentsClient()
        self.branch = "jules-work/durable-lane"
        self.store = ClaudeJulesOriginBindingStore(self.client, self.branch)
        self.now = datetime(2026, 9, 30, 0, 30, tzinfo=timezone.utc)
        self.created_at = datetime(2026, 9, 30, 0, 0, tzinfo=timezone.utc).isoformat()
        self.expires_at = datetime(2026, 9, 30, 1, 0, tzinfo=timezone.utc).isoformat()

        self.valid_request = {
            "schema_version": 2,
            "profile": "JULES_CHAT_SEMIAUTO_V2",
            "command_id": "relay-dev-loop-123-compat-baseline",
            "target_repo": "kamiyusense/multi-ai-council-phase0",
            "target_branch": "feature/bounded-target",
            "work_branch": "jules-work/relay-dev-loop-123-compat-baseline",
            "expected_target_head": "2457a6b9b4aa3582fc7eda526c739e1ae54952dc",
            "expected_target_tree": "c9be2e0480b5e52204089410b3583a0b4b1537de",
            "allowed_paths": ["docs/CLAUDE_NIGHT_LOOP_DESIGN.md"],
            "prompt": "Test baseline",
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "retry": 0,
            "fallback": "disabled",
        }

        self.valid_claim = {
            "schema_version": 3,
            "loop_id": "loop-123",
            "command_id": "relay-dev-loop-123-compat-baseline",
            "target_branch": "feature/bounded-target",
            "work_branch": "jules-work/relay-dev-loop-123-compat-baseline",
            "expected_target_head": "2457a6b9b4aa3582fc7eda526c739e1ae54952dc",
            "expected_target_tree": "c9be2e0480b5e52204089410b3583a0b4b1537de",
            "retry": 0,
            "fallback": "disabled",
        }

        self.valid_record = build_binding_record(
            "origin-loop-456",
            1,
            "corr-789",
            1,
            self.valid_request,
            self.valid_claim,
        )

    def test_constructor_rejects_default_branch(self) -> None:
        with self.assertRaises(ValueError):
            ClaudeJulesOriginBindingStore(self.client, "main")
        with self.assertRaises(ValueError):
            ClaudeJulesOriginBindingStore(self.client, "master")
        with self.assertRaises(ValueError):
            ClaudeJulesOriginBindingStore(self.client, "")

    def test_invalid_command_id_rejected_before_access(self) -> None:
        with self.assertRaises(ValueError):
            _get_path("../invalid")
        with self.assertRaises(ValueError):
            _get_path("invalid/path")

    def test_persist_absent_creates_and_reads_back_successfully_returns_accepted(self) -> None:
        result = self.store.persist(self.valid_record, self.valid_request, self.valid_claim)
        self.assertEqual(result.status, "ACCEPTED")
        self.assertEqual(self.client.create_calls, 1)
        self.assertIsNotNone(result.record)
        self.assertEqual(result.record["command_id"], self.valid_request["command_id"])

    def test_persist_existing_identical_returns_recovered_no_create(self) -> None:
        self.store.persist(self.valid_record, self.valid_request, self.valid_claim)
        self.assertEqual(self.client.create_calls, 1)

        result = self.store.persist(self.valid_record, self.valid_request, self.valid_claim)
        self.assertEqual(result.status, "RECOVERED")
        self.assertEqual(self.client.create_calls, 1)  # No new create

    def test_persist_existing_different_valid_returns_blocked_no_create(self) -> None:
        self.store.persist(self.valid_record, self.valid_request, self.valid_claim)

        different_record = copy.deepcopy(self.valid_record)
        different_record["origin_round"] = 2
        # need to recompute sha to make it valid but different
        from automation.command_bus.claude_jules_origin_binding import compute_binding_sha256, validate_binding_record
        different_record["binding_sha256"] = compute_binding_sha256(different_record)
        different_record = validate_binding_record(different_record)

        result = self.store.persist(different_record, self.valid_request, self.valid_claim)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(self.client.create_calls, 1)

    def test_persist_existing_malformed_returns_unknown_no_create(self) -> None:
        path = _get_path(self.valid_request["command_id"])
        self.client.files[(path, self.branch)] = GitHubContent(path, "not-json", "sha")

        result = self.store.persist(self.valid_record, self.valid_request, self.valid_claim)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(self.client.create_calls, 0)

    def test_persist_existing_mismatched_cross_binding_returns_unknown(self) -> None:
        # Create a valid record but save it for this path
        path = _get_path(self.valid_request["command_id"])
        # alter a cross binding field in the existing file so it fails verify
        bad_existing = copy.deepcopy(self.valid_record)
        bad_existing["target_branch"] = "wrong-branch"
        from automation.command_bus.claude_jules_origin_binding import compute_binding_sha256, validate_binding_record
        bad_existing["binding_sha256"] = compute_binding_sha256(bad_existing)
        bad_existing = validate_binding_record(bad_existing)

        self.client.files[(path, self.branch)] = GitHubContent(
            path, json.dumps(bad_existing), "sha"
        )

        result = self.store.persist(self.valid_record, self.valid_request, self.valid_claim)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(self.client.create_calls, 0)

    def test_persist_create_raises_but_stores_returns_accepted(self) -> None:
        self.client.create_should_raise = True
        self.client.create_but_store = True
        result = self.store.persist(self.valid_record, self.valid_request, self.valid_claim)
        self.assertEqual(result.status, "ACCEPTED")
        self.assertEqual(self.client.create_calls, 1)

    def test_persist_create_raises_no_store_returns_unknown(self) -> None:
        self.client.create_should_raise = True
        self.client.create_but_store = False
        result = self.store.persist(self.valid_record, self.valid_request, self.valid_claim)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(self.client.create_calls, 1)

    def test_persist_create_success_but_readback_differs_returns_unknown(self) -> None:
        # To simulate a mutation during store, we subclass
        class TamperingClient(FakeGitHubContentsClient):
            def create(self, path: str, text: str, message: str, branch: str) -> GitHubContent:
                # Store tampered text
                tampered = json.loads(text)
                tampered["origin_round"] = 999
                # don't fix sha, just store it
                content = GitHubContent(path, json.dumps(tampered), "fake-sha")
                self.files[(path, branch)] = content
                self.create_calls += 1
                return content

        tampering_store = ClaudeJulesOriginBindingStore(TamperingClient(), self.branch)
        result = tampering_store.persist(self.valid_record, self.valid_request, self.valid_claim)
        self.assertEqual(result.status, "UNKNOWN")

    def test_persist_invalid_input_record_returns_unknown(self) -> None:
        bad_record = copy.deepcopy(self.valid_record)
        bad_record["origin_round"] = -1
        result = self.store.persist(bad_record, self.valid_request, self.valid_claim)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(self.client.create_calls, 0)

    def test_persist_mismatched_request_claim_returns_unknown(self) -> None:
        bad_claim = copy.deepcopy(self.valid_claim)
        bad_claim["target_branch"] = "wrong"
        result = self.store.persist(self.valid_record, self.valid_request, bad_claim)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(self.client.create_calls, 0)

    def test_read_missing_returns_unknown(self) -> None:
        result = self.store.read(self.valid_request["command_id"], self.valid_request, self.valid_claim)
        self.assertEqual(result.status, "UNKNOWN")

    def test_read_valid_returns_read(self) -> None:
        self.store.persist(self.valid_record, self.valid_request, self.valid_claim)
        result = self.store.read(self.valid_request["command_id"], self.valid_request, self.valid_claim)
        self.assertEqual(result.status, "READ")
        self.assertIsNotNone(result.record)
        self.assertEqual(result.record["command_id"], self.valid_request["command_id"])

    def test_read_command_id_mismatch_returns_unknown_fail_closed(self) -> None:
        self.store.persist(self.valid_record, self.valid_request, self.valid_claim)

        # Read with a different command_id than what is in the record.
        # This requires tweaking the request/claim and bypassing the path validation slightly,
        # but path validation catches command_id mismatch.
        # Actually, if we ask for command_id="different-command", it won't exist.
        # Let's say we ask for valid command_id but the file contains a different one.

        other_request = copy.deepcopy(self.valid_request)
        other_request["command_id"] = "relay-dev-loop-999-other"
        other_claim = copy.deepcopy(self.valid_claim)
        other_claim["command_id"] = "relay-dev-loop-999-other"

        # Manually seed a mismatched record at the right path
        path = _get_path(self.valid_request["command_id"])

        other_record = build_binding_record(
            "origin-loop-456", 1, "corr-789", 1, other_request, other_claim
        )
        self.client.files[(path, self.branch)] = GitHubContent(
            path, json.dumps(other_record), "sha"
        )

        # now read using the original command_id, request, and claim
        # it will read other_record from the file, but when verified against self.valid_request, it should fail verify
        result = self.store.read(self.valid_request["command_id"], self.valid_request, self.valid_claim)
        self.assertEqual(result.status, "UNKNOWN")

    def test_read_invalid_cross_binding_returns_unknown(self) -> None:
        self.store.persist(self.valid_record, self.valid_request, self.valid_claim)
        bad_claim = copy.deepcopy(self.valid_claim)
        bad_claim["retry"] = 1
        result = self.store.read(self.valid_request["command_id"], self.valid_request, bad_claim)
        self.assertEqual(result.status, "UNKNOWN")
