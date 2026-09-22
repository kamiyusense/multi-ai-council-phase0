"""Durable GitHub-path persistence for executor handoffs."""

from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from .executor import ExecutorLedger, ExecutorResult
from .state_machine import StateMachine

_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
_PREFIXES = {
    "request": "execution_requests",
    "claim": "execution_claims",
    "result": "execution_results",
    "receipt": "execution_receipts",
}
_IDS = {
    "request": "request_id",
    "claim": "claim_id",
    "result": "result_id",
    "receipt": "receipt_id",
}


@dataclass(frozen=True)
class ExecutorContent:
    path: str
    text: str
    sha: str


class ExecutorContentsClient(Protocol):
    def get(self, path: str, ref: str) -> ExecutorContent | None: ...
    def list(self, prefix: str, ref: str) -> list[ExecutorContent]: ...
    def create(self, path: str, text: str, message: str, branch: str) -> ExecutorContent: ...
    def update(self, path: str, text: str, sha: str, message: str, branch: str) -> ExecutorContent: ...


def executor_record_path(kind: str, loop_id: str, record_id: str) -> str:
    if kind not in _PREFIXES:
        raise ValueError("unknown executor record kind")
    _safe(loop_id, "loop_id")
    _safe(record_id, _IDS[kind])
    return f"{_PREFIXES[kind]}/{loop_id}/{record_id}.json"


def executor_state_path(loop_id: str) -> str:
    _safe(loop_id, "loop_id")
    return f"state/{loop_id}.json"


class GitHubExecutorBackend:
    def __init__(self, client: ExecutorContentsClient, *, branch: str, ref: str | None = None):
        self.client = client
        self.branch = branch
        self.ref = ref or branch

    def append(self, kind: str, loop_id: str, record: dict[str, Any]) -> ExecutorResult:
        try:
            _validate(kind, loop_id, record)
            _validate_predecessors(self, kind, loop_id, record)
            record_id = record[_IDS[kind]]
            path = executor_record_path(kind, loop_id, record_id)
            if self.client.get(path, self.branch) is not None:
                return ExecutorResult("BLOCKED", "duplicate durable executor record")
            self.client.create(path, _canonical(record), f"append executor {kind} {record_id}", self.branch)
            verified = self.client.get(path, self.branch)
            if verified is None:
                return ExecutorResult("UNKNOWN", "executor write readback unavailable")
            readback = _decode(kind, loop_id, record_id, verified)
            if readback != record:
                return ExecutorResult("UNKNOWN", "executor write readback mismatch", readback)
            return ExecutorResult("ACCEPTED", "executor record written and verified", readback)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
            return ExecutorResult("UNKNOWN", str(exc))

    def write_state(self, loop_id: str, state: dict[str, Any]) -> ExecutorResult:
        try:
            _validate_state(loop_id, state)
            path = executor_state_path(loop_id)
            text = _canonical(state)
            current = self.client.get(path, self.branch)
            if current is None:
                self.client.create(path, text, f"create executor state {loop_id}", self.branch)
            else:
                self.client.update(path, text, current.sha, f"update executor state {loop_id}", self.branch)
            verified = self.client.get(path, self.branch)
            if verified is None:
                return ExecutorResult("UNKNOWN", "executor state readback unavailable")
            readback = json.loads(verified.text)
            _validate_state(loop_id, readback)
            if readback != state:
                return ExecutorResult("UNKNOWN", "executor state readback mismatch", readback)
            return ExecutorResult("ACCEPTED", "executor state written and verified", readback)
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
            return ExecutorResult("UNKNOWN", str(exc))

    def recover(self, loop_id: str) -> ExecutorResult:
        try:
            state_content = self.client.get(executor_state_path(loop_id), self.ref)
            if state_content is None:
                return ExecutorResult("UNKNOWN", "executor durable state missing")
            state = json.loads(state_content.text)
            _validate_state(loop_id, state)
            records: dict[str, list[dict[str, Any]]] = {kind: [] for kind in _PREFIXES}
            for kind, prefix in _PREFIXES.items():
                for content in sorted(self.client.list(f"{prefix}/{loop_id}/", self.ref), key=lambda x: x.path):
                    raw = json.loads(content.text)
                    if not isinstance(raw, dict):
                        raise ValueError(f"malformed executor {kind}")
                    record_id = raw.get(_IDS[kind])
                    if content.path != executor_record_path(kind, loop_id, record_id):
                        raise ValueError(f"executor {kind} path identity mismatch")
                    _validate(kind, loop_id, raw)
                    records[kind].append(raw)
            _reject_duplicates(records)
            _validate_graph(records)
            ledger = ExecutorLedger()
            for record in records["request"]:
                ledger.append_request(record)
            for record in records["claim"]:
                ledger.append_claim(record)
            for record in records["result"]:
                ledger.append_result(record)
            for record in records["receipt"]:
                if any(r["receipt_id"] == record["receipt_id"] for r in ledger.receipts):
                    raise ValueError("duplicate executor receipt")
                ledger.receipts.append(deepcopy(record))
            return ExecutorResult("RECOVERED", "executor durable session recovered", {"ledger": ledger, "state": state})
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
            return ExecutorResult("UNKNOWN", str(exc))


def _validate(kind: str, loop_id: str, record: dict[str, Any]) -> None:
    if kind not in _PREFIXES or not isinstance(record, dict):
        raise ValueError("invalid executor durable record")
    _safe(record.get(_IDS[kind]), _IDS[kind])
    if kind in {"request", "result", "receipt"} and record.get("loop_id") != loop_id:
        raise ValueError("executor loop/path mismatch")
    ledger = ExecutorLedger()
    if kind == "request":
        ledger.append_request(record)
    elif kind == "claim":
        ledger.append_claim(record)
    elif kind == "result":
        ledger.append_result(record)
    else:
        ledger.from_records({"receipts": [record]})


def _validate_predecessors(
    backend: GitHubExecutorBackend, kind: str, loop_id: str, record: dict[str, Any]
) -> None:
    if kind == "request":
        return
    request = _read(backend, "request", loop_id, record["request_id"])
    if kind == "claim":
        if record["executor_role"] != request["executor_role"]:
            raise ValueError("executor claim role mismatch")
        if _time(record["claimed_at"]) >= _time(record["expires_at"]) or _time(record["expires_at"]) > _time(request["expires_at"]):
            raise ValueError("executor claim/request expiry mismatch")
        return
    if kind == "result":
        _match(request, record)
        submitted = _time(record["submitted_at"])
        owners = []
        for item in backend.client.list(f"execution_claims/{loop_id}/", backend.branch):
            claim = json.loads(item.text)
            _validate("claim", loop_id, claim)
            if (
                claim.get("request_id") == record["request_id"]
                and claim.get("executor_instance_id") == record.get("executor_instance_id")
                and claim.get("executor_generation") == record.get("executor_generation")
                and _time(claim["claimed_at"]) <= submitted < _time(claim["expires_at"])
            ):
                owners.append(claim)
        if len(owners) != 1:
            raise ValueError("executor result has no unique valid claim")
        return
    result = _read(backend, "result", loop_id, record["result_id"])
    if result["request_id"] != record["request_id"]:
        raise ValueError("executor receipt request/result mismatch")
    _match(result, record)


def _read(
    backend: GitHubExecutorBackend, kind: str, loop_id: str, record_id: str
) -> dict[str, Any]:
    content = backend.client.get(executor_record_path(kind, loop_id, record_id), backend.branch)
    if content is None:
        raise ValueError(f"referenced executor {kind} unavailable")
    return _decode(kind, loop_id, record_id, content)


def _decode(
    kind: str, loop_id: str, record_id: str, content: ExecutorContent
) -> dict[str, Any]:
    if content.path != executor_record_path(kind, loop_id, record_id):
        raise ValueError("executor durable path mismatch")
    record = json.loads(content.text)
    if not isinstance(record, dict) or record.get(_IDS[kind]) != record_id:
        raise ValueError("executor durable identity mismatch")
    _validate(kind, loop_id, record)
    return record


def _validate_graph(records: dict[str, list[dict[str, Any]]]) -> None:
    requests = {r["request_id"]: r for r in records["request"]}
    results = {r["result_id"]: r for r in records["result"]}
    claims: dict[str, list[dict[str, Any]]] = {}
    for claim in records["claim"]:
        request = requests.get(claim["request_id"])
        if request is None or claim["executor_role"] != request["executor_role"]:
            raise ValueError("executor claim references invalid request")
        if _time(claim["claimed_at"]) >= _time(claim["expires_at"]) or _time(claim["expires_at"]) > _time(request["expires_at"]):
            raise ValueError("executor claim/request expiry mismatch")
        claims.setdefault(claim["request_id"], []).append(claim)
    for group in claims.values():
        generations = [c["executor_generation"] for c in group]
        if len(generations) != len(set(generations)):
            raise ValueError("duplicate executor generation")
    for result in records["result"]:
        request = requests.get(result["request_id"])
        if request is None:
            raise ValueError("executor result references missing request")
        _match(request, result)
        submitted = _time(result["submitted_at"])
        owners = [
            c for c in claims.get(result["request_id"], [])
            if c["executor_instance_id"] == result["executor_instance_id"]
            and c["executor_generation"] == result["executor_generation"]
            and _time(c["claimed_at"]) <= submitted < _time(c["expires_at"])
        ]
        if len(owners) != 1:
            raise ValueError("executor result has no unique valid claim")
    for receipt in records["receipt"]:
        result = results.get(receipt["result_id"])
        request = requests.get(receipt["request_id"])
        if result is None or request is None or result["request_id"] != receipt["request_id"]:
            raise ValueError("executor receipt references missing predecessor")
        _match(result, receipt)


def _reject_duplicates(records: dict[str, list[dict[str, Any]]]) -> None:
    for kind, items in records.items():
        ids = [item[_IDS[kind]] for item in items]
        if len(ids) != len(set(ids)):
            raise ValueError(f"duplicate executor {kind} identity")


def _validate_state(loop_id: str, state: dict[str, Any]) -> None:
    if not isinstance(state, dict) or state.get("loop_id") != loop_id:
        raise ValueError("executor state loop/path mismatch")
    StateMachine(state)


def _match(expected: dict[str, Any], actual: dict[str, Any]) -> None:
    keys = ("loop_id", "round", "correlation_id", "expected_target_head")
    if tuple(expected.get(k) for k in keys) != tuple(actual.get(k) for k in keys):
        raise ValueError("executor durable context mismatch")
    if "expected_target_tree" in expected:
        if actual.get("expected_target_tree") != expected.get("expected_target_tree"):
            raise ValueError("executor durable target tree mismatch")


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _safe(value: Any, field: str) -> None:
    if not isinstance(value, str) or not value or value in {".", ".."} or not _COMPONENT.fullmatch(value):
        raise ValueError(f"unsafe executor {field}")
