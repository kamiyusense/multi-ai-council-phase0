from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import unittest

from automation.command_bus.event_processor import EventProcessor
from automation.command_bus.late_receipt import (
    SuccessorGateState,
    durable_run_completion_state,
    receipt_replay_disposition,
    reconcile_late_terminal_receipt,
    successor_issue_gate,
    validate_late_receipt_evidence,
)
from automation.command_bus.ledger import InMemoryLedger
from automation.command_bus.validator import validate_state


NOW = datetime(2026, 9, 25, 0, 0, tzinfo=timezone.utc)
REPO = "kamiyusense/multi-ai-council-phase0"
HEAD = "a" * 40
TREE = "b" * 40


def command(name="old", generation=1, **changes):
    value = {
        "schema_version": 1,
        "command_id": f"{name}-000001",
        "loop_id": name,
        "round": 1,
        "correlation_id": f"{name}-round-1",
        "generation": generation,
        "target": "work",
        "action": "JULES_SPLASH_SETTLE_DIAGNOSTIC",
        "expected_repo": REPO,
        "expected_pr": 4,
        "expected_target_head": HEAD,
        "expected_target_tree": TREE,
        "requires_live_model": False,
        "requires_github_write": True,
        "retry": 0,
        "fallback": "disabled",
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
    }
    value.update(changes)
    return value


def state(cmd=None, status="UNKNOWN", **changes):
    cmd = cmd or command()
    value = {
        "schema_version": 1,
        "loop_id": cmd["loop_id"],
        "state": status,
        "round": 0,
        "max_rounds": 6,
        "expires_at": (NOW + timedelta(hours=1)).isoformat(),
        "stop_requested": status != "RUNNING",
        "last_command_id": cmd["command_id"],
        "last_receipt_id": None,
        "expected_target": "work",
        "retry_policy": 0,
    }
    value.update(changes)
    return value


def receipt(cmd=None, **changes):
    cmd = cmd or command()
    value = {
        "schema_version": 1,
        "receipt_id": f"{cmd['loop_id']}/000001",
        "command_id": cmd["command_id"],
        "loop_id": cmd["loop_id"],
        "correlation_id": cmd["correlation_id"],
        "generation": cmd.get("generation"),
        "round": 1,
        "state": "DONE",
        "executed_once": True,
        "retry_count": 0,
        "fallback_used": False,
        "evidence_refs": ["durable://terminal"],
        "task_submitted": False,
        "jules_task_started": False,
        "model_started": False,
    }
    value.update(changes)
    return value


def successor(old=None, **changes):
    old = old or command()
    value = command(
        "successor",
        generation=old.get("generation", 1) + 1,
        action="JULES_HUMAN_AUTH_BOOTSTRAP",
        expires_at=(NOW + timedelta(hours=2)).isoformat(),
    )
    value.update(changes)
    return value


class LateReceiptReconciliationTests(unittest.TestCase):
    def test_unknown_then_done_receipt_reconciles_without_erasing_history(self):
        old = command()
        original = state(old, status="UNKNOWN", failure_reason="no durable result")
        original_copy = deepcopy(original)
        refs = ["evidence/no-result.json", "evidence/timeout.json"]
        evidence, reconciled = reconcile_late_terminal_receipt(
            old,
            original,
            receipt(old),
            observed_at=NOW.isoformat(),
            prior_evidence_refs=refs,
            write_ambiguity=False,
            external_action_state="NONE",
        )
        self.assertEqual(original, original_copy)
        self.assertEqual(evidence["prior_state"], "UNKNOWN")
        self.assertEqual(evidence["prior_evidence_refs"], refs)
        self.assertEqual(reconciled["state"], "RECONCILED_LATE_RESULT")
        self.assertEqual(reconciled["last_receipt_id"], receipt(old)["receipt_id"])
        self.assertTrue(reconciled["late_terminal_receipt_observed"])
        validate_state(reconciled)
        validate_late_receipt_evidence(old, evidence)

    def test_successor_already_issued_is_recorded_but_old_is_never_replayed(self):
        old = command()
        nxt = successor(old)
        evidence, reconciled = reconcile_late_terminal_receipt(
            old,
            state(old),
            receipt(old),
            observed_at=NOW.isoformat(),
            prior_evidence_refs=["evidence/no-result.json"],
            successor_command=nxt,
            write_ambiguity=False,
            external_action_state="NONE",
        )
        self.assertTrue(evidence["successor_already_issued"])
        self.assertEqual(evidence["successor_command_id"], nxt["command_id"])
        self.assertEqual(receipt_replay_disposition(old, receipt(old)), "NO_OP")
        self.assertEqual(reconciled["successor_command_id"], nxt["command_id"])

    def test_duplicate_event_after_terminal_receipt_is_noop_even_with_stale_unknown_state(self):
        old = command()
        ledger = InMemoryLedger(state(old, status="UNKNOWN"))
        ledger.add_command(old)
        ledger.add_receipt(receipt(old))
        result = EventProcessor(
            ledger, repo=REPO, pr=4, observed_head=HEAD
        ).process(old["command_id"], now=NOW)
        self.assertEqual(result.status, "NO-OP")
        self.assertIn("terminal receipt", result.reason)

    def test_late_receipt_never_authorizes_reexecution_of_external_action(self):
        old = command()
        _, reconciled = reconcile_late_terminal_receipt(
            old,
            state(old),
            receipt(old),
            observed_at=NOW.isoformat(),
            prior_evidence_refs=["evidence/no-result.json"],
            write_ambiguity=False,
            external_action_state="NONE",
        )
        decision = successor_issue_gate(
            old,
            reconciled,
            receipt(old),
            successor_command=successor(old),
            write_ambiguity=False,
            external_action_state="OCCURRED",
            task_submitted=False,
            jules_task_started=False,
            model_started=False,
            now=NOW,
        )
        self.assertEqual(decision.state, SuccessorGateState.BLOCKED)
        self.assertEqual(receipt_replay_disposition(old, receipt(old)), "NO_OP")

    def test_late_pass_preserves_prior_unknown_evidence_refs(self):
        old = command()
        refs = ["evidence/unknown-close.json", "evidence/no-receipt.json"]
        evidence, _ = reconcile_late_terminal_receipt(
            old,
            state(old),
            receipt(old, state="DONE"),
            observed_at=NOW.isoformat(),
            prior_evidence_refs=refs,
            write_ambiguity=False,
            external_action_state="NONE",
        )
        self.assertEqual(evidence["late_receipt_state"], "DONE")
        self.assertEqual(evidence["prior_evidence_refs"], refs)
        self.assertIn("UNKNOWN", evidence["history_transition"])
        self.assertIn("RECONCILED_LATE_RESULT", evidence["history_transition"])

    def test_unknown_jules_model_or_external_state_defers_successor(self):
        old = command()
        _, reconciled = reconcile_late_terminal_receipt(
            old,
            state(old),
            receipt(old),
            observed_at=NOW.isoformat(),
            prior_evidence_refs=["evidence/unknown.json"],
            write_ambiguity=False,
            external_action_state="NONE",
        )
        cases = (
            {"external_action_state": "UNKNOWN"},
            {"task_submitted": "UNKNOWN"},
            {"jules_task_started": "UNKNOWN"},
            {"model_started": "UNKNOWN"},
        )
        for changes in cases:
            args = {
                "external_action_state": "NONE",
                "task_submitted": False,
                "jules_task_started": False,
                "model_started": False,
            }
            args.update(changes)
            with self.subTest(changes=changes):
                decision = successor_issue_gate(
                    old,
                    reconciled,
                    receipt(old),
                    successor_command=successor(old),
                    write_ambiguity=False,
                    now=NOW,
                    **args,
                )
                self.assertEqual(decision.state, SuccessorGateState.DEFERRED)

    def test_closed_without_receipt_defers_because_old_run_may_still_be_alive(self):
        old = command()
        decision = successor_issue_gate(
            old,
            state(old, status="UNKNOWN"),
            None,
            successor_command=successor(old),
            write_ambiguity=False,
            external_action_state="NONE",
            task_submitted=False,
            jules_task_started=False,
            model_started=False,
            now=NOW,
        )
        self.assertEqual(decision.state, SuccessorGateState.DEFERRED)
        self.assertIn("completion remains uncertain", decision.reason)

    def test_late_receipt_must_be_reconciled_before_successor(self):
        old = command()
        decision = successor_issue_gate(
            old,
            state(old, status="UNKNOWN"),
            receipt(old),
            successor_command=successor(old),
            write_ambiguity=False,
            external_action_state="NONE",
            task_submitted=False,
            jules_task_started=False,
            model_started=False,
            now=NOW,
        )
        self.assertEqual(decision.state, SuccessorGateState.DEFERRED)
        self.assertIn("not durably reconciled", decision.reason)

    def test_safe_reconciled_terminal_can_allow_fresh_successor(self):
        old = command()
        _, reconciled = reconcile_late_terminal_receipt(
            old,
            state(old),
            receipt(old),
            observed_at=NOW.isoformat(),
            prior_evidence_refs=["evidence/no-result.json"],
            write_ambiguity=False,
            external_action_state="NONE",
        )
        self.assertEqual(
            durable_run_completion_state(old, reconciled, receipt(old)),
            "TERMINAL_DURABLE",
        )
        decision = successor_issue_gate(
            old,
            reconciled,
            receipt(old),
            successor_command=successor(old),
            write_ambiguity=False,
            external_action_state="NONE",
            task_submitted=False,
            jules_task_started=False,
            model_started=False,
            now=NOW,
        )
        self.assertEqual(
            decision.state, SuccessorGateState.ALLOW_NEW_SUCCESSOR
        )

    def test_write_ambiguity_defers_successor(self):
        old = command()
        _, reconciled = reconcile_late_terminal_receipt(
            old,
            state(old),
            receipt(old),
            observed_at=NOW.isoformat(),
            prior_evidence_refs=["evidence/no-result.json"],
            write_ambiguity=True,
            external_action_state="UNKNOWN",
        )
        decision = successor_issue_gate(
            old,
            reconciled,
            receipt(old),
            successor_command=successor(old),
            write_ambiguity=True,
            external_action_state="NONE",
            task_submitted=False,
            jules_task_started=False,
            model_started=False,
            now=NOW,
        )
        self.assertEqual(decision.state, SuccessorGateState.DEFERRED)

    def test_schema_files_include_reconciliation_contract(self):
        root = Path(__file__).resolve().parents[1]
        state_schema = json.loads((root / "schema" / "state.schema.json").read_text())
        late_schema = json.loads(
            (root / "schema" / "late_receipt_reconciliation.schema.json").read_text()
        )
        self.assertIn(
            "RECONCILED_LATE_RESULT",
            state_schema["properties"]["state"]["enum"],
        )
        required = set(late_schema["required"])
        for field in (
            "prior_state",
            "late_receipt_id",
            "prior_evidence_refs",
            "replay_disposition",
            "successor_already_issued",
        ):
            self.assertIn(field, required)


if __name__ == "__main__":
    unittest.main()
