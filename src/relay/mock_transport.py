from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MockTransport:
    responses: dict[str, bytes] = field(default_factory=dict)
    prompt_counts: dict[str, int] = field(default_factory=dict)
    cancelled: list[tuple[str, str]] = field(default_factory=list)
    closed: list[tuple[str, str]] = field(default_factory=list)
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

    def prompt(self, provider_id: str, session_id: str, payload: dict[str, Any]) -> bytes:
        self.prompt_counts[provider_id] = self.prompt_counts.get(provider_id, 0) + 1
        return self.responses.get(provider_id, b"{}")

    def cancel(self, provider_id: str, session_id: str) -> None:
        self.cancelled.append((provider_id, session_id))

    def close(self, provider_id: str, session_id: str) -> None:
        self.closed.append((provider_id, session_id))
