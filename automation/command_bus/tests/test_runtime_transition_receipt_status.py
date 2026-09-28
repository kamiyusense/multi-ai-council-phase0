from __future__ import annotations

import copy
import json
import unittest

from automation.command_bus.github_backend import GitHubContent
from automation.command_bus.runtime_transition_jules import (
    JulesTerminalOwnerReceiptAdapter,
    prepare_jules_terminal_owner_receipt,
)
from automation.command_bus.runtime_transition_receipt import (
    CanonicalOwnerReceiptGitHubBackend,
    build_terminal_owner_receipt,
)
from automation.command_bus.runtime_transition_coordinator import StatusRefreshPlan
from automation.command_bus.runtime_transition_status import (
    PrepareOnlyStatusBoundary,
    prepare_status_workflow_call,
)
from automation.command_bus.tests.test_loop_owner import first_event, next_event


class Client:
    def __init__(self):
        self.data = {}
        self.creates = 0
        self.fail_after_write = False

    def get(self, path, ref):
        return self.data.get(path)

    def create(self, path, text, message, branch):
        self.creates += 1
        if path in self.data:
            raise RuntimeError("conflict")
        self.data[path] = GitHubContent(path, text, f"sha-{self.creates}")
        if self.fail_after_write:
            raise OSError("ambiguous create")
        return self.data[path]


def terminal_event():
    first = first_event()
    event = next_event(first, event_type="TERMINAL")
    event["correlation_id"] = first["correlation_id"]
    return first, event


def jules_receipt(first):
    return {
        "schema_version": 1,
        "receipt_id": "loop-015/000001",
        "command_id": first["command_id"],
        "loop_id": first["loop_id"],
        "round": 1,
        "correlation_id": first["correlation_id"],
        "state": "DONE",
        "executed_once": True,
        "retry_count": 0,
        "fallback_used": False,
        "evidence_refs": ["workflow-run:1", "jules-session:1"],
    }


class CanonicalOwnerReceiptTests(unittest.TestCase):
    def test_jules_terminal_receipt_derives_distinct_owner_receipt(self):
        first, event = terminal_event()
        receipt = prepare_jules_terminal_owner_receipt(event, jules_receipt=jules_receipt(first))
        self.assertEqual(receipt["receipt_id"], event["source_receipt_id"])
        self.assertEqual(receipt["command_id"], event["command_id"])
        self.assertEqual(receipt["evidence_refs"], event["evidence_refs"])
        self.assertEqual(receipt["provider_kind"], "JULES")
        self.assertEqual(receipt["provider_source_receipt_id"], "loop-015/000001")
        self.assertEqual(
            receipt["provider_source_receipt_ref"],
            "automation/command_bus/receipts/loop-015/000001.json",
        )

    def test_active_event_collision_and_mismatch_are_rejected(self):
        first = first_event()
        with self.assertRaises(ValueError):
            build_terminal_owner_receipt(
                first,
                provider_kind="JULES",
                provider_receipt=jules_receipt(first),
                provider_receipt_ref="automation/command_bus/receipts/loop-015/000099.json",
            )

        _, event = terminal_event()
        collision = copy.deepcopy(event)
        collision["source_receipt_ref"] = "automation/command_bus/receipts/loop-015/000001.json"
        with self.assertRaises(ValueError):
            prepare_jules_terminal_owner_receipt(collision, jules_receipt=jules_receipt(first))

        bad = jules_receipt(first)
        bad["correlation_id"] = "other-correlation"
        with self.assertRaises(ValueError):
            prepare_jules_terminal_owner_receipt(event, jules_receipt=bad)

    def test_create_only_owner_receipt_recovers_and_rejects_conflict(self):
        first, event = terminal_event()
        receipt = prepare_jules_terminal_owner_receipt(event, jules_receipt=jules_receipt(first))
        client = Client()
        backend = CanonicalOwnerReceiptGitHubBackend(client, branch="runtime-ledger")
        self.assertEqual(backend.write(event, receipt).status, "ACCEPTED")
        self.assertEqual(backend.write(event, copy.deepcopy(receipt)).status, "RECOVERED")
        self.assertEqual(client.creates, 1)
        changed = copy.deepcopy(receipt)
        changed["provider_source_command_id"] = "other-command"
        self.assertEqual(backend.write(event, changed).status, "BLOCKED")
        self.assertEqual(client.creates, 1)

    def test_ambiguous_owner_receipt_create_is_resolved_by_readback_without_retry(self):
        first, event = terminal_event()
        receipt = prepare_jules_terminal_owner_receipt(event, jules_receipt=jules_receipt(first))
        client = Client()
        client.fail_after_write = True
        backend = CanonicalOwnerReceiptGitHubBackend(client, branch="runtime-ledger")
        self.assertEqual(backend.write(event, receipt).status, "ACCEPTED")
        self.assertEqual(client.creates, 1)

    def test_jules_adapter_fresh_reads_durable_receipt_then_writes_canonical_receipt(self):
        first, event = terminal_event()
        client = Client()
        source = "automation/command_bus/receipts/loop-015/000001.json"
        client.data[source] = GitHubContent(
            source,
            json.dumps(jules_receipt(first), sort_keys=True, separators=(",", ":")),
            "jules-source",
        )
        adapter = JulesTerminalOwnerReceiptAdapter(client, branch="runtime-ledger")
        result = adapter.publish(event, jules_round=1)
        self.assertEqual(result.status, "ACCEPTED", result)
        self.assertEqual(client.creates, 1)
        self.assertIn(event["source_receipt_ref"], client.data)

        again = adapter.publish(event, jules_round=1)
        self.assertEqual(again.status, "RECOVERED")
        self.assertEqual(client.creates, 1)

    def test_jules_adapter_missing_source_fails_closed_without_write(self):
        _, event = terminal_event()
        client = Client()
        adapter = JulesTerminalOwnerReceiptAdapter(client, branch="runtime-ledger")
        result = adapter.publish(event, jules_round=1)
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(client.creates, 0)


class StatusPrepareOnlyTests(unittest.TestCase):
    def plan(self, **changes):
        values = {
            "loop_id": "loop-015",
            "state_ref": "runtime-ledger",
            "event_id": "receipt-owner-2",
            "generation": 2,
            "display_state": "IDLE",
            "transition_status": "TERMINAL",
        }
        values.update(changes)
        return StatusRefreshPlan(**values)

    def test_plan_uses_only_deployed_workflow_inputs(self):
        prepared = prepare_status_workflow_call(self.plan())
        self.assertEqual(prepared.workflow, ".github/workflows/loop-status-signal.yml")
        self.assertEqual(prepared.code_ref, "main")
        self.assertEqual(prepared.inputs, {"loop_id": "loop-015", "state_ref": "runtime-ledger"})
        self.assertNotIn("owner", prepared.inputs)
        self.assertNotIn("provider_state", prepared.inputs)
        self.assertNotIn("event_id", prepared.inputs)

    def test_default_data_ref_and_invalid_status_are_rejected(self):
        with self.assertRaises(ValueError):
            prepare_status_workflow_call(self.plan(state_ref="main"))
        with self.assertRaises(ValueError):
            prepare_status_workflow_call(self.plan(display_state="PURPLE"))
        with self.assertRaises(ValueError):
            prepare_status_workflow_call(self.plan(transition_status="UNKNOWN"))

    def test_prepare_boundary_is_deterministic_and_dedupes_exact_plan(self):
        boundary = PrepareOnlyStatusBoundary()
        plan = self.plan()
        boundary.prepare(plan)
        boundary.prepare(plan)
        self.assertEqual(len(boundary.prepared), 1)
        boundary.prepare(self.plan(event_id="receipt-owner-3", generation=3))
        self.assertEqual(len(boundary.prepared), 2)


if __name__ == "__main__":
    unittest.main()
