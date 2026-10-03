"""One-shot approval / consumed / terminal state for the first Codex LIVE proof.

Small, dependency-free helpers shared by the M9 runner and the transport guard.
Files live in one state directory:

  approval.json          {"record": {...}, "approval_sha256": "..."}  (typed human approval)
  consumed.json          written atomically (O_EXCL) right before the single live turn
  terminal_receipt.json  written atomically (O_EXCL) after the first terminal outcome

A real (non-fixture) Codex backend can only be launched while `approval.json` is valid and
`consumed.json` matches it and `terminal_receipt.json` does not exist yet.
"""

from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

APPROVAL_FILE = "approval.json"
CONSUMED_FILE = "consumed.json"
TERMINAL_FILE = "terminal_receipt.json"

DECISION = "APPROVE_FIRST_LIVE_POC"
SCOPE = "FIRST_LIVE_POC_ONLY"
PROVIDER = "openai"


def canonical_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True, ensure_ascii=False)


def canonical_sha256(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def read_json(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


def write_exclusive(path: Path, value: Any) -> bool:
    """Create `path` atomically with JSON content; False if it already exists."""
    data = (json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8")
    try:
        fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    try:
        os.write(fd, data)
    finally:
        os.close(fd)
    return True


@dataclass(frozen=True, slots=True)
class LiveAuthorization:
    state_dir: Path
    approval_sha256: str


def verify_approval_record(approval: Any) -> str:
    """Validate the approval file content; returns its sha256 or raises ValueError."""
    if not isinstance(approval, dict) or set(approval) != {"record", "approval_sha256"}:
        raise ValueError("approval file shape is invalid")
    record = approval["record"]
    if not isinstance(record, dict):
        raise ValueError("approval record is invalid")
    if record.get("decision") != DECISION or record.get("scope") != SCOPE:
        raise ValueError("approval decision/scope is not APPROVE_FIRST_LIVE_POC / FIRST_LIVE_POC_ONLY")
    if record.get("one_shot") is not True or record.get("provider") != PROVIDER:
        raise ValueError("approval must be one_shot for provider openai")
    if record.get("max_dispatches") != 1 or record.get("max_prompts") != 1 or record.get("max_generations") != 1:
        raise ValueError("approval limits must be 1/1/1")
    if record.get("retry") != 0 or record.get("fallback") != "disabled":
        raise ValueError("approval must keep retry=0 and fallback=disabled")
    digest = canonical_sha256(record)
    if approval["approval_sha256"] != digest:
        raise ValueError("approval hash does not match the record")
    return digest


def verify_live_authorization(auth: Any, provider_id: str) -> None:
    """Fail closed unless this exact approval was just consumed and nothing terminal exists."""
    if not isinstance(auth, LiveAuthorization):
        raise ValueError("live backend requires a LiveAuthorization")
    if provider_id != PROVIDER:
        raise ValueError("live backend is only approved for provider openai")
    state = Path(auth.state_dir)
    try:
        digest = verify_approval_record(read_json(state / APPROVAL_FILE))
        consumed = read_json(state / CONSUMED_FILE)
    except (OSError, ValueError) as exc:
        raise ValueError(f"APPROVAL_PROVENANCE_NOT_VERIFIED: {exc}") from exc
    if digest != auth.approval_sha256 or not isinstance(consumed, dict) or consumed.get("approval_sha256") != digest:
        raise ValueError("APPROVAL_PROVENANCE_NOT_VERIFIED: approval was not consumed for this run")
    if (state / TERMINAL_FILE).exists():
        raise ValueError("one-shot already finished: terminal receipt exists")
