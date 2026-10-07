from __future__ import annotations

import copy
import json
import unittest

from automation.command_bus.github_backend import GitHubContent
from automation.command_bus.loop_owner_backend import LoopOwnerGitHubBackend, owner_event_path
from automation.command_bus.tests.test_loop_owner import next_event, records


class FakeClient:
    def __init__(self):
        self.data: dict[str, GitHubContent] = {}
        self.creates = 0
        self.after_create = None

    def get(self, path: str, ref: str):
        return self.data.get(path)

    def list(self, prefix: str, ref: str):
        return [self.data[path] for path in sorted(self.data) if path.startswith(prefix)]

    def create(self, path: str, text: str, message: str, branch: str):
        self.creates += 1
        if path in self.data:
            raise RuntimeError("create-only conflict")
        content = GitHubContent(path=path, text=text, sha=f"sha-{self.creates}")
        self.data[path] = content
        if self.after_create is not None:
            self.after_create(self, path)
        return content

    def update(self, path: str, text: str, sha: str, message: str, branch: str):
        raise AssertionError("owner ledger must never update an existing event")


def event1():
    return copy.deepcopy(records()[0][0])



class LoopOwnerBackendTests(unittest.TestCase):
    def setUp(self):
        self.client = FakeClient()
        self.backend = LoopOwnerGitHubBackend(self.client, branch="runtime-ledger")

    def test_path_is_canonical_and_rejects_unsafe_loop(self):
        self.assertEqual(
            owner_event_path("loop-015", 1),
            "automation/command_bus/loop_owner_events/loop-015/000001.json",
        )
        with self.assertRaises(ValueError):
            owner_event_path("../bad", 1)

    def test_first_append_is_create_only_and_read_back(self):
        event = event1()
        result = self.backend.append(event)
        self.assertEqual((result.status, result.chain_length), ("ACCEPTED", 1))
        self.assertEqual(self.client.creates, 1)
        path = owner_event_path(event["loop_id"], 1)
        self.assertEqual(json.loads(self.client.data[path].text), event)
        read = self.backend.read_chain(event["loop_id"])
        self.assertEqual((read.status, read.chain_length), ("READ", 1))

    def test_stale_generation_is_blocked_without_write(self):
        event = event1()
        event["generation"] = 2
        event["fencing_token"] = 2
        event["previous_generation"] = 1
        result = self.backend.append(event)
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(self.client.creates, 0)

    def test_lost_create_response_recovers_from_exact_generation_and_chain(self):
        def lost_response(client, path):
            raise OSError("response lost after immutable create")
        self.client.after_create = lost_response
        result = self.backend.append(event1())
        self.assertEqual((result.status, result.chain_length), ("ACCEPTED", 1))
        self.assertEqual(self.client.creates, 1)

    def test_failed_create_without_readback_is_unknown_without_resend(self):
        def failed_create(*args):
            self.client.creates += 1
            raise OSError("request outcome unavailable")
        self.client.create = failed_create
        result = self.backend.append(event1())
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(self.client.creates, 1)

    def test_renew_and_handoff_append_only(self):
        first = event1()
        self.assertEqual(self.backend.append(first).status, "ACCEPTED")
        renew = next_event(first)
        self.assertEqual(self.backend.append(renew).status, "ACCEPTED")
        handoff = next_event(renew, event_type="HANDOFF", owner_role="AUTO", holder_id="controller-2")
        self.assertEqual(self.backend.append(handoff).status, "ACCEPTED")
        self.assertEqual(self.backend.read_chain(first["loop_id"]).chain_length, 3)

    def test_release_closes_chain_and_reuse_is_not_written(self):
        first = event1()
        self.assertEqual(self.backend.append(first).status, "ACCEPTED")
        released = next_event(first, event_type="RELEASE")
        self.assertEqual(self.backend.append(released).status, "ACCEPTED")
        before = self.client.creates
        attempted = next_event(released)
        self.assertEqual(self.backend.append(attempted).status, "UNKNOWN")
        self.assertEqual(self.client.creates, before)

    def test_existing_malformed_ledger_fails_closed(self):
        first = event1()
        path = owner_event_path(first["loop_id"], 1)
        self.client.data[path] = GitHubContent(path=path, text="{}", sha="bad")
        result = self.backend.append(first)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(self.client.creates, 0)

    def test_noncanonical_or_unexpected_filename_fails_closed(self):
        first = event1()
        bad_path = "automation/command_bus/loop_owner_events/loop-015/not-a-generation.json"
        self.client.data[bad_path] = GitHubContent(path=bad_path, text=json.dumps(first), sha="bad")
        self.assertEqual(self.backend.read_chain(first["loop_id"]).status, "UNKNOWN")

    def test_concurrent_chain_change_after_create_is_unknown_no_retry(self):
        first = event1()
        second = next_event(first)

        def inject(client, created_path):
            path = owner_event_path(first["loop_id"], 2)
            client.data[path] = GitHubContent(
                path=path,
                text=json.dumps(second, sort_keys=True, separators=(",", ":")),
                sha="concurrent",
            )

        self.client.after_create = inject
        result = self.backend.append(first)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(self.client.creates, 1)
        self.assertEqual(result.chain_length, 2)


if __name__ == "__main__":
    unittest.main()
