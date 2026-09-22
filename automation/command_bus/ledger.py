from __future__ import annotations

from copy import deepcopy

from .validator import validate_command, validate_receipt, validate_state

class InMemoryLedger:
    """Append-only test ledger; production persistence is Git history."""
    def __init__(self, state: dict):
        self.state = deepcopy(validate_state(state))
        self.commands: list[dict] = []
        self.receipts: list[dict] = []

    def add_command(self, command: dict) -> None:
        command = deepcopy(validate_command(command))
        if any(c["command_id"] == command["command_id"] for c in self.commands):
            raise ValueError("command is immutable and already exists")
        self.commands.append(command)

    def add_receipt(self, receipt: dict) -> None:
        receipt = deepcopy(validate_receipt(receipt))
        if any(r["receipt_id"] == receipt["receipt_id"] for r in self.receipts):
            raise ValueError("receipt is immutable and already exists")
        self.receipts.append(receipt)

    def terminal_for(self, command_id: str) -> dict | None:
        return next((deepcopy(r) for r in self.receipts if r["command_id"] == command_id), None)

    def has_command(self, command_id: str) -> bool:
        return any(c["command_id"] == command_id for c in self.commands)
