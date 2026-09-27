from __future__ import annotations

import copy
import uuid
from dataclasses import dataclass, field
from typing import Any

from providers.policy import ProviderPolicy
from relay.transport import RelayTransport


@dataclass(slots=True)
class ACPClient(RelayTransport):
    policy: ProviderPolicy
    mock_initialize_response: dict[str, Any] = field(default_factory=dict)
    mock_terminal_responses: dict[str, bytes] = field(default_factory=dict)
    mock_updates: list[dict[str, Any]] = field(default_factory=list)

    # State tracking
    evidence: dict[str, list[dict[str, Any]]] = field(default_factory=dict)
    permission_requests: list[dict[str, Any]] = field(default_factory=list)
    file_reads: list[dict[str, Any]] = field(default_factory=list)
    file_writes: list[dict[str, Any]] = field(default_factory=list)
    terminal_requests: list[dict[str, Any]] = field(default_factory=list)
    elicitation_requests: list[dict[str, Any]] = field(default_factory=list)
    unknown_notifications: list[dict[str, Any]] = field(default_factory=list)

    # Lifecycle tracking
    _sessions: set[str] = field(default_factory=set)
    _prompts: set[str] = field(default_factory=set)
    _cancelled: set[str] = field(default_factory=set)
    _closed: set[str] = field(default_factory=set)

    def initialize(self, provider_id: str) -> dict[str, Any]:
        resp = self.mock_initialize_response

        # Strict validation
        if not isinstance(resp, dict):
            raise ValueError("mock_initialize_response must be a dict")

        if "protocol_version" not in resp or resp["protocol_version"] != 1:
            raise ValueError("protocol_version must be 1")

        capabilities = resp.get("capabilities")
        if not isinstance(capabilities, dict):
            raise ValueError("capabilities must be a dictionary")

        for key, val in capabilities.items():
            if key != "auth" and not isinstance(val, dict):
                raise ValueError(f"capability field {key} must be a dictionary")

        auth_kind = capabilities.get("auth")
        if not self.policy.validate_auth_kind(auth_kind):
            raise ValueError(f"unsupported auth kind: {auth_kind}")

        return {
            "protocol_version": 1,
            "provider_id": provider_id,
            "mode": "acp_mock",
            "live_process_started": False,
        }

    def open_session(self, provider_id: str, *, cwd: str) -> str:
        session_id = f"acp-{uuid.uuid4()}"
        self._sessions.add(session_id)
        self.evidence[session_id] = []
        return session_id

    def prompt(self, provider_id: str, session_id: str, payload: dict[str, Any], timeout_seconds: int | None = None) -> bytes:
        if session_id not in self._sessions:
            raise ValueError("session not open")
        if session_id in self._prompts:
            raise ValueError("session already prompted")
        self._prompts.add(session_id)

        # Record updates
        for update in self.mock_updates:
            self.evidence[session_id].append(copy.deepcopy(update))

        # Return exact raw terminal response
        if session_id in self.mock_terminal_responses:
            resp = self.mock_terminal_responses[session_id]
            if not isinstance(resp, bytes):
                raise TypeError("terminal response must be strictly bytes")
            return resp

        # Default to fail closed on malformed
        return b""

    def cancel(self, provider_id: str, session_id: str) -> None:
        if session_id not in self._sessions:
            raise ValueError("session not open")
        if session_id in self._closed:
            raise ValueError("session already closed")
        if session_id in self._cancelled:
            raise ValueError("session already cancelled")
        self._cancelled.add(session_id)

    def close(self, provider_id: str, session_id: str) -> None:
        if session_id not in self._sessions:
            raise ValueError("session not open")
        if session_id in self._closed:
            raise ValueError("session already closed")
        self._closed.add(session_id)

    # Callbacks that never auto-approve
    def handle_permission_request(self, req: dict[str, Any]) -> bool:
        self.permission_requests.append(copy.deepcopy(req))
        return False

    def handle_file_read(self, req: dict[str, Any]) -> bool:
        self.file_reads.append(copy.deepcopy(req))
        return False

    def handle_file_write(self, req: dict[str, Any]) -> bool:
        self.file_writes.append(copy.deepcopy(req))
        return False

    def handle_terminal_request(self, req: dict[str, Any]) -> bool:
        self.terminal_requests.append(copy.deepcopy(req))
        return False

    def handle_elicitation_request(self, req: dict[str, Any]) -> bool:
        self.elicitation_requests.append(copy.deepcopy(req))
        return False

    def handle_unknown_notification(self, req: dict[str, Any]) -> bool:
        self.unknown_notifications.append(copy.deepcopy(req))
        return False
