from __future__ import annotations

import json
import unittest

from automation.command_bus.executor_backend import ExecutorContent
from automation.command_bus.symphony_attempt_store import (
    GitHubAutonomousAttemptStore,
    attempt_recovery_action,
    make_attempt_id,
)


class FakeAttemptContents:
    def __init__(self):
        self.files = {}
        self.counter = 0
        self.create_calls = 0
        self.raise_after_create_path = None
        self.fail_get_paths = set()

    def get(self, path, ref):
        if path in self.fail_get_paths and path in self.files:
            raise RuntimeError("readback unavailable")
        return self.files.get(path)

    def list(self, prefix, ref):
        return sorted(
            (item for path, item in self.files.items() if path.startswith(prefix)),
            key=lambda item: item.path,
        )

    def create(self, path, text, message, branch):
        self.create_calls += 1
        if path in self.files:
            raise ValueError("already exists")
        self.counter += 1
        value = ExecutorContent(path, text, f"sha-{self.counter}")
        self.files[path] = value
        if self.raise_after_create_path == path:
            self.raise_after_create_path = None
            raise RuntimeError("ambiguous create")
        return value

    def update(self, path, text, sha, message, branch):
        raise AssertionError("attempt store must remain create-only")


def store(client=None):
    client = client or FakeAttemptContents()
    return client, GitHubAutonomousAttemptStore(
        client, write_branch="feature/controller-records",
    )


def intent(s, *, task_id="task::one", attempt_number=1, head="a" * 40):
    return s.append_intent(
        campaign_id="campaign-1",
        task_id=task_id,
        generation=3,
        attempt_number=attempt_number,
        expected_target_head=head,
        expected_target_tree="b" * 40,
        runner_generation=2,
        scope={"task": task_id, "allowed_paths": ["src/"]},
    )


class SymphonyAttemptStoreTests(unittest.TestCase):
    def test_deterministic_path_safe_attempt_identity_handles_corrective_task_ids(self):
        value = make_attempt_id(
            campaign_id="campaign-1",
            task_id="A::corrective::2",
            generation=4,
            attempt_number=3,
            expected_target_head="a" * 40,
        )
        self.assertRegex(value, r"^attempt-[0-9a-f]{32}$")
        self.assertEqual(
            value,
            make_attempt_id(
                campaign_id="campaign-1",
                task_id="A::corrective::2",
                generation=4,
                attempt_number=3,
                expected_target_head="a" * 40,
            ),
        )

    def test_intent_started_terminal_restore_full_lineage(self):
        _, s = store()
        created = intent(s)
        self.assertEqual(created.status, "ACCEPTED")
        started = s.append_started(
            campaign_id="campaign-1",
            attempt_id=created.attempt_id,
            provider_kind="CODEX_APP_SERVER",
            provider_attempt_ref="session-1",
            observation_source="STATIC_SIMULATION",
            thread_id="thread-1",
            turn_id="turn-1",
            workspace_fingerprint="workspace-abc",
        )
        self.assertEqual(started.status, "ACCEPTED")
        terminal = s.append_terminal(
            campaign_id="campaign-1",
            attempt_id=created.attempt_id,
            result_id="result-1",
            outcome="DONE",
            model_started=True,
            evidence_refs=["evidence/result-1.json"],
        )
        self.assertEqual(terminal.status, "ACCEPTED")
        restored = s.restore("campaign-1", created.attempt_id)
        self.assertEqual(restored.state, "TERMINAL")
        self.assertEqual(restored.terminal["result_id"], "result-1")
        self.assertEqual(
            attempt_recovery_action(
                restored,
                old_attempt_stopped_or_fenced=False,
                independent_safe_work=False,
            ),
            "APPLY_TERMINAL_RESULT",
        )

    def test_duplicate_intent_started_and_terminal_never_create_again(self):
        client, s = store()
        created = intent(s)
        calls = client.create_calls
        duplicate = intent(s)
        self.assertEqual(duplicate.status, "CONFLICT")
        self.assertEqual(client.create_calls, calls)

        self.assertEqual(
            s.append_started(
                campaign_id="campaign-1",
                attempt_id=created.attempt_id,
                provider_kind="CODEX_APP_SERVER",
                provider_attempt_ref="session-1",
                observation_source="STATIC_SIMULATION",
            ).status,
            "ACCEPTED",
        )
        calls = client.create_calls
        self.assertEqual(
            s.append_started(
                campaign_id="campaign-1",
                attempt_id=created.attempt_id,
                provider_kind="CODEX_APP_SERVER",
                provider_attempt_ref="session-1",
                observation_source="STATIC_SIMULATION",
            ).status,
            "CONFLICT",
        )
        self.assertEqual(client.create_calls, calls)

        self.assertEqual(
            s.append_terminal(
                campaign_id="campaign-1",
                attempt_id=created.attempt_id,
                result_id="result-1",
                outcome="DONE",
                model_started=True,
            ).status,
            "ACCEPTED",
        )
        calls = client.create_calls
        self.assertEqual(
            s.append_terminal(
                campaign_id="campaign-1",
                attempt_id=created.attempt_id,
                result_id="result-1",
                outcome="DONE",
                model_started=True,
            ).status,
            "CONFLICT",
        )
        self.assertEqual(client.create_calls, calls)

    def test_ambiguous_started_write_readback_resolves_without_resend(self):
        client, s = store()
        created = intent(s)
        path = f"symphony_attempts/campaign-1/{created.attempt_id}/started.json"
        client.raise_after_create_path = path
        result = s.append_started(
            campaign_id="campaign-1",
            attempt_id=created.attempt_id,
            provider_kind="CODEX_APP_SERVER",
            provider_attempt_ref="session-1",
            observation_source="STATIC_SIMULATION",
        )
        self.assertEqual(result.status, "ACCEPTED")
        self.assertEqual(client.create_calls, 2)
        self.assertEqual(s.restore("campaign-1", created.attempt_id).state, "STARTED_UNRESOLVED")

    def test_unverifiable_ambiguous_started_write_is_not_retried(self):
        client, s = store()
        created = intent(s)
        path = f"symphony_attempts/campaign-1/{created.attempt_id}/started.json"
        client.raise_after_create_path = path
        client.fail_get_paths.add(path)
        calls_before = client.create_calls
        result = s.append_started(
            campaign_id="campaign-1",
            attempt_id=created.attempt_id,
            provider_kind="CODEX_APP_SERVER",
            provider_attempt_ref="session-1",
            observation_source="STATIC_SIMULATION",
        )
        self.assertEqual(result.status, "AMBIGUOUS")
        self.assertEqual(client.create_calls, calls_before + 1)
        client.fail_get_paths.clear()
        self.assertEqual(s.restore("campaign-1", created.attempt_id).state, "STARTED_UNRESOLVED")

    def test_started_unresolved_never_reclaims_same_attempt_blindly(self):
        _, s = store()
        created = intent(s)
        s.append_started(
            campaign_id="campaign-1",
            attempt_id=created.attempt_id,
            provider_kind="CODEX_APP_SERVER",
            provider_attempt_ref="session-1",
            observation_source="STATIC_SIMULATION",
        )
        snapshot = s.restore("campaign-1", created.attempt_id)
        self.assertEqual(snapshot.state, "STARTED_UNRESOLVED")
        self.assertEqual(
            attempt_recovery_action(
                snapshot,
                old_attempt_stopped_or_fenced=True,
                independent_safe_work=True,
            ),
            "ISOLATE_TASK_CONTINUE",
        )
        self.assertEqual(
            attempt_recovery_action(
                snapshot,
                old_attempt_stopped_or_fenced=True,
                independent_safe_work=False,
            ),
            "STOP_UNRESOLVED_ATTEMPT",
        )

    def test_claimed_unstarted_requires_explicit_fence_before_reclaim(self):
        _, s = store()
        created = intent(s)
        snapshot = s.restore("campaign-1", created.attempt_id)
        self.assertEqual(snapshot.state, "CLAIMED_UNSTARTED")
        self.assertEqual(
            attempt_recovery_action(
                snapshot,
                old_attempt_stopped_or_fenced=False,
                independent_safe_work=False,
            ),
            "STOP_UNFENCED_ATTEMPT",
        )
        self.assertEqual(
            attempt_recovery_action(
                snapshot,
                old_attempt_stopped_or_fenced=True,
                independent_safe_work=False,
            ),
            "RECLAIM_ALLOWED",
        )

    def test_terminal_model_started_true_requires_started_record(self):
        _, s = store()
        created = intent(s)
        result = s.append_terminal(
            campaign_id="campaign-1",
            attempt_id=created.attempt_id,
            result_id="unknown-1",
            outcome="UNKNOWN",
            model_started=True,
        )
        self.assertEqual(result.status, "CONFLICT")
        self.assertEqual(s.restore("campaign-1", created.attempt_id).state, "CLAIMED_UNSTARTED")

    def test_tampered_started_predecessor_is_rejected_on_restore(self):
        client, s = store()
        created = intent(s)
        s.append_started(
            campaign_id="campaign-1",
            attempt_id=created.attempt_id,
            provider_kind="CODEX_APP_SERVER",
            provider_attempt_ref="session-1",
            observation_source="STATIC_SIMULATION",
        )
        path = f"symphony_attempts/campaign-1/{created.attempt_id}/started.json"
        record = json.loads(client.files[path].text)
        record["intent_digest"] = "0" * 64
        client.files[path] = ExecutorContent(
            path,
            json.dumps(record, sort_keys=True, separators=(",", ":")),
            client.files[path].sha,
        )
        with self.assertRaisesRegex(RuntimeError, "predecessor"):
            s.restore("campaign-1", created.attempt_id)

    def test_list_campaign_rejects_orphan_record_without_intent(self):
        client, s = store()
        orphan = "attempt-" + "1" * 32
        path = f"symphony_attempts/campaign-1/{orphan}/started.json"
        client.files[path] = ExecutorContent(path, "{}", "sha-orphan")
        with self.assertRaisesRegex(RuntimeError, "record set has no intent|protocol|attempt"):
            s.list_campaign("campaign-1")

    def test_default_branch_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "non-default"):
            GitHubAutonomousAttemptStore(FakeAttemptContents(), write_branch="main")


if __name__ == "__main__":
    unittest.main()
