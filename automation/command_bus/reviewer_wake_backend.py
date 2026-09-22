"""Durable GitHub reservation for reviewer wake attempts.

A reservation is append-only and intentionally one-way. Once a request has a
durable wake-attempt record, a fresh session must assume the external wake may
have happened and must not send again. This preserves retry=0 across Work
replacement and ambiguous transport outcomes.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Protocol

from .reviewer_transport import (
    WAKE_ATTEMPT_PROFILE,
    TransportResult,
    make_wake_attempt,
    validate_wake_attempt,
)

_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class WakeContent:
    path: str
    text: str
    sha: str


class WakeContentsClient(Protocol):
    def get(self, path: str, ref: str) -> WakeContent | None: ...
    def list(self, prefix: str, ref: str) -> list[WakeContent]: ...
    def create(self, path: str, text: str, message: str, branch: str) -> WakeContent: ...


def wake_attempt_path(loop_id: str, attempt_id: str) -> str:
    _safe(loop_id, "loop_id")
    _safe(attempt_id, "attempt_id")
    return f"review_wake_attempts/{loop_id}/{attempt_id}.json"


class DurableWakeBackend:
    def __init__(self, client: WakeContentsClient, *, branch: str, ref: str | None = None):
        self.client = client
        self.branch = branch
        self.ref = ref or branch

    def reserve(
        self,
        request: dict[str, Any],
        *,
        attempt_id: str,
        request_ref: str,
        route: str,
        created_at: str,
    ) -> TransportResult:
        try:
            record = make_wake_attempt(
                request,
                attempt_id=attempt_id,
                request_ref=request_ref,
                route=route,
                created_at=created_at,
            )
            loop_id = record["loop_id"]
            existing = self._attempts_for_request(loop_id, record["request_id"], self.branch)
            if existing:
                return TransportResult(
                    "BLOCKED",
                    "durable wake attempt already exists for review request",
                    {
                        "request_id": record["request_id"],
                        "existing_attempt_ids": [x["attempt_id"] for x in existing],
                        "fresh_reservation": False,
                        "retry_count": 0,
                        "fallback_used": False,
                    },
                )

            path = wake_attempt_path(loop_id, attempt_id)
            if self.client.get(path, self.branch) is not None:
                return TransportResult(
                    "BLOCKED",
                    "durable wake attempt identity already exists",
                    {
                        "request_id": record["request_id"],
                        "fresh_reservation": False,
                        "retry_count": 0,
                        "fallback_used": False,
                    },
                )

            self.client.create(
                path,
                _canonical(record),
                f"reserve reviewer wake {attempt_id}",
                self.branch,
            )
            verified = self.client.get(path, self.branch)
            if verified is None:
                return TransportResult(
                    "UNKNOWN",
                    "wake reservation write readback unavailable",
                    {
                        "request_id": record["request_id"],
                        "fresh_reservation": False,
                        "retry_count": 0,
                        "fallback_used": False,
                    },
                )
            readback = self._decode(verified)
            if readback != record:
                return TransportResult(
                    "UNKNOWN",
                    "wake reservation write readback mismatch",
                    {
                        "request_id": record["request_id"],
                        "fresh_reservation": False,
                        "retry_count": 0,
                        "fallback_used": False,
                    },
                )
            validate_wake_attempt(
                request, readback, request_ref=request_ref, route=route
            )
            return TransportResult(
                "RESERVED",
                "durable wake attempt reserved and verified",
                {
                    "request_id": record["request_id"],
                    "attempt_id": attempt_id,
                    "attempt_record": readback,
                    "attempt_path": path,
                    "fresh_reservation": True,
                    "retry_count": 0,
                    "fallback_used": False,
                },
            )
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
            return TransportResult(
                "UNKNOWN",
                str(exc),
                {
                    "fresh_reservation": False,
                    "retry_count": 0,
                    "fallback_used": False,
                },
            )

    def read_for_request(
        self, request: dict[str, Any], *, request_ref: str, route: str
    ) -> TransportResult:
        try:
            loop_id = request.get("loop_id")
            request_id = request.get("request_id")
            _safe(loop_id, "loop_id")
            _safe(request_id, "request_id")
            attempts = self._attempts_for_request(loop_id, request_id, self.ref)
            if not attempts:
                return TransportResult(
                    "UNKNOWN",
                    "durable wake attempt missing",
                    {
                        "request_id": request_id,
                        "fresh_reservation": False,
                        "retry_count": 0,
                        "fallback_used": False,
                    },
                )
            if len(attempts) != 1:
                return TransportResult(
                    "UNKNOWN",
                    "multiple durable wake attempts for one review request",
                    {
                        "request_id": request_id,
                        "fresh_reservation": False,
                        "retry_count": 0,
                        "fallback_used": False,
                    },
                )
            attempt = attempts[0]
            validate_wake_attempt(
                request, attempt, request_ref=request_ref, route=route
            )
            return TransportResult(
                "READ",
                "durable wake attempt recovered; replay is forbidden",
                {
                    "request_id": request_id,
                    "attempt_id": attempt["attempt_id"],
                    "attempt_record": attempt,
                    "fresh_reservation": False,
                    "retry_count": 0,
                    "fallback_used": False,
                },
            )
        except (ValueError, TypeError, KeyError, json.JSONDecodeError, RuntimeError) as exc:
            return TransportResult(
                "UNKNOWN",
                str(exc),
                {
                    "fresh_reservation": False,
                    "retry_count": 0,
                    "fallback_used": False,
                },
            )

    def _attempts_for_request(
        self, loop_id: str, request_id: str, ref: str
    ) -> list[dict[str, Any]]:
        prefix = f"review_wake_attempts/{loop_id}/"
        result: list[dict[str, Any]] = []
        for content in self.client.list(prefix, ref):
            record = self._decode(content)
            if record["loop_id"] != loop_id:
                raise ValueError("wake attempt loop/path mismatch")
            if record["request_id"] == request_id:
                result.append(record)
        return result

    def _decode(self, content: WakeContent) -> dict[str, Any]:
        record = json.loads(content.text)
        if not isinstance(record, dict):
            raise ValueError("wake attempt record is not an object")
        required = {
            "schema_version", "wake_profile", "attempt_id", "request_id",
            "loop_id", "round", "correlation_id", "expected_target_head",
            "expected_target_tree", "request_ref", "route", "state",
            "created_at", "retry", "fallback",
        }
        if not required <= record.keys():
            raise ValueError("incomplete wake attempt record")
        if record["schema_version"] != 1 or record["wake_profile"] != WAKE_ATTEMPT_PROFILE:
            raise ValueError("unsupported wake attempt record")
        if record["state"] != "RESERVED" or record["retry"] != 0 or record["fallback"] != "disabled":
            raise ValueError("unsafe wake attempt state")
        expected_path = wake_attempt_path(record["loop_id"], record["attempt_id"])
        if content.path != expected_path:
            raise ValueError("wake attempt path identity mismatch")
        _safe(record["request_id"], "request_id")
        return record


def _canonical(record: dict[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"))


def _safe(value: Any, field: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value in {".", ".."}
        or not _COMPONENT.fullmatch(value)
    ):
        raise ValueError(f"unsafe wake {field}")
