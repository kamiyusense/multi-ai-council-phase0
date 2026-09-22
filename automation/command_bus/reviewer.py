"""Exchangeable reviewer-role protocol for the durable command bus.

This module deliberately has no Chat/thread identifier.  Requests, claims,
responses, and consumption receipts are append-only records in the ledger.
The in-memory implementation is a deterministic fixture for the GitHub
append-only representation; it performs no network, model, or provider work.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any


def _utc(value: datetime | None) -> datetime:
    return value or datetime.now(timezone.utc)


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


@dataclass(frozen=True)
class ReviewResult:
    status: str
    reason: str
    record: dict[str, Any] | None = None


class ReviewerLedger:
    """Append-only reviewer records plus explicit terminal receipts."""

    def __init__(self) -> None:
        self.requests: list[dict[str, Any]] = []
        self.claims: list[dict[str, Any]] = []
        self.responses: list[dict[str, Any]] = []
        self.receipts: list[dict[str, Any]] = []

    def append_request(self, request: dict[str, Any]) -> None:
        _validate_request(request)
        if any(r["request_id"] == request["request_id"] for r in self.requests):
            raise ValueError("duplicate request")
        self.requests.append(dict(request))

    def append_claim(self, claim: dict[str, Any]) -> None:
        _validate_claim(claim)
        if any(c["claim_id"] == claim["claim_id"] for c in self.claims):
            raise ValueError("duplicate claim")
        self.claims.append(dict(claim))

    def append_response(self, response: dict[str, Any]) -> None:
        _validate_response(response)
        if any(r["response_id"] == response["response_id"] for r in self.responses):
            raise ValueError("duplicate response")
        self.responses.append(dict(response))


def make_request(*, request_id: str, loop_id: str, round: int,
                 correlation_id: str, expected_target_head: str,
                 expires_at: str) -> dict[str, Any]:
    request = {"schema_version": 1, "request_id": request_id,
               "loop_id": loop_id, "round": round,
               "correlation_id": correlation_id,
               "expected_target_head": expected_target_head,
               "expires_at": expires_at, "status": "OPEN"}
    _validate_request(request)
    return request


def claim_request(ledger: ReviewerLedger, request_id: str, *, claim_id: str,
                  reviewer_instance_id: str, reviewer_generation: int,
                  role: str = "reviewer", capability: str = "review",
                  claimed_at: datetime | None = None,
                  expires_at: str | None = None) -> ReviewResult:
    request = _request(ledger, request_id)
    if request is None:
        return ReviewResult("UNKNOWN", "request not found")
    now = _utc(claimed_at)
    if now >= _parse(request["expires_at"]):
        return ReviewResult("UNKNOWN", "request expired")
    active = _active_claim(ledger, request_id, now)
    if active is not None:
        return ReviewResult("BLOCKED", "active claim already exists", active)
    previous = [c for c in ledger.claims if c["request_id"] == request_id]
    if previous and reviewer_generation <= max(c["reviewer_generation"] for c in previous):
        return ReviewResult("BLOCKED", "stale reviewer generation")
    claim = {"schema_version": 1, "claim_id": claim_id,
             "request_id": request_id, "reviewer_instance_id": reviewer_instance_id,
             "reviewer_generation": reviewer_generation, "role": role,
             "capability": capability, "claimed_at": now.isoformat(),
             "expires_at": expires_at or request["expires_at"], "status": "ACTIVE"}
    try:
        ledger.append_claim(claim)
    except ValueError as exc:
        return ReviewResult("UNKNOWN", str(exc))
    return ReviewResult("CLAIMED", "active reviewer claim", claim)


def submit_response(ledger: ReviewerLedger, request_id: str, *, response_id: str,
                    reviewer_instance_id: str, reviewer_generation: int,
                    decision: str, evidence_refs: list[str],
                    loop_id: str, round: int, correlation_id: str,
                    expected_target_head: str,
                    submitted_at: datetime | None = None) -> ReviewResult:
    request = _request(ledger, request_id)
    if request is None:
        return ReviewResult("UNKNOWN", "request not found")
    if any(r["request_id"] == request_id for r in ledger.responses):
        return ReviewResult("NO-OP", "response already exists")
    claim = _active_claim(ledger, request_id, _utc(submitted_at))
    if claim is None:
        return ReviewResult("UNKNOWN", "no active claim")
    if (claim["reviewer_instance_id"], claim["reviewer_generation"]) != (reviewer_instance_id, reviewer_generation):
        return ReviewResult("BLOCKED", "response reviewer does not own active claim")
    response = {"schema_version": 1, "response_id": response_id,
                "request_id": request_id, "loop_id": loop_id, "round": round,
                "correlation_id": correlation_id,
                "expected_target_head": expected_target_head,
                "reviewer_instance_id": reviewer_instance_id,
                "reviewer_generation": reviewer_generation,
                "decision": decision, "evidence_refs": list(evidence_refs),
                "submitted_at": _utc(submitted_at).isoformat(), "status": "AVAILABLE"}
    try:
        _validate_response(response)
        _match_request(request, response)
        ledger.append_response(response)
    except ValueError as exc:
        return ReviewResult("BLOCKED", str(exc), response)
    return ReviewResult("ACCEPTED", "valid review response", response)


def consume_response(ledger: ReviewerLedger, request_id: str, *, loop_id: str,
                     round: int, correlation_id: str,
                     expected_target_head: str) -> ReviewResult:
    response = next((r for r in ledger.responses if r["request_id"] == request_id), None)
    if response is None:
        return ReviewResult("UNKNOWN", "response missing")
    if any(r.get("response_id") == response["response_id"] and r["state"] == "CONSUMED" for r in ledger.receipts):
        return ReviewResult("NO-OP", "response receipt already consumed")
    try:
        _match_response(response, loop_id, round, correlation_id, expected_target_head)
        if not response["decision"].strip() or not response["evidence_refs"]:
            raise ValueError("empty or unverifiable response")
    except ValueError as exc:
        return ReviewResult("UNKNOWN", str(exc), response)
    receipt = {"schema_version": 1, "receipt_id": f"review-{response['response_id']}",
               "response_id": response["response_id"], "request_id": request_id,
               "state": "CONSUMED", "loop_id": loop_id, "round": round,
               "correlation_id": correlation_id,
               "expected_target_head": expected_target_head}
    if any(r["receipt_id"] == receipt["receipt_id"] for r in ledger.receipts):
        return ReviewResult("NO-OP", "terminal receipt already exists", receipt)
    ledger.receipts.append(receipt)
    return ReviewResult("VALID", "response consumed", response)


def _request(ledger: ReviewerLedger, request_id: str) -> dict[str, Any] | None:
    return next((r for r in ledger.requests if r["request_id"] == request_id), None)


def _active_claim(ledger: ReviewerLedger, request_id: str, now: datetime) -> dict[str, Any] | None:
    claims = [c for c in ledger.claims if c["request_id"] == request_id and c["status"] == "ACTIVE"]
    return next((c for c in reversed(claims) if now < _parse(c["expires_at"])), None)


def _validate_request(r: dict[str, Any]) -> None:
    required = {"schema_version", "request_id", "loop_id", "round", "correlation_id", "expected_target_head", "expires_at", "status"}
    if not required <= r.keys() or r["schema_version"] != 1 or r["status"] != "OPEN" or r["round"] < 1:
        raise ValueError("invalid review request")
    _parse(r["expires_at"])


def _validate_claim(c: dict[str, Any]) -> None:
    required = {"schema_version", "claim_id", "request_id", "reviewer_instance_id", "reviewer_generation", "role", "capability", "claimed_at", "expires_at", "status"}
    if not required <= c.keys() or c["schema_version"] != 1 or c["status"] != "ACTIVE" or c["reviewer_generation"] < 1:
        raise ValueError("invalid reviewer claim")
    _parse(c["claimed_at"]); _parse(c["expires_at"])


def _validate_response(r: dict[str, Any]) -> None:
    required = {"schema_version", "response_id", "request_id", "loop_id", "round", "correlation_id", "expected_target_head", "reviewer_instance_id", "reviewer_generation", "decision", "evidence_refs", "submitted_at", "status"}
    if not required <= r.keys() or r["schema_version"] != 1 or r["status"] != "AVAILABLE":
        raise ValueError("invalid review response")
    if not isinstance(r["evidence_refs"], list):
        raise ValueError("invalid evidence refs")


def _match_request(request: dict[str, Any], response: dict[str, Any]) -> None:
    _match_response(response, request["loop_id"], request["round"], request["correlation_id"], request["expected_target_head"])


def _match_response(response: dict[str, Any], loop_id: str, round: int, correlation_id: str, target_head: str) -> None:
    if (response["loop_id"], response["round"], response["correlation_id"], response["expected_target_head"]) != (loop_id, round, correlation_id, target_head):
        raise ValueError("review response correlation, round, loop, or target head mismatch")
