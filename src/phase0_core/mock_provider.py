from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class MockProviderAdapter:
    provider_id: str
    raw_result: bytes = b"{}"
    live_execution_count: int = 0
    dispatch_count: int = 0
    aborted_handles: list[object] = field(default_factory=list)

    def prepare(self, case_context: dict[str, Any]) -> dict[str, Any]:
        return dict(case_context)

    def preflight(self, prepared_context: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "mode": "mock", "provider": self.provider_id}

    def dispatch(self, prepared_context: dict[str, Any]) -> object:
        self.dispatch_count += 1
        return {"provider": self.provider_id, "dispatch": self.dispatch_count}

    def collect(self, process_handle: object) -> bytes:
        return self.raw_result

    def abort(self, process_handle: object) -> dict[str, Any]:
        self.aborted_handles.append(process_handle)
        return {"aborted": True, "provider": self.provider_id}

    def classify(self, raw_result: bytes) -> dict[str, Any]:
        return {"provider": self.provider_id, "mock": True, "raw_size": len(raw_result)}
