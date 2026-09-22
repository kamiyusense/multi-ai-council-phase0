"""Exchangeable executor-role protocol.

This layer prepares deterministic work handoffs without binding correctness to
Chat, thread, browser, or provider session identifiers. The current protocol
accepts PREPARE_ONLY requests only. Live execution is deliberately outside this
module and requires a separately authorized adapter.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .state_machine import StateMachine


def _utc(value: datetime | None) -> datetime:
    return value or datetime.now(timezone.utc)


def _parse(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class ExecutorResult:
    status: str
    reason: str
    record: dict[str, Any] | None = None


class ExecutorLedger:
    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.claims: list[dict[str, Any]] = []
        self.results: list[dict[str, Any]] = []
        self.receipts: list[dict[str, Any]] = []

    def append_request(self, record: dict[str, Any]) -> None:
        _validate_request(record)
        if any(item["request_id"] == record["request_id"] for item in self.requests):
            raise ValueError("duplicate executor request")
        self.requests.append(deepcopy(record))

    def append_claim(self, record: dict[str, Any]) -> None:
        _validate_claim(record)
        if any(item["claim_id"] == record["claim_id"] for item in self.claims):
            raise ValueError("duplicate executor claim")
        self.claims.append(deepcopy(record))

    def append_result(self, record: dict[str, Any]) -> None:
        _validate_result(record)
        if any(item["result_id"] == record["result_id"] for item in self.results):
            raise ValueError("duplicate executor result")
        self.results.append(deepcopy(record))

    def export_records(self) -> dict[str, list[dict[str, Any]]]:
        return {
            "requests": deepcopy(self.requests),
            "claims": deepcopy(self.claims),
            "results": deepcopy(self.results),
            "receipts": deepcopy(self.receipts),
        }

    @classmethod
    def from_records(cls, records: dict[str, Any]) -> "ExecutorLedger":
        ledger = cls()
        for record in records.get("requests", []):
            ledger.append_request(record)
        for record in records.get("claims", []):
            ledger.append_claim(record)
        for record in records.get("results", []):
            ledger.append_result(record)
        for record in records.get("receipts", []):
            _validate_receipt(record)
            if any(item["receipt_id"] == record["receipt_id"] for item in ledger.receipts):
                raise ValueError("duplicate executor receipt")
            ledger.receipts.append(deepcopy(record))
        return ledger


def make_executor_request(
    *, request_id: str, loop_id: str, round: int, correlation_id: str,
    executor_role: str, executor_kind: str, action: str,
    expected_repo: str, expected_pr: int, expected_target_head: str,
    expires_at: str, execution_mode: str = "PREPARE_ONLY",
    requires_live_model: bool = False, requires_github_write: bool = False,
) -> dict[str, Any]:
    record = {
        "schema_version": 1,
        "request_id": request_id,
        "loop_id": loop_id,
        "round": round,
        "correlation_id": correlation_id,
        "executor_role": executor_role,
        "executor_kind": executor_kind,
        "action": action,
        "execution_mode": execution_mode,
        "expected_repo": expected_repo,
        "expected_pr": expected_pr,
        "expected_target_head": expected_target_head,
        "requires_live_model": requires_live_model,
        "requires_github_write": requires_github_write,
        "retry": 0,
        "fallback": "disabled",
        "expires_at": expires_at,
        "status": "OPEN",
    }
    _validate_request(record)
    return record


def request_executor(
    ledger: ExecutorLedger, request: dict[str, Any], *,
    state: dict[str, Any] | StateMachine | None = None,
    now: datetime | None = None,
) -> ExecutorResult:
    gate = _state_gate(state, _utc(now))
    if gate:
        return gate
    try:
        ledger.append_request(request)
    except (ValueError, TypeError, KeyError) as exc:
        return ExecutorResult("UNKNOWN", str(exc))
    return ExecutorResult("REQUESTED", "executor request appended", request)


def claim_executor(
    ledger: ExecutorLedger, request_id: str, *, claim_id: str,
    executor_instance_id: str, executor_generation: int,
    capability: str, claimed_at: datetime | None = None,
    expires_at: str | None = None,
    state: dict[str, Any] | StateMachine | None = None,
) -> ExecutorResult:
    now = _utc(claimed_at)
    gate = _state_gate(state, now)
    if gate:
        return gate
    request = _request(ledger, request_id)
    try:
        if request is None:
            return ExecutorResult("UNKNOWN", "executor request not found")
        request_expiry = _parse(request["expires_at"])
        if now >= request_expiry:
            return ExecutorResult("UNKNOWN", "executor request expired")
        active = _active_claim(ledger, request_id, now)
        if active is not None:
            return ExecutorResult("BLOCKED", "active executor claim already exists", active)
        previous = [c for c in ledger.claims if c.get("request_id") == request_id]
        if previous and executor_generation <= max(c["executor_generation"] for c in previous):
            return ExecutorResult("BLOCKED", "stale executor generation")
        claim_expiry = _parse(expires_at if expires_at is not None else request["expires_at"])
        if claim_expiry <= now:
            return ExecutorResult("BLOCKED", "executor claim expires at or before claimed_at")
        if claim_expiry > request_expiry:
            return ExecutorResult("BLOCKED", "executor claim expires after request")
        record = {
            "schema_version": 1,
            "claim_id": claim_id,
            "request_id": request_id,
            "executor_instance_id": executor_instance_id,
            "executor_generation": executor_generation,
            "executor_role": request["executor_role"],
            "capability": capability,
            "claimed_at": now.isoformat(),
            "expires_at": claim_expiry.isoformat(),
            "status": "ACTIVE",
        }
        ledger.append_claim(record)
    except (ValueError, TypeError, KeyError) as exc:
        return ExecutorResult("UNKNOWN", str(exc))
    return ExecutorResult("CLAIMED", "active executor claim", record)


def submit_executor_result(
    ledger: ExecutorLedger, request_id: str, *, result_id: str,
    executor_instance_id: str, executor_generation: int,
    result_state: str, evidence_refs: Any,
    loop_id: str, round: int, correlation_id: str,
    expected_target_head: str, submitted_at: datetime | None = None,
    state: dict[str, Any] | StateMachine | None = None,
) -> ExecutorResult:
    now = _utc(submitted_at)
    gate = _state_gate(state, now)
    if gate:
        return gate
    request = _request(ledger, request_id)
    record: dict[str, Any] | None = None
    try:
        if request is None:
            return ExecutorResult("UNKNOWN", "executor request not found")
        if now >= _parse(request["expires_at"]):
            return ExecutorResult("UNKNOWN", "executor request expired")
        if any(item.get("request_id") == request_id for item in ledger.results):
            return ExecutorResult("NO-OP", "executor result already exists")
        claim = _active_claim(ledger, request_id, now)
        if claim is None:
            return ExecutorResult("UNKNOWN", "no active executor claim")
        if (claim["executor_instance_id"], claim["executor_generation"]) != (
            executor_instance_id, executor_generation
        ):
            return ExecutorResult("BLOCKED", "result executor does not own active claim")
        record = {
            "schema_version": 1,
            "result_id": result_id,
            "request_id": request_id,
            "loop_id": loop_id,
            "round": round,
            "correlation_id": correlation_id,
            "expected_target_head": expected_target_head,
            "executor_instance_id": executor_instance_id,
            "executor_generation": executor_generation,
            "result_state": result_state,
            "evidence_refs": evidence_refs,
            "submitted_at": now.isoformat(),
            "status": "AVAILABLE",
        }
        _validate_result(record)
        _match_request(request, record)
        ledger.append_result(record)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return ExecutorResult("BLOCKED", str(exc), record)
    return ExecutorResult("ACCEPTED", "valid executor result", record)


def consume_executor_result(
    ledger: ExecutorLedger, request_id: str, *, loop_id: str, round: int,
    correlation_id: str, expected_target_head: str,
    now: datetime | None = None,
    state: dict[str, Any] | StateMachine | None = None,
) -> ExecutorResult:
    at = _utc(now)
    gate = _state_gate(state, at)
    if gate:
        return gate
    request = _request(ledger, request_id)
    result = next((r for r in ledger.results if r.get("request_id") == request_id), None)
    if request is None:
        return ExecutorResult("UNKNOWN", "executor request not found")
    try:
        if at >= _parse(request["expires_at"]):
            return ExecutorResult("UNKNOWN", "executor request expired")
        if result is None:
            return ExecutorResult("UNKNOWN", "executor result missing")
        if any(
            r.get("result_id") == result.get("result_id") and r.get("state") == "CONSUMED"
            for r in ledger.receipts
        ):
            return ExecutorResult("NO-OP", "executor result already consumed")
        _validate_result(result)
        _match_context(result, loop_id, round, correlation_id, expected_target_head)
        if result["result_state"] == "PREPARED" and not result["evidence_refs"]:
            raise ValueError("prepared result requires evidence")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return ExecutorResult("UNKNOWN", str(exc), result)
    receipt = {
        "schema_version": 1,
        "receipt_id": f"executor-{result['result_id']}",
        "result_id": result["result_id"],
        "request_id": request_id,
        "state": "CONSUMED",
        "loop_id": loop_id,
        "round": round,
        "correlation_id": correlation_id,
        "expected_target_head": expected_target_head,
    }
    if any(r.get("receipt_id") == receipt["receipt_id"] for r in ledger.receipts):
        return ExecutorResult("NO-OP", "terminal executor receipt already exists", receipt)
    ledger.receipts.append(receipt)
    return ExecutorResult("VALID", "executor result consumed", result)


def _state_gate(
    state: dict[str, Any] | StateMachine | None, now: datetime
) -> ExecutorResult | None:
    if state is None:
        return None
    try:
        machine = state if isinstance(state, StateMachine) else StateMachine(state)
        if machine.mark_expired(now):
            return ExecutorResult("BLOCKED", "expired")
        reason = machine.blocked_reason(now)
        return ExecutorResult("BLOCKED", reason) if reason else None
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return ExecutorResult("UNKNOWN", str(exc))


def _request(ledger: ExecutorLedger, request_id: str) -> dict[str, Any] | None:
    return next((r for r in ledger.requests if r.get("request_id") == request_id), None)


def _active_claim(
    ledger: ExecutorLedger, request_id: str, now: datetime
) -> dict[str, Any] | None:
    for claim in reversed([
        c for c in ledger.claims
        if c.get("request_id") == request_id and c.get("status") == "ACTIVE"
    ]):
        try:
            if now < _parse(claim["expires_at"]):
                return claim
        except (ValueError, TypeError, KeyError):
            continue
    return None


def _validate_request(r: dict[str, Any]) -> None:
    required = {
        "schema_version", "request_id", "loop_id", "round", "correlation_id",
        "executor_role", "executor_kind", "action", "execution_mode",
        "expected_repo", "expected_pr", "expected_target_head",
        "requires_live_model", "requires_github_write", "retry", "fallback",
        "expires_at", "status",
    }
    if not isinstance(r, dict) or not required <= r.keys():
        raise ValueError("invalid executor request")
    if r["schema_version"] != 1 or r["status"] != "OPEN":
        raise ValueError("invalid executor request")
    if r["execution_mode"] != "PREPARE_ONLY" or r["requires_live_model"] is not False:
        raise ValueError("live executor request is not authorized")
    if r["retry"] != 0 or r["fallback"] != "disabled":
        raise ValueError("unsafe executor request policy")
    for key in (
        "request_id", "loop_id", "correlation_id", "executor_role",
        "executor_kind", "action", "expected_repo", "expected_target_head",
    ):
        if not isinstance(r[key], str) or not r[key]:
            raise ValueError(f"invalid executor request {key}")
    if isinstance(r["round"], bool) or not isinstance(r["round"], int) or r["round"] < 1:
        raise ValueError("invalid executor request round")
    if isinstance(r["expected_pr"], bool) or not isinstance(r["expected_pr"], int) or r["expected_pr"] < 1:
        raise ValueError("invalid executor target PR")
    if not isinstance(r["requires_github_write"], bool):
        raise ValueError("invalid github write flag")
    _parse(r["expires_at"])


def _validate_claim(c: dict[str, Any]) -> None:
    required = {
        "schema_version", "claim_id", "request_id", "executor_instance_id",
        "executor_generation", "executor_role", "capability",
        "claimed_at", "expires_at", "status",
    }
    if not isinstance(c, dict) or not required <= c.keys():
        raise ValueError("invalid executor claim")
    if c["schema_version"] != 1 or c["status"] != "ACTIVE":
        raise ValueError("invalid executor claim")
    for key in ("claim_id", "request_id", "executor_instance_id", "executor_role", "capability"):
        if not isinstance(c[key], str) or not c[key]:
            raise ValueError(f"invalid executor claim {key}")
    if isinstance(c["executor_generation"], bool) or not isinstance(c["executor_generation"], int) or c["executor_generation"] < 1:
        raise ValueError("invalid executor generation")
    _parse(c["claimed_at"])
    _parse(c["expires_at"])


def _validate_result(r: dict[str, Any]) -> None:
    required = {
        "schema_version", "result_id", "request_id", "loop_id", "round",
        "correlation_id", "expected_target_head", "executor_instance_id",
        "executor_generation", "result_state", "evidence_refs",
        "submitted_at", "status",
    }
    if not isinstance(r, dict) or not required <= r.keys():
        raise ValueError("invalid executor result")
    if r["schema_version"] != 1 or r["status"] != "AVAILABLE":
        raise ValueError("invalid executor result")
    if r["result_state"] not in {"PREPARED", "BLOCKED", "UNKNOWN"}:
        raise ValueError("invalid executor result state")
    if not isinstance(r["evidence_refs"], list) or any(
        not isinstance(ref, str) or not ref for ref in r["evidence_refs"]
    ):
        raise ValueError("malformed executor evidence refs")
    if isinstance(r["round"], bool) or not isinstance(r["round"], int) or r["round"] < 1:
        raise ValueError("invalid executor result round")
    if isinstance(r["executor_generation"], bool) or not isinstance(r["executor_generation"], int) or r["executor_generation"] < 1:
        raise ValueError("invalid executor result generation")
    for key in (
        "result_id", "request_id", "loop_id", "correlation_id",
        "expected_target_head", "executor_instance_id",
    ):
        if not isinstance(r[key], str) or not r[key]:
            raise ValueError(f"invalid executor result {key}")
    _parse(r["submitted_at"])


def _validate_receipt(r: dict[str, Any]) -> None:
    required = {
        "schema_version", "receipt_id", "result_id", "request_id", "state",
        "loop_id", "round", "correlation_id", "expected_target_head",
    }
    if not isinstance(r, dict) or not required <= r.keys():
        raise ValueError("invalid executor receipt")
    if r["schema_version"] != 1 or r["state"] != "CONSUMED":
        raise ValueError("invalid executor receipt")


def _match_request(request: dict[str, Any], result: dict[str, Any]) -> None:
    _match_context(
        result, request["loop_id"], request["round"],
        request["correlation_id"], request["expected_target_head"],
    )


def _match_context(
    record: dict[str, Any], loop_id: str, round: int,
    correlation_id: str, target_head: str,
) -> None:
    if (
        record["loop_id"], record["round"], record["correlation_id"],
        record["expected_target_head"],
    ) != (loop_id, round, correlation_id, target_head):
        raise ValueError("executor loop, round, correlation, or target head mismatch")
