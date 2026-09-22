"""Transport-neutral wake layer for durable semantic review.

A transport may wake a reviewer, but it never supplies the authoritative
review result. Correctness comes only from a durable GitHub review_response
validated against its review_request.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol

from .reviewer import DURABLE_REVIEW_V2


SUPPORTED_ROUTES = frozenset({"browser", "direct", "manual"})
WAKE_ATTEMPT_PROFILE = "DURABLE_REVIEW_WAKE_ATTEMPT_V1"


@dataclass(frozen=True)
class TransportResult:
    status: str
    reason: str
    evidence: dict[str, Any]


class ReviewerTransport(Protocol):
    route: str
    live_transport: bool

    def send(self, wake: dict[str, Any]) -> TransportResult: ...


def build_review_wake(request: dict[str, Any], request_ref: str) -> dict[str, Any]:
    if request.get("review_profile") != DURABLE_REVIEW_V2:
        raise ValueError("durable review v2 request required")
    required = (
        "request_id", "loop_id", "round", "correlation_id",
        "expected_target_head", "expected_target_tree",
        "reviewer_role", "review_kind",
    )
    for key in required:
        value = request.get(key)
        if key == "round":
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError("invalid review wake round")
        elif not isinstance(value, str) or not value:
            raise ValueError(f"invalid review wake {key}")
    expected_ref = (
        f"automation/command_bus/review_requests/"
        f"{request['loop_id']}/{request['request_id']}.json"
    )
    if request_ref != expected_ref:
        raise ValueError("review request durable path mismatch")
    return {
        "schema_version": 1,
        "wake_kind": "DURABLE_REVIEW_WAKE_V1",
        "request_ref": request_ref,
        "request_id": request["request_id"],
        "loop_id": request["loop_id"],
        "round": request["round"],
        "correlation_id": request["correlation_id"],
        "expected_target_head": request["expected_target_head"],
        "expected_target_tree": request["expected_target_tree"],
        "reviewer_role": request["reviewer_role"],
        "review_kind": request["review_kind"],
        "response_channel": "GITHUB_DURABLE_ONLY",
        "parse_browser_output": False,
        "retry": 0,
        "fallback": "disabled",
    }


def make_wake_attempt(
    request: dict[str, Any],
    *,
    attempt_id: str,
    request_ref: str,
    route: str,
    created_at: str,
) -> dict[str, Any]:
    wake = build_review_wake(request, request_ref)
    if route not in SUPPORTED_ROUTES:
        raise ValueError("unsupported reviewer transport route")
    if not isinstance(attempt_id, str) or not attempt_id:
        raise ValueError("wake attempt id required")
    if not isinstance(created_at, str):
        raise ValueError("wake attempt timestamp required")
    parsed = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("wake attempt timestamp must include timezone")
    return {
        "schema_version": 1,
        "wake_profile": WAKE_ATTEMPT_PROFILE,
        "attempt_id": attempt_id,
        "request_id": wake["request_id"],
        "loop_id": wake["loop_id"],
        "round": wake["round"],
        "correlation_id": wake["correlation_id"],
        "expected_target_head": wake["expected_target_head"],
        "expected_target_tree": wake["expected_target_tree"],
        "request_ref": request_ref,
        "route": route,
        "state": "RESERVED",
        "created_at": created_at,
        "retry": 0,
        "fallback": "disabled",
    }


def validate_wake_attempt(
    request: dict[str, Any],
    attempt: dict[str, Any],
    *,
    request_ref: str,
    route: str,
) -> None:
    expected = make_wake_attempt(
        request,
        attempt_id=attempt.get("attempt_id"),
        request_ref=request_ref,
        route=route,
        created_at=attempt.get("created_at"),
    )
    if attempt != expected:
        raise ValueError("wake attempt does not match durable review request")


class MockReviewerTransport:
    """Fixture transport. It never opens a browser or starts a model."""

    def __init__(self, route: str) -> None:
        if route not in SUPPORTED_ROUTES:
            raise ValueError("unsupported reviewer transport route")
        self.route = route
        self.live_transport = False
        self.sent: list[dict[str, Any]] = []

    def send(self, wake: dict[str, Any]) -> TransportResult:
        self.sent.append(dict(wake))
        return TransportResult(
            "SIMULATED",
            "transport wake simulated; durable GitHub response still required",
            {
                "route": self.route,
                "external_send_attempted": False,
                "live_model_started": False,
                "browser_ui_parsed": False,
                "durable_response_required": True,
                "retry_count": 0,
                "fallback_used": False,
            },
        )


class ReviewWakeCoordinator:
    """Exactly-one-attempt coordinator for a logical review request."""

    def __init__(self) -> None:
        self.dispatched_request_ids: set[str] = set()

    def dispatch(
        self,
        request: dict[str, Any],
        *,
        request_ref: str,
        transport: ReviewerTransport,
    ) -> TransportResult:
        request_id = request.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            return TransportResult(
                "UNKNOWN", "review request identity unavailable",
                {"retry_count": 0, "fallback_used": False},
            )
        if getattr(transport, "live_transport", True):
            return TransportResult(
                "BLOCKED", "live reviewer transport is not authorized by static P1",
                {
                    "request_id": request_id,
                    "retry_count": 0,
                    "fallback_used": False,
                    "external_send_attempted": False,
                },
            )
        if request_id in self.dispatched_request_ids:
            return TransportResult(
                "BLOCKED", "review wake already attempted",
                {
                    "request_id": request_id,
                    "retry_count": 0,
                    "fallback_used": False,
                    "second_send_attempted": False,
                },
            )
        try:
            wake = build_review_wake(request, request_ref)
        except (ValueError, TypeError, KeyError) as exc:
            return TransportResult(
                "UNKNOWN", str(exc),
                {"retry_count": 0, "fallback_used": False},
            )

        # Mark before send so an ambiguous transport result cannot be replayed.
        self.dispatched_request_ids.add(request_id)
        try:
            result = transport.send(wake)
        except Exception as exc:
            return TransportResult(
                "UNKNOWN",
                f"review transport result unavailable: {type(exc).__name__}",
                {
                    "request_id": request_id,
                    "request_ref": request_ref,
                    "external_send_attempted": "UNKNOWN",
                    "retry_count": 0,
                    "fallback_used": False,
                    "second_send_attempted": False,
                },
            )
        evidence = dict(result.evidence)
        evidence.update({
            "request_id": request_id,
            "request_ref": request_ref,
            "retry_count": 0,
            "fallback_used": False,
            "second_send_attempted": False,
        })
        if result.status not in {"SIMULATED", "SENT", "UNKNOWN"}:
            return TransportResult("UNKNOWN", "unsupported transport result", evidence)
        return TransportResult(result.status, result.reason, evidence)


    def dispatch_reserved(
        self,
        request: dict[str, Any],
        *,
        request_ref: str,
        transport: ReviewerTransport,
        reservation: TransportResult,
    ) -> TransportResult:
        if reservation.status != "RESERVED":
            return TransportResult(
                "BLOCKED", "fresh durable wake reservation required",
                {"retry_count": 0, "fallback_used": False},
            )
        if reservation.evidence.get("fresh_reservation") is not True:
            return TransportResult(
                "BLOCKED", "recovered wake reservation cannot be replayed",
                {"retry_count": 0, "fallback_used": False},
            )
        attempt = reservation.evidence.get("attempt_record")
        if not isinstance(attempt, dict):
            return TransportResult(
                "UNKNOWN", "durable wake attempt readback unavailable",
                {"retry_count": 0, "fallback_used": False},
            )
        try:
            validate_wake_attempt(
                request, attempt,
                request_ref=request_ref,
                route=transport.route,
            )
        except (ValueError, TypeError, KeyError) as exc:
            return TransportResult(
                "UNKNOWN", str(exc),
                {"retry_count": 0, "fallback_used": False},
            )
        return self.dispatch(
            request, request_ref=request_ref, transport=transport
        )
