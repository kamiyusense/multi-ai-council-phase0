"""One-shot approval / consumed / terminal state for one Claude turn through the gated container (Path B).

Same file layout and rules as ``m9_live_state`` (which stays Codex-only), with a Claude-specific decision and the
Gate dispatch id bound into the approval record:

  approval.json          {"record": {...}, "approval_sha256": "..."}  (typed human approval)
  consumed.json          written atomically (O_EXCL) right before the single live turn
  terminal_receipt.json  written atomically (O_EXCL) after the first terminal outcome

A real Claude CLI can only be started while ``approval.json`` is valid, ``consumed.json`` matches it and
``terminal_receipt.json`` does not exist yet. Nothing here starts a process or reads an account.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .m9_live_state import (
    APPROVAL_FILE,
    CONSUMED_FILE,
    TERMINAL_FILE,
    LiveAuthorization,
    canonical_sha256,
    read_json,
)

__all__ = [
    "APPROVAL_FILE", "CONSUMED_FILE", "TERMINAL_FILE", "DECISION", "SCOPE", "PROVIDER",
    "LiveAuthorization", "build_approval", "verify_approval_record", "verify_claude_live_authorization",
]

DECISION = "APPROVE_CLAUDE_PATH_B_ONE_TURN"
SCOPE = "CLAUDE_PATH_B_ONE_TURN_ONLY"
PROVIDER = "anthropic"

_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
_RECORD_KEYS = frozenset({
    "decision", "scope", "one_shot", "provider", "dispatch_id",
    "max_dispatches", "max_prompts", "max_generations", "retry", "fallback",
})


def build_approval(dispatch_id: str) -> dict[str, Any]:
    """The approval file content for one Gate dispatch (the caller writes it after the human typed the phrase)."""
    record = {
        "decision": DECISION, "scope": SCOPE, "one_shot": True, "provider": PROVIDER, "dispatch_id": dispatch_id,
        "max_dispatches": 1, "max_prompts": 1, "max_generations": 1, "retry": 0, "fallback": "disabled",
    }
    approval = {"record": record, "approval_sha256": canonical_sha256(record)}
    verify_approval_record(approval)
    return approval


def verify_approval_record(approval: Any) -> str:
    """Validate the approval file content; returns its sha256 or raises ValueError."""
    if not isinstance(approval, dict) or set(approval) != {"record", "approval_sha256"}:
        raise ValueError("approval file shape is invalid")
    record = approval["record"]
    if not isinstance(record, dict) or set(record) != _RECORD_KEYS:
        raise ValueError("approval record is invalid")
    if record["decision"] != DECISION or record["scope"] != SCOPE:
        raise ValueError(f"approval decision/scope is not {DECISION} / {SCOPE}")
    if record["one_shot"] is not True or record["provider"] != PROVIDER:
        raise ValueError("approval must be one_shot for provider anthropic")
    if not isinstance(record["dispatch_id"], str) or not _UUID.match(record["dispatch_id"]):
        raise ValueError("approval dispatch_id must be a lower-case UUID")
    if record["max_dispatches"] != 1 or record["max_prompts"] != 1 or record["max_generations"] != 1:
        raise ValueError("approval limits must be 1/1/1")
    if record["retry"] != 0 or record["fallback"] != "disabled":
        raise ValueError("approval must keep retry=0 and fallback=disabled")
    digest = canonical_sha256(record)
    if approval["approval_sha256"] != digest:
        raise ValueError("approval hash does not match the record")
    return digest


def verify_claude_live_authorization(auth: Any, provider_id: str) -> str:
    """Fail closed unless this exact approval was just consumed and nothing terminal exists; returns the dispatch id."""
    if not isinstance(auth, LiveAuthorization):
        raise ValueError("live Claude turn requires a LiveAuthorization")
    if provider_id != PROVIDER:
        raise ValueError("this one-shot state is only for provider anthropic")
    state = Path(auth.state_dir)
    try:
        approval = read_json(state / APPROVAL_FILE)
        digest = verify_approval_record(approval)
        consumed = read_json(state / CONSUMED_FILE)
    except (OSError, ValueError) as exc:
        raise ValueError(f"APPROVAL_PROVENANCE_NOT_VERIFIED: {exc}") from exc
    if digest != auth.approval_sha256 or not isinstance(consumed, dict) or consumed.get("approval_sha256") != digest:
        raise ValueError("APPROVAL_PROVENANCE_NOT_VERIFIED: approval was not consumed for this run")
    if (state / TERMINAL_FILE).exists():
        raise ValueError("one-shot already finished: terminal receipt exists")
    return approval["record"]["dispatch_id"]
