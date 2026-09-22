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
    expires_at: str, expected_target_tree: str = "UNKNOWN",
    execution_mode: str = "PREPARE_ONLY",
    requires_live_model: bool = False, requires_github_write: bool = False,
    target_role: str = "executor", capability: str = "prepare-only",
    objective: str = "prepare implementation artifact",
    input_refs: Any = None, evidence_refs: Any = None,
    allowed_actions: Any = None, prohibited_actions: Any = None,
    requires_user_approval: bool = False,
    approval_state: str = "NOT_REQUIRED",
    live_start_permitted: bool = False,
    requires_clean_workspace: bool = True,
    workspace_integrity_profile: str = "TREE_IDENTITY_V1",
    path_policy: Any = None,
    mutation_lease_ttl_seconds: int = 900,
) -> dict[str, Any]:
    record = {
        "schema_version": 1,
        "request_id": request_id,
        "execution_request_id": request_id,
        "loop_id": loop_id,
        "round": round,
        "correlation_id": correlation_id,
        "target_role": target_role,
        "executor_role": executor_role,
        "executor_kind": executor_kind,
        "capability": capability,
        "objective": objective,
        "input_refs": list(input_refs or []),
        "evidence_refs": list(evidence_refs or []),
        "allowed_actions": list(allowed_actions or ["PREPARE_ARTIFACT"]),
        "prohibited_actions": list(prohibited_actions or ["LIVE_START", "EXTERNAL_SEND"]),
        "requires_user_approval": requires_user_approval,
        "approval_state": approval_state,
        "action": action,
        "execution_mode": execution_mode,
        "live_start_permitted": live_start_permitted,
        "expected_repo": expected_repo,
        "expected_pr": expected_pr,
        "expected_target_head": expected_target_head,
        "expected_target_tree": expected_target_tree,
        "requires_clean_workspace": requires_clean_workspace,
        "workspace_integrity_profile": workspace_integrity_profile,
        "path_policy": deepcopy(list(path_policy or [])),
        "mutation_lease_ttl_seconds": mutation_lease_ttl_seconds,
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
        if request.get("requires_user_approval") and request.get("approval_state") != "APPROVED":
            return ExecutorResult("BLOCKED", "executor request requires user approval")
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
    workspace_attestation_id: str | None = None,
    workspace_path_fingerprint: str | None = None,
    observed_head: str | None = None,
    observed_tree: str | None = None,
    observed_index_tree: str | None = None,
) -> ExecutorResult:
    now = _utc(claimed_at)
    gate = _state_gate(state, now)
    if gate:
        return gate
    request = _request(ledger, request_id)
    try:
        if request is None:
            return ExecutorResult("UNKNOWN", "executor request not found")
        if request.get("requires_user_approval") and request.get("approval_state") != "APPROVED":
            return ExecutorResult("BLOCKED", "executor request requires user approval")
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
            "execution_claim_id": claim_id,
            "request_id": request_id,
            "execution_request_id": request_id,
            "executor_instance_id": executor_instance_id,
            "executor_generation": executor_generation,
            "executor_role": request["executor_role"],
            "capability": capability,
            "claimed_at": now.isoformat(),
            "expires_at": claim_expiry.isoformat(),
            "status": "ACTIVE",
        }
        integrity_values = {
            "workspace_attestation_id": workspace_attestation_id,
            "workspace_path_fingerprint": workspace_path_fingerprint,
            "observed_head": observed_head,
            "observed_tree": observed_tree,
            "observed_index_tree": observed_index_tree,
        }
        if any(value is not None for value in integrity_values.values()):
            if any(not isinstance(value, str) or not value for value in integrity_values.values()):
                raise ValueError("incomplete workspace attestation claim")
            record.update(integrity_values)
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
    artifact_refs: Any = None,
    expected_target_tree: str | None = None,
    workspace_attestation_ref: str | None = None,
    commit_attestation_ref: str | None = None,
    mutation_lease_id: str | None = None,
    mutation_started: bool = False,
    target_head_revalidated: bool = False,
    push_attempted: bool = False,
    remote_readback_verified: bool = False,
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
            "execution_result_id": result_id,
            "request_id": request_id,
            "execution_request_id": request_id,
            "loop_id": loop_id,
            "round": round,
            "correlation_id": correlation_id,
            "expected_target_head": expected_target_head,
            "executor_instance_id": executor_instance_id,
            "executor_generation": executor_generation,
            "result_state": result_state,
            "artifact_refs": list(artifact_refs or []),
            "evidence_refs": evidence_refs,
            "model_executed": False,
            "external_send_attempted": False,
            "retry_count": 0,
            "fallback_used": False,
            "live_started": False,
            "submitted_at": now.isoformat(),
            "status": "AVAILABLE",
        }
        effective_target_tree = (
            expected_target_tree
            if expected_target_tree is not None
            else request.get("expected_target_tree")
        )
        integrity_result = {
            "expected_target_tree": effective_target_tree,
            "workspace_attestation_ref": workspace_attestation_ref,
            "commit_attestation_ref": commit_attestation_ref,
            "mutation_lease_id": mutation_lease_id,
        }
        if any(value is not None for value in integrity_result.values()):
            if effective_target_tree is not None:
                record["expected_target_tree"] = effective_target_tree
            refs = {
                "workspace_attestation_ref": workspace_attestation_ref,
                "commit_attestation_ref": commit_attestation_ref,
                "mutation_lease_id": mutation_lease_id,
            }
            if any(value is not None for value in refs.values()):
                if any(not isinstance(value, str) or not value for value in refs.values()):
                    raise ValueError("incomplete executor integrity result")
                record.update(refs)
        record.update({
            "mutation_started": bool(mutation_started),
            "target_head_revalidated": bool(target_head_revalidated),
            "push_attempted": bool(push_attempted),
            "remote_readback_verified": bool(remote_readback_verified),
        })
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
        "execution_receipt_id": f"executor-{result['result_id']}",
        "result_id": result["result_id"],
        "execution_result_id": result["result_id"],
        "request_id": request_id,
        "execution_request_id": request_id,
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
        "execution_request_id", "target_role", "executor_role", "executor_kind",
        "capability", "objective", "input_refs", "evidence_refs",
        "allowed_actions", "prohibited_actions", "requires_user_approval",
        "approval_state", "action", "execution_mode", "live_start_permitted",
        "expected_repo", "expected_pr", "expected_target_head",
        "requires_live_model", "requires_github_write", "retry", "fallback",
        "expires_at", "status",
    }
    if not isinstance(r, dict) or not required <= r.keys():
        raise ValueError("invalid executor request")
    if r["schema_version"] != 1 or r["status"] != "OPEN":
        raise ValueError("invalid executor request")
    if (
        r["execution_mode"] != "PREPARE_ONLY"
        or r["requires_live_model"] is not False
        or r["live_start_permitted"] is not False
    ):
        raise ValueError("live executor request is not authorized")
    if r["target_role"] != "executor" or r["execution_request_id"] != r["request_id"]:
        raise ValueError("invalid executor target or request alias")
    if not isinstance(r["requires_user_approval"], bool):
        raise ValueError("invalid executor approval requirement")
    if r["approval_state"] not in {"NOT_REQUIRED", "PENDING", "APPROVED", "DENIED"}:
        raise ValueError("invalid executor approval state")
    if not r["requires_user_approval"] and r["approval_state"] != "NOT_REQUIRED":
        raise ValueError("executor approval state mismatch")
    if r["requires_user_approval"] and r["approval_state"] == "NOT_REQUIRED":
        raise ValueError("executor approval state mismatch")
    if r["retry"] != 0 or r["fallback"] != "disabled":
        raise ValueError("unsafe executor request policy")
    for key in (
        "request_id", "loop_id", "correlation_id", "executor_role",
        "executor_kind", "capability", "objective", "action", "expected_repo",
        "expected_target_head",
    ):
        if not isinstance(r[key], str) or not r[key]:
            raise ValueError(f"invalid executor request {key}")
    if isinstance(r["round"], bool) or not isinstance(r["round"], int) or r["round"] < 1:
        raise ValueError("invalid executor request round")
    if isinstance(r["expected_pr"], bool) or not isinstance(r["expected_pr"], int) or r["expected_pr"] < 1:
        raise ValueError("invalid executor target PR")
    if not isinstance(r["requires_github_write"], bool):
        raise ValueError("invalid github write flag")
    for key in ("input_refs", "evidence_refs", "allowed_actions", "prohibited_actions"):
        if not isinstance(r[key], list) or any(not isinstance(v, str) or not v for v in r[key]):
            raise ValueError(f"invalid executor request {key}")
    if not r["allowed_actions"] or not r["prohibited_actions"]:
        raise ValueError("executor action boundaries are required")
    integrity_fields = {
        "expected_target_tree", "requires_clean_workspace",
        "workspace_integrity_profile", "path_policy",
        "mutation_lease_ttl_seconds",
    }
    present_integrity = integrity_fields & r.keys()
    if present_integrity and present_integrity != integrity_fields:
        raise ValueError("incomplete executor workspace integrity contract")
    if present_integrity:
        if not isinstance(r["expected_target_tree"], str) or not r["expected_target_tree"]:
            raise ValueError("invalid expected target tree")
        if r["requires_clean_workspace"] is not True:
            raise ValueError("mutable executor requires clean workspace")
        if r["workspace_integrity_profile"] != "TREE_IDENTITY_V1":
            raise ValueError("unsupported workspace integrity profile")
        if not isinstance(r["path_policy"], list):
            raise ValueError("invalid executor path policy")
        if (
            isinstance(r["mutation_lease_ttl_seconds"], bool)
            or not isinstance(r["mutation_lease_ttl_seconds"], int)
            or r["mutation_lease_ttl_seconds"] <= 0
        ):
            raise ValueError("invalid mutation lease ttl")
    _parse(r["expires_at"])


def _validate_claim(c: dict[str, Any]) -> None:
    required = {
        "schema_version", "claim_id", "execution_claim_id", "request_id",
        "execution_request_id", "executor_instance_id",
        "executor_generation", "executor_role", "capability",
        "claimed_at", "expires_at", "status",
    }
    if not isinstance(c, dict) or not required <= c.keys():
        raise ValueError("invalid executor claim")
    if c["schema_version"] != 1 or c["status"] != "ACTIVE":
        raise ValueError("invalid executor claim")
    if c["execution_claim_id"] != c["claim_id"] or c["execution_request_id"] != c["request_id"]:
        raise ValueError("invalid executor claim alias")
    for key in ("claim_id", "request_id", "executor_instance_id", "executor_role", "capability"):
        if not isinstance(c[key], str) or not c[key]:
            raise ValueError(f"invalid executor claim {key}")
    if isinstance(c["executor_generation"], bool) or not isinstance(c["executor_generation"], int) or c["executor_generation"] < 1:
        raise ValueError("invalid executor generation")
    integrity_fields = {
        "workspace_attestation_id", "workspace_path_fingerprint",
        "observed_head", "observed_tree", "observed_index_tree",
    }
    present_integrity = integrity_fields & c.keys()
    if present_integrity and present_integrity != integrity_fields:
        raise ValueError("incomplete workspace attestation claim")
    if present_integrity and any(not isinstance(c[key], str) or not c[key] for key in integrity_fields):
        raise ValueError("invalid workspace attestation claim")
    _parse(c["claimed_at"])
    _parse(c["expires_at"])


def _validate_result(r: dict[str, Any]) -> None:
    required = {
        "schema_version", "result_id", "execution_result_id", "request_id",
        "execution_request_id", "loop_id", "round",
        "correlation_id", "expected_target_head", "executor_instance_id",
        "executor_generation", "result_state", "artifact_refs", "evidence_refs",
        "model_executed", "external_send_attempted", "retry_count",
        "fallback_used", "live_started",
        "submitted_at", "status",
    }
    if not isinstance(r, dict) or not required <= r.keys():
        raise ValueError("invalid executor result")
    if r["schema_version"] != 1 or r["status"] != "AVAILABLE":
        raise ValueError("invalid executor result")
    if r["execution_result_id"] != r["result_id"] or r["execution_request_id"] != r["request_id"]:
        raise ValueError("invalid executor result alias")
    if (
        r["model_executed"] is not False
        or r["external_send_attempted"] is not False
        or r["retry_count"] != 0
        or r["fallback_used"] is not False
        or r["live_started"] is not False
    ):
        raise ValueError("unsafe executor result")
    if r["result_state"] not in {"PREPARED", "BLOCKED", "UNKNOWN"}:
        raise ValueError("invalid executor result state")
    if "expected_target_tree" in r:
        if not isinstance(r["expected_target_tree"], str) or not r["expected_target_tree"]:
            raise ValueError("invalid executor expected target tree")
    attestation_fields = {
        "workspace_attestation_ref", "commit_attestation_ref", "mutation_lease_id",
    }
    present_attestation = attestation_fields & r.keys()
    if present_attestation and present_attestation != attestation_fields:
        raise ValueError("incomplete executor integrity result")
    if present_attestation and any(
        not isinstance(r[key], str) or not r[key] for key in attestation_fields
    ):
        raise ValueError("invalid executor integrity result")
    for key in (
        "mutation_started", "target_head_revalidated",
        "push_attempted", "remote_readback_verified",
    ):
        if key in r and not isinstance(r[key], bool):
            raise ValueError(f"invalid executor result {key}")
    if not isinstance(r["evidence_refs"], list) or any(
        not isinstance(ref, str) or not ref for ref in r["evidence_refs"]
    ):
        raise ValueError("malformed executor evidence refs")
    if not isinstance(r["artifact_refs"], list) or any(
        not isinstance(ref, str) or not ref for ref in r["artifact_refs"]
    ):
        raise ValueError("malformed executor artifact refs")
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
        "schema_version", "receipt_id", "execution_receipt_id", "result_id",
        "execution_result_id", "request_id", "execution_request_id", "state",
        "loop_id", "round", "correlation_id", "expected_target_head",
    }
    if not isinstance(r, dict) or not required <= r.keys():
        raise ValueError("invalid executor receipt")
    if r["schema_version"] != 1 or r["state"] != "CONSUMED":
        raise ValueError("invalid executor receipt")
    if (
        r["execution_receipt_id"] != r["receipt_id"]
        or r["execution_result_id"] != r["result_id"]
        or r["execution_request_id"] != r["request_id"]
    ):
        raise ValueError("invalid executor receipt alias")


def _match_request(request: dict[str, Any], result: dict[str, Any]) -> None:
    _match_context(
        result, request["loop_id"], request["round"],
        request["correlation_id"], request["expected_target_head"],
    )
    if "expected_target_tree" in request:
        if result.get("expected_target_tree") != request["expected_target_tree"]:
            raise ValueError("executor target tree mismatch")


def _match_context(
    record: dict[str, Any], loop_id: str, round: int,
    correlation_id: str, target_head: str,
) -> None:
    if (
        record["loop_id"], record["round"], record["correlation_id"],
        record["expected_target_head"],
    ) != (loop_id, round, correlation_id, target_head):
        raise ValueError("executor loop, round, correlation, or target head mismatch")
