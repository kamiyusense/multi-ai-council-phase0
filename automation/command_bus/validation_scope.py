"""Deterministic validation scope for command-bus static code.

Operational ledger records are append-only data and grow without bound. Static
code validation therefore verifies a bounded code/test/schema scope by blob SHA
and validates live durable records through their own protocol, rather than
re-downloading every historical command/receipt/evidence blob on every run.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable


ROOT = "automation/command_bus/"
STATIC_PREFIXES = (
    ROOT + "tests/",
    ROOT + "schema/",
    ROOT + "config/",
    ROOT + "docker/",
)
LEDGER_PREFIXES = (
    ROOT + "commands/",
    ROOT + "events/",
    ROOT + "evidence/",
    ROOT + "receipts/",
    ROOT + "state/",
    ROOT + "review_requests/",
    ROOT + "review_claims/",
    ROOT + "review_responses/",
    ROOT + "review_receipts/",
    ROOT + "review_wake_attempts/",
    ROOT + "execution_requests/",
    ROOT + "execution_claims/",
    ROOT + "execution_results/",
    ROOT + "execution_receipts/",
    ROOT + "jules_launch_attempts/",
    ROOT + "auth_handoffs/",
    ROOT + "loop_owner_events/",
    ROOT + "loop_owner_observations/",
    ROOT + "loop_owner_authorities/",
)


class ScopeKind(StrEnum):
    STATIC = "STATIC"
    LEDGER = "LEDGER"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class ValidationScope:
    static_blobs: tuple[dict[str, Any], ...]
    ledger_blobs: tuple[dict[str, Any], ...]
    unknown_blobs: tuple[dict[str, Any], ...]

    @property
    def static_blob_count(self) -> int:
        return len(self.static_blobs)

    @property
    def ledger_blob_count(self) -> int:
        return len(self.ledger_blobs)


def classify_command_bus_path(path: str) -> ScopeKind:
    if not isinstance(path, str) or not path.startswith(ROOT):
        return ScopeKind.UNKNOWN
    rest = path[len(ROOT):]
    if not rest:
        return ScopeKind.UNKNOWN
    if "/" not in rest:
        if rest.endswith(".py") or rest in {"README.md", "claude_gate_compose.yaml"}:
            return ScopeKind.STATIC
        return ScopeKind.UNKNOWN
    if any(path.startswith(prefix) for prefix in STATIC_PREFIXES):
        return ScopeKind.STATIC
    if any(path.startswith(prefix) for prefix in LEDGER_PREFIXES):
        return ScopeKind.LEDGER
    return ScopeKind.UNKNOWN


def partition_command_bus_blobs(entries: Iterable[dict[str, Any]]) -> ValidationScope:
    static: list[dict[str, Any]] = []
    ledger: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    for raw in entries:
        if not isinstance(raw, dict):
            unknown.append({"path": "<malformed>", "type": "<malformed>"})
            continue
        if raw.get("type") != "blob":
            continue
        path = raw.get("path")
        kind = classify_command_bus_path(path)
        target = static if kind is ScopeKind.STATIC else ledger if kind is ScopeKind.LEDGER else unknown
        target.append(dict(raw))
    key = lambda item: str(item.get("path"))
    return ValidationScope(tuple(sorted(static, key=key)), tuple(sorted(ledger, key=key)), tuple(sorted(unknown, key=key)))


def require_bounded_static_scope(entries: Iterable[dict[str, Any]]) -> ValidationScope:
    scope = partition_command_bus_blobs(entries)
    if scope.unknown_blobs:
        paths = ", ".join(str(item.get("path")) for item in scope.unknown_blobs)
        raise ValueError(f"unknown command-bus blob scope: {paths}")
    if not scope.static_blobs:
        raise ValueError("static command-bus scope is empty")
    return scope
