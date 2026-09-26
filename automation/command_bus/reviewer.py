"""Exchangeable reviewer-role protocol for the durable command bus.

The protocol contains no Chat or thread identifier. Records are append-only;
the in-memory ledger is a deterministic stand-in for GitHub records and does
not perform network, model, provider, or retry work.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from .state_machine import StateMachine


DURABLE_REVIEW_V2 = "DURABLE_REVIEW_V2"


def _utc(value: datetime | None) -> datetime:
    return value or datetime.now(timezone.utc)


def _parse(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
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
        self.requests.append(deepcopy(request))

    def append_claim(self, claim: dict[str, Any]) -> None:
        _validate_claim(claim)
        if any(c["claim_id"] == claim["claim_id"] for c in self.claims):
            raise ValueError("duplicate claim")
        self.claims.append(deepcopy(claim))

    def append_response(self, response: dict[str, Any]) -> None:
        _validate_response(response)
        if any(r["response_id"] == response["response_id"] for r in self.responses):
            raise ValueError("duplicate response")
        self.responses.append(deepcopy(response))

    def export_records(self) -> dict[str, list[dict[str, Any]]]:
        return {"requests": deepcopy(self.requests), "claims": deepcopy(self.claims),
                "responses": deepcopy(self.responses), "receipts": deepcopy(self.receipts)}

    @classmethod
    def from_records(cls, records: dict[str, Any]) -> "ReviewerLedger":
        ledger = cls()
        for request in records.get("requests", []):
            ledger.append_request(request)
        for claim in records.get("claims", []):
            ledger.append_claim(claim)
        for response in records.get("responses", []):
            ledger.append_response(response)
        for receipt in records.get("receipts", []):
            _validate_receipt(receipt)
            ledger.receipts.append(deepcopy(receipt))
        return ledger


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


def make_request_v2(
    *, request_id: str, loop_id: str, round: int, correlation_id: str,
    expected_target_head: str, expected_target_tree: str,
    reviewer_role: str, review_kind: str, evidence_refs: list[str],
    allowed_decisions: list[str], expires_at: str,
) -> dict[str, Any]:
    request = make_request(
        request_id=request_id, loop_id=loop_id, round=round,
        correlation_id=correlation_id,
        expected_target_head=expected_target_head, expires_at=expires_at,
    )
    request.update({
        "review_profile": DURABLE_REVIEW_V2,
        "expected_target_tree": expected_target_tree,
        "reviewer_role": reviewer_role,
        "review_kind": review_kind,
        "evidence_refs": list(evidence_refs),
        "allowed_decisions": list(allowed_decisions),
        "retry": 0,
        "fallback": "disabled",
    })
    _validate_request(request)
    return request


def validate_review_request(request: dict[str, Any]) -> None:
    """Validate a durable review request without mutating a ledger."""
    _validate_request(request)


def request_review(ledger: ReviewerLedger, request: dict[str, Any], *,
                   state: dict[str, Any] | StateMachine | None = None,
                   now: datetime | None = None) -> ReviewResult:
    gate = _state_gate(state, _utc(now))
    if gate:
        return gate
    try:
        ledger.append_request(request)
    except (ValueError, TypeError, KeyError) as exc:
        return ReviewResult("UNKNOWN", str(exc))
    return ReviewResult("REQUESTED", "review request appended", request)


def claim_request(ledger: ReviewerLedger, request_id: str, *, claim_id: str,
                  reviewer_instance_id: str, reviewer_generation: int,
                  role: str = "reviewer", capability: str = "review",
                  claimed_at: datetime | None = None,
                  expires_at: str | None = None,
                  state: dict[str, Any] | StateMachine | None = None) -> ReviewResult:
    now = _utc(claimed_at)
    gate = _state_gate(state, now)
    if gate:
        return gate
    request = _request(ledger, request_id)
    try:
        if request is None:
            return ReviewResult("UNKNOWN", "request not found")
        request_expiry = _parse(request["expires_at"])
        if now >= request_expiry:
            return ReviewResult("UNKNOWN", "request expired")
        if request.get("review_profile") == DURABLE_REVIEW_V2 and role != request["reviewer_role"]:
            return ReviewResult("BLOCKED", "reviewer role does not match request")
        active = _active_claim(ledger, request_id, now)
        if active is not None:
            return ReviewResult("BLOCKED", "active claim already exists", active)
        previous = [c for c in ledger.claims if isinstance(c, dict) and c.get("request_id") == request_id]
        if previous and reviewer_generation <= max(c["reviewer_generation"] for c in previous):
            return ReviewResult("BLOCKED", "stale reviewer generation")
        claim_expiry = _parse(expires_at if expires_at is not None else request["expires_at"])
        if claim_expiry <= now:
            return ReviewResult("BLOCKED", "claim expires at or before claimed_at")
        if claim_expiry > request_expiry:
            return ReviewResult("BLOCKED", "claim expires after review request")
        claim = {"schema_version": 1, "claim_id": claim_id,
                 "request_id": request_id, "reviewer_instance_id": reviewer_instance_id,
                 "reviewer_generation": reviewer_generation, "role": role,
                 "capability": capability, "claimed_at": now.isoformat(),
                 "expires_at": claim_expiry.isoformat(), "status": "ACTIVE"}
        ledger.append_claim(claim)
    except (ValueError, TypeError, KeyError) as exc:
        return ReviewResult("UNKNOWN", str(exc))
    return ReviewResult("CLAIMED", "active reviewer claim", claim)


def submit_response(ledger: ReviewerLedger, request_id: str, *, response_id: str,
                    reviewer_instance_id: str, reviewer_generation: int,
                    decision: Any, evidence_refs: Any,
                    loop_id: str, round: int, correlation_id: str,
                    expected_target_head: str,
                    submitted_at: datetime | None = None,
                    state: dict[str, Any] | StateMachine | None = None,
                    expected_target_tree: str | None = None,
                    rationale_summary: str | None = None,
                    next_command_proposal: dict[str, Any] | None = None,
                    model_route_evidence: dict[str, Any] | None = None) -> ReviewResult:
    now = _utc(submitted_at)
    gate = _state_gate(state, now)
    if gate:
        return gate
    request = _request(ledger, request_id)
    response: dict[str, Any] | None = None
    try:
        if request is None:
            return ReviewResult("UNKNOWN", "request not found")
        if now >= _parse(request["expires_at"]):
            return ReviewResult("UNKNOWN", "review request expired")
        if any(isinstance(r, dict) and r.get("request_id") == request_id for r in ledger.responses):
            return ReviewResult("NO-OP", "response already exists")
        claim = _active_claim(ledger, request_id, now)
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
                    "decision": decision, "evidence_refs": evidence_refs,
                    "submitted_at": now.isoformat(), "status": "AVAILABLE"}
        if request.get("review_profile") == DURABLE_REVIEW_V2:
            if decision not in request["allowed_decisions"]:
                raise ValueError("review decision not allowed by request")
            if not isinstance(evidence_refs, list) or not evidence_refs:
                raise ValueError("durable review v2 response requires evidence")
            response.update({
                "review_profile": DURABLE_REVIEW_V2,
                "expected_target_tree": expected_target_tree,
                "reviewer_role": request["reviewer_role"],
                "review_kind": request["review_kind"],
                "rationale_summary": rationale_summary,
                "next_command_proposal": next_command_proposal,
                "model_route_evidence": model_route_evidence,
            })
        _validate_response(response)
        _match_request(request, response)
        ledger.append_response(response)
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return ReviewResult("BLOCKED", str(exc), response)
    return ReviewResult("ACCEPTED", "valid review response", response)


def consume_response(ledger: ReviewerLedger, request_id: str, *, loop_id: str,
                     round: int, correlation_id: str,
                     expected_target_head: str,
                     now: datetime | None = None,
                     state: dict[str, Any] | StateMachine | None = None,
                     expected_target_tree: str | None = None) -> ReviewResult:
    at = _utc(now)
    gate = _state_gate(state, at)
    if gate:
        return gate
    response = next((r for r in ledger.responses if isinstance(r, dict) and r.get("request_id") == request_id), None)
    request = _request(ledger, request_id)
    if request is None:
        return ReviewResult("UNKNOWN", "request not found")
    try:
        if at >= _parse(request["expires_at"]):
            return ReviewResult("UNKNOWN", "review request expired")
        if response is None:
            return ReviewResult("UNKNOWN", "response missing")
        if any(isinstance(r, dict) and r.get("response_id") == response.get("response_id") and r.get("state") == "CONSUMED" for r in ledger.receipts):
            return ReviewResult("NO-OP", "response receipt already consumed")
        _validate_response(response)
        _match_response(response, loop_id, round, correlation_id, expected_target_head)
        _match_request(request, response)
        if request.get("review_profile") == DURABLE_REVIEW_V2:
            if expected_target_tree != request["expected_target_tree"]:
                raise ValueError("review consume target tree mismatch")
            if response["decision"] not in request["allowed_decisions"]:
                raise ValueError("review decision not allowed by request")
        if not response["decision"].strip() or not response["evidence_refs"]:
            raise ValueError("empty or unverifiable response")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return ReviewResult("UNKNOWN", str(exc), response)
    receipt = {"schema_version": 1, "receipt_id": f"review-{response['response_id']}",
               "response_id": response["response_id"], "request_id": request_id,
               "state": "CONSUMED", "loop_id": loop_id, "round": round,
               "correlation_id": correlation_id,
               "expected_target_head": expected_target_head}
    if request.get("review_profile") == DURABLE_REVIEW_V2:
        receipt["review_profile"] = DURABLE_REVIEW_V2
        receipt["expected_target_tree"] = request["expected_target_tree"]
    if any(isinstance(r, dict) and r.get("receipt_id") == receipt["receipt_id"] for r in ledger.receipts):
        return ReviewResult("NO-OP", "terminal receipt already exists", receipt)
    ledger.receipts.append(receipt)
    return ReviewResult("VALID", "response consumed", response)


def _state_gate(state: dict[str, Any] | StateMachine | None, now: datetime) -> ReviewResult | None:
    if state is None:
        return None
    try:
        machine = state if isinstance(state, StateMachine) else StateMachine(state)
        if machine.mark_expired(now):
            return ReviewResult("BLOCKED", "expired")
        reason = machine.blocked_reason(now)
        return ReviewResult("BLOCKED", reason) if reason else None
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return ReviewResult("UNKNOWN", str(exc))


def _request(ledger: ReviewerLedger, request_id: str) -> dict[str, Any] | None:
    return next((r for r in ledger.requests if isinstance(r, dict) and r.get("request_id") == request_id), None)


def _active_claim(ledger: ReviewerLedger, request_id: str, now: datetime) -> dict[str, Any] | None:
    claims = [c for c in ledger.claims if isinstance(c, dict) and c.get("request_id") == request_id and c.get("status") == "ACTIVE"]
    for claim in reversed(claims):
        try:
            if now < _parse(claim["expires_at"]):
                return claim
        except (ValueError, TypeError, KeyError):
            continue
    return None


def _validate_request(r: dict[str, Any]) -> None:
    required = {"schema_version", "request_id", "loop_id", "round", "correlation_id", "expected_target_head", "expires_at", "status"}
    if not isinstance(r, dict) or not required <= r.keys() or r["schema_version"] != 1 or r["status"] != "OPEN":
        raise ValueError("invalid review request")
    if not all(isinstance(r[k], str) and r[k] for k in ("request_id", "loop_id", "correlation_id", "expected_target_head")):
        raise ValueError("invalid review request identity")
    if isinstance(r["round"], bool) or not isinstance(r["round"], int) or r["round"] < 1:
        raise ValueError("invalid review request round")
    _parse(r["expires_at"])
    if r.get("review_profile") == DURABLE_REVIEW_V2:
        required_v2 = {
            "expected_target_tree", "reviewer_role", "review_kind",
            "evidence_refs", "allowed_decisions", "retry", "fallback",
        }
        if not required_v2 <= r.keys():
            raise ValueError("incomplete durable review v2 request")
        for key in ("expected_target_tree", "reviewer_role", "review_kind"):
            if not isinstance(r[key], str) or not r[key]:
                raise ValueError(f"invalid durable review v2 {key}")
        if (
            not isinstance(r["evidence_refs"], list) or not r["evidence_refs"]
            or any(not isinstance(x, str) or not x for x in r["evidence_refs"])
        ):
            raise ValueError("invalid durable review v2 evidence refs")
        if (
            not isinstance(r["allowed_decisions"], list) or not r["allowed_decisions"]
            or len(r["allowed_decisions"]) != len(set(r["allowed_decisions"]))
            or any(not isinstance(x, str) or not x for x in r["allowed_decisions"])
        ):
            raise ValueError("invalid durable review v2 allowed decisions")
        if r["retry"] != 0 or r["fallback"] != "disabled":
            raise ValueError("unsafe durable review retry/fallback policy")
        if _contains_session_identity(r):
            raise ValueError("session identity is not a correctness input")


def _validate_claim(c: dict[str, Any]) -> None:
    required = {"schema_version", "claim_id", "request_id", "reviewer_instance_id", "reviewer_generation", "role", "capability", "claimed_at", "expires_at", "status"}
    if not isinstance(c, dict) or not required <= c.keys() or c["schema_version"] != 1 or c["status"] != "ACTIVE":
        raise ValueError("invalid reviewer claim")
    if isinstance(c["reviewer_generation"], bool) or not isinstance(c["reviewer_generation"], int) or c["reviewer_generation"] < 1:
        raise ValueError("invalid reviewer generation")
    _parse(c["claimed_at"]); _parse(c["expires_at"])


def _validate_response(r: dict[str, Any]) -> None:
    required = {"schema_version", "response_id", "request_id", "loop_id", "round", "correlation_id", "expected_target_head", "reviewer_instance_id", "reviewer_generation", "decision", "evidence_refs", "submitted_at", "status"}
    if not isinstance(r, dict) or not required <= r.keys() or r["schema_version"] != 1 or r["status"] != "AVAILABLE":
        raise ValueError("invalid review response")
    if not isinstance(r["decision"], str) or not isinstance(r["evidence_refs"], list):
        raise ValueError("malformed review response")
    if any(not isinstance(ref, str) or not ref for ref in r["evidence_refs"]):
        raise ValueError("malformed evidence refs")
    if isinstance(r["round"], bool) or not isinstance(r["round"], int) or r["round"] < 1:
        raise ValueError("invalid response round")
    if isinstance(r["reviewer_generation"], bool) or not isinstance(r["reviewer_generation"], int) or r["reviewer_generation"] < 1:
        raise ValueError("invalid response reviewer generation")
    _parse(r["submitted_at"])
    if r.get("review_profile") == DURABLE_REVIEW_V2:
        required_v2 = {
            "expected_target_tree", "reviewer_role", "review_kind",
            "rationale_summary", "next_command_proposal", "model_route_evidence",
        }
        if not required_v2 <= r.keys():
            raise ValueError("incomplete durable review v2 response")
        for key in ("expected_target_tree", "reviewer_role", "review_kind", "rationale_summary"):
            if not isinstance(r[key], str) or not r[key]:
                raise ValueError(f"invalid durable review v2 response {key}")
        if r["next_command_proposal"] is not None and not isinstance(r["next_command_proposal"], dict):
            raise ValueError("invalid next command proposal")
        if r["model_route_evidence"] is not None and not isinstance(r["model_route_evidence"], dict):
            raise ValueError("invalid model route evidence")
        if _contains_session_identity(r):
            raise ValueError("session identity is not a correctness input")


def _contains_session_identity(value: Any) -> bool:
    forbidden = {"thread_id", "conversation_id", "browser_session_id", "chat_id"}
    if isinstance(value, dict):
        if forbidden.intersection(value):
            return True
        return any(_contains_session_identity(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_session_identity(item) for item in value)
    return False


def _validate_receipt(r: dict[str, Any]) -> None:
    required = {"schema_version", "receipt_id", "response_id", "request_id", "state"}
    if not isinstance(r, dict) or not required <= r.keys() or r["schema_version"] != 1 or r["state"] != "CONSUMED":
        raise ValueError("invalid review receipt")
    if r.get("review_profile") == DURABLE_REVIEW_V2:
        tree = r.get("expected_target_tree")
        if not isinstance(tree, str) or not tree:
            raise ValueError("invalid durable review v2 receipt target tree")


def _match_request(request: dict[str, Any], response: dict[str, Any]) -> None:
    _match_response(response, request["loop_id"], request["round"], request["correlation_id"], request["expected_target_head"])
    if request.get("review_profile") == DURABLE_REVIEW_V2:
        if response.get("review_profile") != DURABLE_REVIEW_V2:
            raise ValueError("review profile mismatch")
        if response.get("expected_target_tree") != request.get("expected_target_tree"):
            raise ValueError("review response target tree mismatch")
        if response.get("reviewer_role") != request.get("reviewer_role"):
            raise ValueError("reviewer role mismatch")
        if response.get("review_kind") != request.get("review_kind"):
            raise ValueError("review kind mismatch")


def _match_response(response: dict[str, Any], loop_id: str, round: int,
                    correlation_id: str, target_head: str) -> None:
    if (response["loop_id"], response["round"], response["correlation_id"], response["expected_target_head"]) != (loop_id, round, correlation_id, target_head):
        raise ValueError("review response correlation, round, loop, or target head mismatch")
