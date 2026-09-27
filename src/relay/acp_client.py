from __future__ import annotations
import json
from copy import deepcopy
from typing import Any

class ACPClient:
    def __init__(self, init_fixture_path: str = "fixtures/relay/acp_initialize_account.json", policy: Any = None):
        self.init_fixture_path = init_fixture_path
        self.policy = policy
        self._session_count = 0
        self._sessions: dict[str, dict[str, Any]] = {}
        # safety callbacks
        self.permission_calls = []
        self.file_read_calls = []
        self.file_write_calls = []
        self.terminal_request_calls = []
        self.elicitation_calls = []
        self.unknown_extension_calls = []

        self.configured_responses: dict[str, bytes] = {}
        self.configured_updates: dict[str, list[dict[str, Any]]] = {}

    def permission_callback(self, data: Any) -> bool:
        self.permission_calls.append(deepcopy(data))
        return False

    def file_read_callback(self, data: Any) -> bool:
        self.file_read_calls.append(deepcopy(data))
        return False

    def file_write_callback(self, data: Any) -> bool:
        self.file_write_calls.append(deepcopy(data))
        return False

    def terminal_request_callback(self, data: Any) -> bool:
        self.terminal_request_calls.append(deepcopy(data))
        return False

    def elicitation_callback(self, data: Any) -> bool:
        self.elicitation_calls.append(deepcopy(data))
        return False

    def unknown_extension_callback(self, data: Any) -> bool:
        self.unknown_extension_calls.append(deepcopy(data))
        return False

    def initialize(self, provider_id: str) -> dict[str, Any]:
        with open(self.init_fixture_path, "r") as f:
            data = json.load(f)

        if data.get("protocol_version") != 1:
            raise ValueError("Protocol version must be 1")

        capabilities = data.get("capabilities", {})
        if not isinstance(capabilities, dict):
            raise ValueError("Capabilities must be a dict")

        for key, value in capabilities.items():
            if key == "auth" and "metadata" in value:
                continue
            if not isinstance(value, dict) or value.get("mode") != "local-mock":
                raise ValueError("Unsupported capability shape")

        return {"live_process_started": False}

    def open_session(self, provider_id: str, *, cwd: str) -> str:
        self._session_count += 1
        session_id = f"acp-mock:{provider_id}:{self._session_count}"
        self._sessions[session_id] = {
            "provider_id": provider_id,
            "cwd": cwd,
            "state": "open",
            "prompted": False,
            "evidence": []
        }
        return session_id

    def prompt(self, provider_id: str, session_id: str, payload: dict[str, Any], timeout_seconds: int | None = None) -> bytes:
        if session_id not in self._sessions:
            raise ValueError("Unknown session")
        session = self._sessions[session_id]
        if session["provider_id"] != provider_id:
            raise ValueError("Wrong provider")
        if session["state"] != "open":
            raise ValueError("Session is not open")
        if session["prompted"]:
            raise ValueError("Session already prompted")

        session["prompted"] = True

        if payload.get("timeout"):
            raise TimeoutError("mock prompt timeout")
        if payload.get("error"):
            raise RuntimeError("mock prompt error")

        updates = self.configured_updates.get(session_id, [])
        for update in updates:
            if not isinstance(update, dict):
                raise ValueError("Malformed update")
            session["evidence"].append(deepcopy(update))

        response = self.configured_responses.get(session_id)
        if not isinstance(response, bytes):
            raise ValueError("Terminal response must be configured and be bytes")

        return response

    def cancel(self, provider_id: str, session_id: str) -> None:
        if session_id not in self._sessions:
            raise ValueError("Unknown session")
        session = self._sessions[session_id]
        if session["provider_id"] != provider_id:
            raise ValueError("Wrong provider")
        if session["state"] in ("cancelled", "closed"):
            raise ValueError("Session already closed/cancelled")

        session["state"] = "cancelled"

    def close(self, provider_id: str, session_id: str) -> None:
        if session_id not in self._sessions:
            raise ValueError("Unknown session")
        session = self._sessions[session_id]
        if session["provider_id"] != provider_id:
            raise ValueError("Wrong provider")
        if session["state"] == "closed":
            raise ValueError("Session already closed")

        session["state"] = "closed"

    def get_evidence(self, session_id: str) -> list[dict[str, Any]]:
        return deepcopy(self._sessions[session_id]["evidence"])
