from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


class AdmissionRefused(ValueError):
    """A pre-generation admission check refused the dispatch; nothing was prompted."""


class RouteViolationCancelled(Exception):
    """A confirmed API-key / external route was reported mid-turn; the lifecycle cancels and stops."""


@runtime_checkable
class RelayTransport(Protocol):
    """Transport boundary. Implementations must not retry or fallback."""

    def initialize(self, provider_id: str) -> dict[str, Any]: ...
    def open_session(self, provider_id: str, *, cwd: str) -> str: ...
    def prompt(self, provider_id: str, session_id: str, payload: dict[str, Any], timeout_seconds: int | None = None) -> bytes: ...
    def cancel(self, provider_id: str, session_id: str) -> None: ...
    def close(self, provider_id: str, session_id: str) -> None: ...
