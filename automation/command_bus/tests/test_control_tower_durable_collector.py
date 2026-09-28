from __future__ import annotations

import copy
import json
import unittest

from automation.command_bus.control_tower_durable_collector import (
    ControlTowerDurableCollector,
)
from automation.command_bus.github_backend import GitHubContent
from automation.command_bus.loop_owner_observation import provider_observation_path
from automation.command_bus.tests.test_loop_owner import (
    EVIDENCE,
    next_event,
    receipt_for,
    target_for,
)
from automation.command_bus.tests.test_loop_status_issue import state
from automation.command_bus.tests.test_loop_status_transition import inputs


class Client:
    def __init__(self, data):
        self.data = copy.deepcopy(data)
        self.get_calls = []
        self.list_calls = []
        self.mutate_after_first_get = {}

    def get(self, path, ref):
        self.get_calls.append((path, ref))
        value = self.data.get(path)
        if value is None:
            return None
        if path in self.mutate_after_first_get:
            count = sum(1 for p, _ in self.get_calls if p == path)
            current = copy.deepcopy(value)
            if count == 1:
                self.data[path] = copy.deepcopy(self.mutate_after_first_get[path])
            value = current
        return GitHubContent(path=path, text=json.dumps(value), sha="a" * 40)

    def list(self, prefix, ref):
        self.list_calls.append((prefix, ref))
        items = []
        for path, value in sorted(self.data.items()):
            if path.startswith(prefix):
                items.append(
                    GitHubContent(path=path, text=json.dumps(value), sha="b" * 40)
                )
        return items

    def create(self, *args, **kwargs):
        raise AssertionError("read-only collector must not create")

    def update(self, *args, **kwargs):
        raise AssertionError("read-only collector must not update")


class TargetReader:
    def __init__(self, target):
        self.target = copy.deepcopy(target)
        self.calls = []
        self.second_target = None

    def read_target(self, repository, pr_number):
        self.calls.append((repository, pr_number))
        if len(self.calls) > 1 and self.second_target is not None:
            return copy.deepcopy(self.second_target)
        return copy.deepcopy(self.target)


class Clock:
    def __init__(self, now):
        self.value = now
        self.calls = 0

    def now(self):
        self.calls += 1
        return self.value


def durable_data(values=None):
    values = copy.deepcopy(values or inputs())
    loop_id = values["state"]["loop_id"]
    data = {
        f"automation/command_bus/state/{loop_id}.json": values["state"],
        values["receipt_ref"]: values["receipt"],
    }
    for event in values["owner_events"]:
        data[
            f"automation/command_bus/loop_owner_events/{loop_id}/{event['generation']:06d}.json"
        ] = event
    for ref, document in values["evidence_readbacks"].items():
        data[ref] = document
    if values["provider_observation_ref"] is not None:
        data[values["provider_observation_ref"]] = values["provider_observation"]
    return data


def fresh_target(values=None):
    values = values or inputs()
    return {
        **values["target"],
        "state": "open",
        "merged": False,
    }


def collector(values=None, *, client=None, target=None):
    values = values or inputs()
    client = client or Client(durable_data(values))
    reader = TargetReader(target or fresh_target(values))
    clock = Clock(values["now"])
    return (
        ControlTowerDurableCollector(
            client,
            ref="runtime/data",
            target_reader=reader,
            clock=clock,
        ),
        client,
        reader,
        clock,
    )


def registry(loop_id="loop-015", *, identity_state="DURABLE", enabled=True):
    return {
        "schema_version": 1,
        "loops": [
            {
                "loop_id": loop_id,
                "display_name": "Loop 015",
                "mode": "SEMI_AUTO",
                "controller_kind": "CHATGPT",
                "worker_kind": "JULES",
                "display_order": 10,
                "enabled": enabled,
                "safe_detail_ref": "issue:33",
                "identity_state": identity_state,
            }
        ],
    }


class ControlTowerDurableCollectorTests(unittest.TestCase):
    def test_valid_active_transition_is_collected_read_only(self):
        c, client, reader, clock = collector()
        result = c.collect_transition("loop-015")
        self.assertEqual(result.status, "COLLECTED", result)
        self.assertEqual(result.transition.status, "VALID")
        self.assertEqual(result.transition.projection.display_state, "SEMI_AUTO")
        self.assertEqual(result.fetch_plan["loop_id"], "loop-015")
        self.assertEqual(len(reader.calls), 2)
        self.assertEqual(clock.calls, 1)
        self.assertTrue(client.get_calls)
        self.assertTrue(client.list_calls)

    def test_repository_style_placeholder_registry_is_not_wired_without_reads(self):
        c, client, reader, clock = collector()
        result = c.collect_registry(
            registry(identity_state="PLACEHOLDER")
        )
        self.assertEqual(result.status, "NOT_WIRED")
        self.assertIn("not DURABLE", result.reason)
        self.assertEqual(result.transitions, {})
        self.assertEqual(client.get_calls, [])
        self.assertEqual(client.list_calls, [])
        self.assertEqual(reader.calls, [])
        self.assertEqual(clock.calls, 0)

    def test_durable_registry_collects_transition_inventory(self):
        c, _, _, _ = collector()
        result = c.collect_registry(registry())
        self.assertEqual(result.status, "READY", result)
        self.assertEqual(set(result.transitions), {"loop-015"})
        self.assertEqual(result.transitions["loop-015"].status, "VALID")
        self.assertEqual(result.collections["loop-015"].status, "COLLECTED")

    def test_zero_enabled_registry_is_not_wired(self):
        c, client, reader, _ = collector()
        result = c.collect_registry(registry(enabled=False))
        self.assertEqual(result.status, "NOT_WIRED")
        self.assertEqual(client.get_calls, [])
        self.assertEqual(reader.calls, [])

    def test_missing_exact_durable_record_is_unknown(self):
        data = durable_data()
        values = inputs()
        data.pop(values["receipt_ref"])
        c, _, _, _ = collector(client=Client(data))
        result = c.collect_transition("loop-015")
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIn("missing", result.reason)

    def test_state_change_during_collection_is_unknown(self):
        data = durable_data()
        path = "automation/command_bus/state/loop-015.json"
        changed = copy.deepcopy(data[path])
        changed["round"] = changed["round"] + 1
        client = Client(data)
        client.mutate_after_first_get[path] = changed
        c, _, _, _ = collector(client=client)
        result = c.collect_transition("loop-015")
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIn("state changed", result.reason)

    def test_receipt_change_during_collection_is_unknown(self):
        values = inputs()
        data = durable_data(values)
        changed = copy.deepcopy(data[values["receipt_ref"]])
        changed["state"] = "BLOCKED"
        client = Client(data)
        client.mutate_after_first_get[values["receipt_ref"]] = changed
        c, _, _, _ = collector(values, client=client)
        result = c.collect_transition("loop-015")
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIn("receipt changed", result.reason)

    def test_evidence_change_during_collection_is_unknown(self):
        values = inputs()
        data = durable_data(values)
        changed = {"schema_version": 1, "kind": "changed"}
        client = Client(data)
        client.mutate_after_first_get[EVIDENCE] = changed
        c, _, _, _ = collector(values, client=client)
        result = c.collect_transition("loop-015")
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIn("evidence changed", result.reason)

    def test_provider_observation_change_during_collection_is_unknown(self):
        values = inputs()
        data = durable_data(values)
        ref = values["provider_observation_ref"]
        changed = copy.deepcopy(data[ref])
        changed["state"] = "CHANGED"
        client = Client(data)
        client.mutate_after_first_get[ref] = changed
        c, _, _, _ = collector(values, client=client)
        result = c.collect_transition("loop-015")
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIn("provider observation changed", result.reason)

    def test_target_change_during_collection_is_unknown(self):
        c, _, reader, _ = collector()
        reader.second_target = {
            **fresh_target(),
            "head": "b" * 40,
        }
        result = c.collect_transition("loop-015")
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIn("target changed", result.reason)

    def test_active_owner_requires_open_non_merged_target(self):
        closed = {
            **fresh_target(),
            "state": "closed",
            "merged": False,
        }
        c, _, _, _ = collector(target=closed)
        result = c.collect_transition("loop-015")
        self.assertEqual(result.status, "UNKNOWN")
        self.assertIn("OPEN non-merged", result.reason)

    def test_fresh_target_head_movement_projects_blocked_when_stable(self):
        moved = {
            **fresh_target(),
            "head": "b" * 40,
        }
        c, _, reader, _ = collector(target=moved)
        reader.second_target = copy.deepcopy(moved)
        result = c.collect_transition("loop-015")
        self.assertEqual(result.status, "COLLECTED", result)
        self.assertEqual(result.transition.status, "BLOCKED")
        self.assertEqual(result.transition.projection.display_state, "BLOCKED")

    def test_terminal_transition_does_not_require_provider_observation(self):
        values = inputs()
        first = values["owner_events"][0]
        terminal = next_event(first, event_type="TERMINAL")
        receipt = receipt_for(terminal)
        target = target_for(terminal)
        evidence_ref = terminal["evidence_refs"][0]
        values.update(
            owner_events=[first, terminal],
            state=state(
                state="COMPLETE",
                last_command_id=terminal["command_id"],
                last_receipt_id=terminal["source_receipt_id"],
                expected_target=target,
            ),
            receipt_ref=terminal["source_receipt_ref"],
            receipt=receipt,
            target=target,
            evidence_readbacks={
                evidence_ref: {"schema_version": 1, "kind": "terminal-evidence"}
            },
            provider_observation_ref=None,
            provider_observation=None,
        )
        data = durable_data(values)
        terminal_target = {**target, "state": "closed", "merged": True}
        c, _, reader, _ = collector(values, client=Client(data), target=terminal_target)
        reader.second_target = copy.deepcopy(terminal_target)
        result = c.collect_transition("loop-015")
        self.assertEqual(result.status, "COLLECTED", result)
        self.assertEqual(result.transition.status, "TERMINAL")
        self.assertEqual(result.transition.projection.display_state, "IDLE")

    def test_unsafe_loop_id_blocks_before_reads(self):
        c, client, reader, _ = collector()
        result = c.collect_transition("../bad")
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(client.get_calls, [])
        self.assertEqual(reader.calls, [])


if __name__ == "__main__":
    unittest.main()
