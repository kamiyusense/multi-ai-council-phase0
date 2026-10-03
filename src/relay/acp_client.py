from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from collections.abc import Mapping
from typing import Any

from providers.policy import ProviderPolicy

from .acp_stdio_transport import spawn_stdio_transport


class ACPClient:
    """Deterministic static/mock RelayTransport-compatible ACP test double."""

    def __init__(
        self,
        init_fixture_path: str = "fixtures/relay/acp_initialize_account.json",
        policy: ProviderPolicy | None = None,
    ):
        self.init_fixture_path = init_fixture_path
        self.policy = policy
        self._session_count = 0
        self._sessions: dict[str, dict[str, Any]] = {}

        self.permission_calls: list[Any] = []
        self.file_read_calls: list[Any] = []
        self.file_write_calls: list[Any] = []
        self.terminal_request_calls: list[Any] = []
        self.elicitation_calls: list[Any] = []
        self.unknown_extension_calls: list[Any] = []

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
        if self.policy is None:
            raise ValueError("ProviderPolicy is required")
        if self.policy.provider_id != provider_id:
            raise ValueError("provider_id does not match ProviderPolicy")

        with open(self.init_fixture_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if data.get("protocol_version") != 1:
            raise ValueError("Protocol version must be 1")
        if data.get("live_process_started") is not False:
            raise ValueError("live_process_started must be false")

        auth = data.get("auth")
        if not isinstance(auth, dict):
            raise ValueError("auth must be a dict")
        auth_kind = auth.get("kind")
        if not self.policy.validate_auth_kind(auth_kind):
            raise ValueError("unsupported auth kind")

        capabilities = data.get("capabilities")
        if not isinstance(capabilities, dict):
            raise ValueError("Capabilities must be a dict")
        for value in capabilities.values():
            if not isinstance(value, dict) or value.get("mode") != "local-mock":
                raise ValueError("Unsupported capability shape")

        return {
            "protocol_version": 1,
            "provider_id": provider_id,
            "mode": "acp_mock",
            "live_process_started": False,
        }

    def open_session(self, provider_id: str, *, cwd: str) -> str:
        self._session_count += 1
        session_id = f"acp-mock:{provider_id}:{self._session_count}"
        self._sessions[session_id] = {
            "provider_id": provider_id,
            "cwd": cwd,
            "state": "open",
            "prompted": False,
            "evidence": [],
        }
        return session_id

    def prompt(
        self,
        provider_id: str,
        session_id: str,
        payload: dict[str, Any],
        timeout_seconds: int | None = None,
    ) -> bytes:
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
        if session_id not in self._sessions:
            raise ValueError("Unknown session")
        return deepcopy(self._sessions[session_id]["evidence"])


_MAX_INTERLEAVED_NOTIFICATIONS = 16
# Official adapters push metadata-only session updates around a turn. These carry
# no model text and request nothing from the client, so the prompt wire skips them
# (bounded). Anything else that is not agent_message_chunk (tool_call, plan, ...)
# still fails closed.
_IGNORABLE_SESSION_UPDATES = frozenset({
    "available_commands_update",
    "usage_update",
    "session_info_update",
    "current_mode_update",
    "config_option_update",
})


async def _acp_read_terminal_response(
    stdout: asyncio.StreamReader,
    expected_id: int,
    timeout: float,
    method_name: str,
) -> dict[str, Any]:
    """Internal helper to read and validate a JSON-RPC terminal response.

    Official adapters may interleave one-way notifications (e.g. session/update)
    before the terminal response. Up to _MAX_INTERLEAVED_NOTIFICATIONS are
    skipped; an agent-initiated *request* (method + id, e.g. a permission
    request) is never answered and fails closed.
    """
    skipped = 0
    while True:
        try:
            line = await asyncio.wait_for(stdout.readline(), timeout=timeout)
        except asyncio.TimeoutError as e:
            raise TimeoutError(f"Timeout reading ACP {method_name} response") from e

        if not line:
            raise EOFError(f"Unexpected EOF reading ACP {method_name} response")

        try:
            response = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError(f"Malformed JSON in ACP {method_name} response") from e

        if not isinstance(response, dict):
            raise ValueError(f"ACP {method_name} response must be a JSON object")

        if response.get("jsonrpc") != "2.0":
            raise ValueError(f"ACP {method_name} response must have jsonrpc='2.0'")

        if "method" in response:
            if "id" in response:
                raise ValueError(f"ACP {method_name}: agent-initiated request is not supported")
            skipped += 1
            if skipped > _MAX_INTERLEAVED_NOTIFICATIONS:
                raise ValueError(f"ACP {method_name}: too many interleaved notifications")
            continue
        break

    if type(response.get("id")) is not int or response["id"] != expected_id:
        raise ValueError(f"ACP {method_name} response id mismatch")

    if "error" in response:
        raise RuntimeError(f"ACP {method_name} returned error")

    result = response.get("result")
    if not isinstance(result, dict):
        raise ValueError(f"ACP {method_name} response missing valid result object")

    return result


async def _acp_exchange(
    stdout: asyncio.StreamReader,
    stdin: asyncio.StreamWriter,
    request: dict[str, Any],
    expected_id: int,
    timeout: float,
    method_name: str,
) -> dict[str, Any]:
    """Internal helper to execute a single JSON-RPC request and validate its response."""
    request_bytes = json.dumps(request).encode("utf-8") + b"\n"
    stdin.write(request_bytes)
    await stdin.drain()

    return await _acp_read_terminal_response(stdout, expected_id, timeout, method_name)


async def acp_initialize_wire(command: str, *args: str, timeout: float = 2.0, env: Mapping[str, str] | None = None) -> dict[str, Any]:
    """Execute a single ACP v1 initialize round-trip against a local spawned process.

    This provides an isolated, retry-free primitive bridging Relay to the standard
    ACP Python SDK stdio transport behavior.

    Source: agentclientprotocol/python-sdk commit 9d07d7871ef4b220b8507e15fc4b1560f0950a64;
    src/acp/client/connection.py initialize request contract (Apache-2.0).
    """
    async with spawn_stdio_transport(command, *args, env=env, shutdown_timeout=timeout) as (stdout, stdin, _process):
        request = {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": 1,
                "clientCapabilities": {},
                "clientInfo": {"name": "relay", "version": "0.1.0"},
            },
        }

        result = await _acp_exchange(stdout, stdin, request, 0, timeout, "initialize")

        if type(result.get("protocolVersion")) is not int or result["protocolVersion"] != 1:
            raise ValueError("ACP initialize response unsupported protocol version")

        return result


async def _acp_initialize(stdout: asyncio.StreamReader, stdin: asyncio.StreamWriter, timeout: float) -> dict[str, Any]:
    """Internal helper: ACP initialize round-trip (request id 0)."""
    init_request = {
        "jsonrpc": "2.0",
        "id": 0,
        "method": "initialize",
        "params": {
            "protocolVersion": 1,
            "clientCapabilities": {},
            "clientInfo": {"name": "relay", "version": "0.1.0"},
        },
    }
    init_result = await _acp_exchange(stdout, stdin, init_request, 0, timeout, "initialize")
    if type(init_result.get("protocolVersion")) is not int or init_result["protocolVersion"] != 1:
        raise ValueError("ACP initialize response unsupported protocol version")
    return init_result


async def _acp_new_session(
    stdout: asyncio.StreamReader, stdin: asyncio.StreamWriter, cwd: str, timeout: float, meta: dict[str, Any] | None = None
) -> str:
    """Internal helper: ACP session/new round-trip (request id 1).

    ``meta`` (the provider profile's ``session_meta``, e.g. Claude's ``allowDangerouslySkipPermissions=False``)
    is sent as ``params._meta`` so the official adapter receives the Phase 0 permission policy.
    """
    session_request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "session/new",
        "params": {
            "cwd": cwd,
            "mcpServers": [],
        },
    }
    if meta is not None:
        session_request["params"]["_meta"] = meta
    session_result = await _acp_exchange(stdout, stdin, session_request, 1, timeout, "session/new")

    session_id = session_result.get("sessionId")
    if not isinstance(session_id, str) or not session_id.strip():
        raise ValueError("ACP session/new response missing valid sessionId")

    return session_id


async def _acp_handshake(stdout: asyncio.StreamReader, stdin: asyncio.StreamWriter, cwd: str, timeout: float) -> str:
    """Internal helper to execute initialize and session/new against an existing transport."""
    await _acp_initialize(stdout, stdin, timeout)
    return await _acp_new_session(stdout, stdin, cwd, timeout)


async def acp_open_session_wire(command: str, *args: str, cwd: str, timeout: float = 2.0, env: Mapping[str, str] | None = None) -> str:
    """Execute initialize and session/new round-trips against a single local spawned process."""
    async with spawn_stdio_transport(command, *args, env=env, cwd=cwd, shutdown_timeout=timeout) as (stdout, stdin, _process):
        return await _acp_handshake(stdout, stdin, cwd, timeout)


async def acp_mock_prompt_wire(command: str, *args: str, cwd: str, prompt_text: str, timeout: float = 2.0, env: Mapping[str, str] | None = None) -> str:
    """Execute a single ACP v1 initialize -> session/new -> session/prompt terminal round-trip."""
    async with spawn_stdio_transport(command, *args, env=env, cwd=cwd, shutdown_timeout=timeout) as (stdout, stdin, _process):
        session_id = await _acp_handshake(stdout, stdin, cwd, timeout)

        prompt_request = {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "session/prompt",
            "params": {
                "sessionId": session_id,
                "prompt": [{"type": "text", "text": prompt_text}],
            },
        }

        result = await _acp_exchange(stdout, stdin, prompt_request, 2, timeout, "session/prompt")
        stop_reason = result.get("stopReason")
        if not isinstance(stop_reason, str) or stop_reason not in {"end_turn", "max_tokens", "max_turn_requests", "refusal", "cancelled"}:
            raise ValueError("ACP session/prompt response missing valid stopReason")

        return stop_reason

async def _acp_prompt_text(
    stdout: asyncio.StreamReader,
    stdin: asyncio.StreamWriter,
    session_id: str,
    prompt_text: str,
    timeout: float,
    *,
    max_chunks: int = 3,
    max_ignored: int = _MAX_INTERLEAVED_NOTIFICATIONS,
    ignorable: frozenset[str] = _IGNORABLE_SESSION_UPDATES,
) -> dict[str, str]:
    """Internal helper: session/prompt (request id 2) -> text chunks (default 1..3) + stopReason."""
    prompt_request = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "session/prompt",
        "params": {
            "sessionId": session_id,
            "prompt": [{"type": "text", "text": prompt_text}],
        },
    }

    request_bytes = json.dumps(prompt_request).encode("utf-8") + b"\n"
    stdin.write(request_bytes)
    await stdin.drain()

    concatenated_text = ""
    notification_count = 0
    terminal_result = None

    ignored = 0
    for _ in range(max_chunks + 1 + max_ignored):
        try:
            line = await asyncio.wait_for(stdout.readline(), timeout=timeout)
        except asyncio.TimeoutError as e:
            raise TimeoutError("Timeout reading ACP session/prompt response") from e

        if not line:
            raise EOFError("Unexpected EOF reading ACP session/prompt response")

        try:
            frame = json.loads(line)
        except json.JSONDecodeError as e:
            raise ValueError("Malformed JSON in ACP session/prompt response") from e

        if not isinstance(frame, dict):
            raise ValueError("ACP session/prompt response must be a JSON object")

        if frame.get("jsonrpc") != "2.0":
            raise ValueError("ACP session/prompt response must have jsonrpc='2.0'")

        if "id" in frame:
            # Terminal response
            if notification_count == 0:
                raise ValueError("ACP session/update notification must not have an id field")
            if type(frame.get("id")) is not int or frame["id"] != 2:
                raise ValueError("ACP session/prompt response id mismatch")
            if "error" in frame:
                raise RuntimeError("ACP session/prompt returned error")
            terminal_result = frame.get("result")
            if not isinstance(terminal_result, dict):
                raise ValueError("ACP session/prompt response missing valid result object")
            break
        else:
            # Notification
            if notification_count >= max_chunks:
                raise ValueError(f"Maximum of {max_chunks} text updates exceeded")

            if frame.get("method") != "session/update":
                raise ValueError("ACP session/update notification method must be 'session/update'")

            params = frame.get("params")
            if not isinstance(params, dict):
                raise ValueError("ACP session/update notification missing valid params object")

            if params.get("sessionId") != session_id:
                raise ValueError("ACP session/update notification sessionId mismatch")

            update = params.get("update")
            if not isinstance(update, dict):
                raise ValueError("ACP session/update notification missing valid update object")

            if update.get("sessionUpdate") in _IGNORABLE_SESSION_UPDATES:
                ignored += 1
                if ignored > _MAX_INTERLEAVED_NOTIFICATIONS:
                    raise ValueError("Too many ignorable session updates")
                continue

            if update.get("sessionUpdate") != "agent_message_chunk":
                raise ValueError("ACP session/update notification sessionUpdate must be 'agent_message_chunk'")

            notif_content = update.get("content")
            if not isinstance(notif_content, dict):
                raise ValueError("ACP session/update notification missing valid content object")

            if notif_content.get("type") != "text":
                raise ValueError("ACP session/update notification content type must be 'text'")

            text = notif_content.get("text")
            if not isinstance(text, str):
                raise ValueError("ACP session/update notification missing valid text string")

            concatenated_text += text
            notification_count += 1

    if terminal_result is None:
        raise ValueError("No terminal response received within bound")

    stop_reason = terminal_result.get("stopReason")
    if not isinstance(stop_reason, str) or stop_reason not in {"end_turn", "max_tokens", "max_turn_requests", "refusal", "cancelled"}:
        raise ValueError("ACP session/prompt response missing valid stopReason")

    return {"text": concatenated_text, "stopReason": stop_reason}


async def acp_mock_text_update_wire(command: str, *args: str, cwd: str, prompt_text: str, timeout: float = 2.0, env: Mapping[str, str] | None = None) -> dict[str, str]:
    """Mock-only ACP prompt: concatenate 1..3 text updates before the terminal response."""
    async with spawn_stdio_transport(command, *args, env=env, cwd=cwd, shutdown_timeout=timeout) as (stdout, stdin, _process):
        session_id = await _acp_handshake(stdout, stdin, cwd, timeout)
        return await _acp_prompt_text(stdout, stdin, session_id, prompt_text, timeout)

def acp_mock_text_to_phase0_raw(mock_result: dict[str, str]) -> bytes:
    """
    MOCK ONLY: Pure synchronous helper that converts a synthetic local-fake
    ACP text update result into the phase0-response-v1 JSON bytes envelope
    accepted by RelayCoreAdapter.classify().

    This does NOT connect to a live adapter, dispatch path, bridge, provider,
    or network. It creates only synthetic response data, with no evidence refs.
    """
    if not isinstance(mock_result, dict):
        raise TypeError("mock_result must be a dictionary")

    if set(mock_result.keys()) != {"text", "stopReason"}:
        raise ValueError("mock_result must contain exactly the keys {'text', 'stopReason'}")

    text = mock_result["text"]
    if not isinstance(text, str):
        raise TypeError("text must be a string")

    if not text.strip():
        raise ValueError("text cannot be empty or only whitespace")

    stop_reason = mock_result["stopReason"]
    if not isinstance(stop_reason, str):
        raise TypeError("stopReason must be a string")

    if stop_reason != "end_turn":
        raise ValueError(f"stopReason must be exactly 'end_turn', got {stop_reason}")

    response = {
        "schema_version": "phase0-response-v1",
        "answer_state": "ANSWER",
        "conclusion_code": "SUCCESS",
        "safety_warning": "UNKNOWN",
        "safety_reason": None,
        "evidence_refs": [],
        "marker_echoes": {"head": None, "middle": None, "tail": None},
        "answer_text": text
    }

    return json.dumps(response, ensure_ascii=False).encode("utf-8")
