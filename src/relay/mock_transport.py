from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MockTransport:
    responses: dict[str, bytes] = field(default_factory=dict)
    prompt_counts: dict[str, int] = field(default_factory=dict)
    cancelled: list[tuple[str, str]] = field(default_factory=list)
    closed: list[tuple[str, str]] = field(default_factory=list)
    prompt_timeouts: dict[str, float | None] = field(default_factory=dict)
    timeout_providers: set[str] = field(default_factory=set)
    error_providers: set[str] = field(default_factory=set)
    live_process_started: bool = False

    def initialize(self, provider_id: str) -> dict[str, Any]:
        return {
            "protocol_version": 1,
            "provider_id": provider_id,
            "mode": "mock",
            "live_process_started": False,
        }

    def open_session(self, provider_id: str, *, cwd: str) -> str:
        return f"mock:{provider_id}:{cwd}"

    def prompt(self, provider_id: str, session_id: str, payload: dict[str, Any], timeout_seconds: float | None = None) -> bytes:
        self.prompt_counts[provider_id] = self.prompt_counts.get(provider_id, 0) + 1
        self.prompt_timeouts[provider_id] = timeout_seconds
        if provider_id in self.timeout_providers:
            raise TimeoutError("mock prompt timeout")
        if provider_id in self.error_providers:
            raise RuntimeError("mock prompt error")
        return self.responses.get(provider_id, b"{}")

    def cancel(self, provider_id: str, session_id: str) -> None:
        self.cancelled.append((provider_id, session_id))

    def close(self, provider_id: str, session_id: str) -> None:
        self.closed.append((provider_id, session_id))
