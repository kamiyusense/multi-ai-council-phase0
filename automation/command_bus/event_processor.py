from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .ledger import InMemoryLedger
from .state_machine import StateMachine
from .validator import validate_command

@dataclass(frozen=True)
class ProcessResult:
    status: str
    reason: str
    receipt: dict | None = None

class EventProcessor:
    def __init__(self, ledger: InMemoryLedger, *, repo: str, pr: int, observed_head: str):
        self.ledger, self.repo, self.pr, self.observed_head = ledger, repo, pr, observed_head

    def process(self, command_id: str | None = None, *, now: datetime | None = None) -> ProcessResult:
        if command_id is None:
            return ProcessResult("NO-OP", "no command in event")
        command = next((c for c in self.ledger.commands if c["command_id"] == command_id), None)
        if command is None:
            return ProcessResult("NO-OP", "command not found")
        if self.ledger.terminal_for(command_id):
            return ProcessResult("NO-OP", "terminal receipt already exists")
        sm = StateMachine(self.ledger.state)
        if sm.mark_expired(now):
            return ProcessResult("BLOCKED", "expired")
        reason = sm.blocked_reason(now)
        if reason:
            return ProcessResult("BLOCKED", reason)
        try:
            validate_command(command)
            if command["expected_repo"] != self.repo or command["expected_pr"] != self.pr or command["target"] != "work":
                raise ValueError("wrong repository or PR")
            if command["expected_head"] != self.observed_head:
                raise ValueError("expected head mismatch")
            if command["loop_id"] != self.ledger.state["loop_id"] or command["round"] != self.ledger.state["round"] + 1:
                raise ValueError("round or loop correlation mismatch")
            if command["correlation_id"] != f"{command['loop_id']}-round-{command['round']}" and command["action"] != "STOP":
                raise ValueError("correlation mismatch")
            if command["action"] == "STOP":
                sm.request_stop()
                result_state = "CANCELLED"
            else:
                self.ledger.state["round"] = command["round"]
                self.ledger.state["last_command_id"] = command_id
                self.ledger.state["state"] = "WAITING_FOR_EVIDENCE"
                result_state = "DONE"
            receipt = self._receipt(command, result_state)
            self.ledger.add_receipt(receipt)
            self.ledger.state["last_receipt_id"] = receipt["receipt_id"]
            return ProcessResult("PROCESSED", result_state, receipt)
        except ValueError as exc:
            receipt = self._receipt(command, "BLOCKED", str(exc))
            self.ledger.add_receipt(receipt)
            return ProcessResult("BLOCKED", str(exc), receipt)

    def _receipt(self, command: dict, state: str, reason: str | None = None) -> dict:
        receipt = {"schema_version": 1, "receipt_id": command["command_id"], "command_id": command["command_id"], "loop_id": command["loop_id"], "correlation_id": command["correlation_id"], "state": state, "executed_once": True, "github_head_before": self.observed_head, "github_head_after": self.observed_head, "external_send_attempted": False, "external_send_readback_verified": "NO", "retry_count": 0, "fallback_used": False, "evidence_refs": []}
        if reason:
            receipt["reason"] = reason
        return receipt
