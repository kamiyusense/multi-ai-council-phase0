from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ProviderAdapter(Protocol):
    """Transport-neutral provider adapter boundary.

    Phase 0 Core owns policy. Relay/provider implementations must not add hidden
    retries, fallback, Git writes, permission changes, or paid/API-key routing.
    """

    provider_id: str

    def prepare(self, case_context: dict[str, Any]) -> dict[str, Any]: ...
    def preflight(self, prepared_context: dict[str, Any]) -> dict[str, Any]: ...
    def dispatch(self, prepared_context: dict[str, Any]) -> object: ...
    def collect(self, process_handle: object) -> bytes: ...
    def abort(self, process_handle: object) -> dict[str, Any]: ...
    def classify(self, raw_result: bytes) -> dict[str, Any]: ...
