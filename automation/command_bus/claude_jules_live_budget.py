"""Persistent, create-only budget ledger for real Jules dispatches (Loop A).

The human authorization caps Loop A at ``LOOP_A_LIVE_BUDGET`` real Jules
dispatches in total, across sessions, origin loops, rounds and branches.  One
slot record is created *before* the irreversible carrier command write and is
never released: a dispatch whose outcome is unknown still consumes its slot.
Slots are numbered 1..cap; two controllers racing for the same slot collide on
the create-only path and the loser re-reads the ledger, so the cap cannot be
exceeded.  The cap is a module constant, not a policy field, so it cannot be
raised by editing a policy file.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from .claude_jules_dispatch import EVIDENCE_ROOT, canonical_json, sha256_of

LOOP_A_LIVE_BUDGET = 10
SLOT_PROFILE = "CLAUDE_AUTO_LIVE_BUDGET_SLOT_V1"
_PREFIX = f"{EVIDENCE_ROOT}/claude-auto-live-budget/"
_SLOT_FILE = re.compile(r"^slot-([0-9]{2})\.json$")
_SLOT_KEYS = {"schema_version", "profile", "slot", "cap", "command_id", "intent_sha256", "origin_loop_id",
              "acquired_at", "counts_as_used", "retry_count", "slot_sha256"}


def slot_path(slot: int) -> str:
    if isinstance(slot, bool) or not isinstance(slot, int) or not 1 <= slot <= 99:
        raise ValueError("invalid budget slot")
    return f"{_PREFIX}slot-{slot:02d}.json"


@dataclass(frozen=True)
class BudgetResult:
    status: str  # ACQUIRED / RECOVERED / EXHAUSTED / COLLISION / UNKNOWN
    reason: str
    record: dict[str, Any] | None = None


def validate_slot(record: Any, *, path: str | None = None) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) != _SLOT_KEYS:
        raise ValueError("budget slot keys mismatch")
    if record["schema_version"] != 1 or record["profile"] != SLOT_PROFILE:
        raise ValueError("unsupported budget slot")
    if record["cap"] != LOOP_A_LIVE_BUDGET or record["counts_as_used"] is not True or record["retry_count"] != 0:
        raise ValueError("budget slot invariants violated")
    if record["slot_sha256"] != sha256_of({k: v for k, v in record.items() if k != "slot_sha256"}):
        raise ValueError("budget slot digest mismatch")
    if path is not None and path != slot_path(record["slot"]):
        raise ValueError("budget slot path mismatch")
    return record


class LiveBudgetLedger:
    def __init__(self, client: Any, *, data_branch: str, cap: int = LOOP_A_LIVE_BUDGET):
        if cap != LOOP_A_LIVE_BUDGET:
            raise ValueError("the Loop A live budget cap is fixed by the human authorization")
        self.client, self.branch, self.cap = client, data_branch, cap

    def slots(self) -> list[dict[str, Any]]:
        records = []
        for content in self.client.list(_PREFIX, self.branch):
            if _SLOT_FILE.fullmatch(content.path[len(_PREFIX):]) is None:
                raise ValueError("unexpected file in budget ledger")
            records.append(validate_slot(json.loads(content.text), path=content.path))
        records.sort(key=lambda r: r["slot"])
        if [r["slot"] for r in records] != list(range(1, len(records) + 1)):
            raise ValueError("budget ledger slots are not contiguous")
        if len({r["command_id"] for r in records}) != len(records):
            raise ValueError("one command consumed two budget slots")
        if len(records) > self.cap:
            raise ValueError("budget ledger exceeds the cap")
        return records

    def used(self) -> int:
        return len(self.slots())

    def acquire(self, *, command_id: str, intent_sha256: str, origin_loop_id: str, acquired_at: str) -> BudgetResult:
        for _ in range(self.cap + 1):
            try:
                slots = self.slots()
            except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
                return BudgetResult("UNKNOWN", f"budget ledger unverifiable: {exc}")
            except Exception as exc:
                return BudgetResult("UNKNOWN", f"budget ledger read failed: {exc}")
            mine = [s for s in slots if s["command_id"] == command_id]
            if mine:
                if mine[0]["intent_sha256"] != intent_sha256:
                    return BudgetResult("COLLISION", "budget slot for this command is bound to another intent")
                return BudgetResult("RECOVERED", f"budget slot {mine[0]['slot']} already held", mine[0])
            if len(slots) >= self.cap:
                return BudgetResult("EXHAUSTED", f"LIVE budget exhausted ({len(slots)}/{self.cap}); no further dispatch")
            record = {"schema_version": 1, "profile": SLOT_PROFILE, "slot": len(slots) + 1, "cap": self.cap,
                      "command_id": command_id, "intent_sha256": intent_sha256, "origin_loop_id": origin_loop_id,
                      "acquired_at": acquired_at, "counts_as_used": True, "retry_count": 0}
            record["slot_sha256"] = sha256_of(record)
            path = slot_path(record["slot"])
            try:
                if self.client.get(path, self.branch) is None:
                    try:
                        self.client.create(path, canonical_json(record), f"Claude AUTO live budget slot {record['slot']}/{self.cap}", self.branch)
                    except Exception:
                        pass  # readback decides
                readback = self.client.get(path, self.branch)
            except Exception as exc:
                return BudgetResult("UNKNOWN", f"budget slot readback failed: {exc}")
            if readback is None:
                return BudgetResult("UNKNOWN", "budget slot create not proven by readback")
            try:
                if json.loads(readback.text) == record:
                    return BudgetResult("ACQUIRED", f"budget slot {record['slot']}/{self.cap} acquired", record)
            except json.JSONDecodeError:
                return BudgetResult("UNKNOWN", "budget slot unreadable")
            # Another controller won this slot: re-read the ledger and try the next one.
        return BudgetResult("UNKNOWN", "budget ledger kept changing")
