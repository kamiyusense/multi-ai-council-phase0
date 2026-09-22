"""Transport-neutral wake layer for durable semantic review.

A transport may wake a reviewer, but it never supplies the authoritative
review result. Correctness comes only from a durable GitHub review_response
validated against its review_request.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .reviewer import DURABLE_REVIEW_V2


SUPPORTED_ROUTES = frozenset({"browser", "direct", "manual"})


@dataclass(frozen=True)
class TransportResult:
    status: str
    reason: str
    evidence: dict[str, Any]


class ReviewerTransport(Protocol):
    route: str

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


class MockReviewerTransport:
    """Fixture transport. It never opens a browser or starts a model."""

    def __init__(self, route: str) -> None:
        if route not in SUPPORTED_ROUTES:
            raise ValueError("unsupported reviewer transport route")
        self.route = route
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
        result = transport.send(wake)
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
