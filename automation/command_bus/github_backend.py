"""GitHub Contents-style durable persistence for reviewer records.

The client protocol is deliberately tiny so the runtime can use a GitHub
Contents API adapter while tests use a deterministic in-memory fake. Only
state paths may be updated; request, claim, response, and receipt paths are
append-only and duplicate writes are rejected before any overwrite.
"""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Protocol

from .reviewer import ReviewerLedger, ReviewResult
from .state_machine import StateMachine

_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PREFIXES = {
    "request": "review_requests",
    "claim": "review_claims",
    "response": "review_responses",
    "receipt": "review_receipts",
}
_IDS = {"request": "request_id", "claim": "claim_id", "response": "response_id", "receipt": "receipt_id"}


@dataclass(frozen=True)
class GitHubContent:
    path: str
    text: str
    sha: str


class GitHubContentsClient(Protocol):
    """Minimal adapter over GitHub Contents API read/create/update/list calls."""

    def get(self, path: str, ref: str) -> GitHubContent | None: ...
    def list(self, prefix: str, ref: str) -> list[GitHubContent]: ...
    def create(self, path: str, text: str, message: str, branch: str) -> GitHubContent: ...
    def update(self, path: str, text: str, sha: str, message: str, branch: str) -> GitHubContent: ...


def record_path(kind: str, loop_id: str, record_id: str) -> str:
    if kind not in _PREFIXES:
        raise ValueError("unknown reviewer record kind")
    _safe_component(loop_id, "loop_id")
    _safe_component(record_id, _IDS[kind])
    return f"{_PREFIXES[kind]}/{loop_id}/{record_id}.json"


def state_path(loop_id: str) -> str:
    _safe_component(loop_id, "loop_id")
    return f"state/{loop_id}.json"


class GitHubRecordBackend:
    def __init__(self, client: GitHubContentsClient, *, branch: str, ref: str | None = None):
        self.client = client
        self.branch = branch
        self.ref = ref or branch

    def append(self, kind: str, loop_id: str, record: dict[str, Any]) -> ReviewResult:
        try:
            if not isinstance(record, dict):
                raise ValueError("record must be an object")
            record_id = record.get(_IDS[kind])
            path = record_path(kind, loop_id, record_id)
            if self.client.get(path, self.ref) is not None:
                return ReviewResult("BLOCKED", "duplicate durable record")
            content = json.dumps(record, sort_keys=True, separators=(",", ":"))
            written = self.client.create(path, content, f"append reviewer {kind} {record_id}", self.branch)
            return ReviewResult("ACCEPTED", "append-only record written", json.loads(written.text))
        except (KeyError, TypeError, ValueError) as exc:
            return ReviewResult("UNKNOWN", str(exc))

    def read(self, kind: str, loop_id: str, record_id: str) -> ReviewResult:
        try:
            path = record_path(kind, loop_id, record_id)
            content = self.client.get(path, self.ref)
            if content is None:
                return ReviewResult("UNKNOWN", "durable record missing")
            record = json.loads(content.text)
            if not isinstance(record, dict):
                raise ValueError("durable record is not an object")
            if record.get(_IDS[kind]) != record_id:
                raise ValueError("durable record identity mismatch")
            return ReviewResult("READ", "durable record read", record)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return ReviewResult("UNKNOWN", str(exc))

    def write_state(self, loop_id: str, state: dict[str, Any]) -> ReviewResult:
        try:
            if not isinstance(state, dict):
                raise ValueError("state must be an object")
            StateMachine(state)
            path = state_path(loop_id)
            text = json.dumps(state, sort_keys=True, separators=(",", ":"))
            current = self.client.get(path, self.ref)
            if current is None:
                written = self.client.create(path, text, f"create reviewer state {loop_id}", self.branch)
            else:
                written = self.client.update(path, text, current.sha, f"update reviewer state {loop_id}", self.branch)
            return ReviewResult("ACCEPTED", "mutable state written", json.loads(written.text))
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            return ReviewResult("UNKNOWN", str(exc))

    def read_state(self, loop_id: str) -> ReviewResult:
        try:
            path = state_path(loop_id)
            content = self.client.get(path, self.ref)
            if content is None:
                return ReviewResult("UNKNOWN", "durable state missing")
            state = json.loads(content.text)
            if not isinstance(state, dict):
                raise ValueError("durable state is not an object")
            StateMachine(state)
            return ReviewResult("READ", "durable state read", state)
        except (TypeError, ValueError, KeyError, json.JSONDecodeError) as exc:
            return ReviewResult("UNKNOWN", str(exc))

    def recover(self, loop_id: str, *, expected_ids: dict[str, list[str]] | None = None) -> ReviewResult:
        """Reconstruct a fresh ledger from durable records, fail-closed."""
        state_result = self.read_state(loop_id)
        if state_result.status != "READ":
            return state_result
        records: dict[str, list[dict[str, Any]]] = {kind: [] for kind in _PREFIXES}
        try:
            for kind, prefix in _PREFIXES.items():
                for content in sorted(self.client.list(f"{prefix}/{loop_id}/", self.ref), key=lambda item: item.path):
                    record = json.loads(content.text)
                    if not isinstance(record, dict) or record.get(_IDS[kind]) is None:
                        raise ValueError(f"malformed {kind} record")
                    records[kind].append(record)
            for kind, ids in (expected_ids or {}).items():
                present = {record.get(_IDS[kind]) for record in records.get(kind, [])}
                if any(record_id not in present for record_id in ids):
                    raise ValueError(f"missing expected {kind} record")
            ledger = ReviewerLedger()
            for record in records["request"]:
                ledger.append_request(record)
            for record in records["claim"]:
                ledger.append_claim(record)
            for record in records["response"]:
                ledger.append_response(record)
            for record in records["receipt"]:
                ledger.receipts.append(deepcopy(record))
            return ReviewResult("RECOVERED", "fresh durable session recovered", {"ledger": ledger, "state": state_result.record})
        except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
            return ReviewResult("UNKNOWN", str(exc))


def _safe_component(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value or value in {".", ".."} or not _COMPONENT.fullmatch(value):
        raise ValueError(f"unsafe {field}")
