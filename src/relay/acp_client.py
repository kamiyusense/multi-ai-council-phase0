from __future__ import annotations

import json
from typing import Any

from providers.policy import ProviderPolicy
from relay.transport import RelayTransport

class ACPClient:
    """Static/mock ACP lifecycle wrapper around an injected connection double.

    This layer ducks-types RelayTransport but applies the documented ACP lifecycle:
    initialize -> verify auth/capabilities -> open session -> prompt -> stream -> close/cancel.
    It applies client-side safety handlers, rejecting dangerous/unsupported requests,
    and returns UNKNOWN on structural failure instead of silently succeeding.
    """

    def __init__(self, connection_double: Any, policy: ProviderPolicy) -> None:
        self.conn = connection_double
        self.policy = policy
        self._live_process_started = False
        self._retry_count = 0
        self._fallback_enabled = False

    def initialize(self, provider_id: str) -> dict[str, Any]:
        result = self.conn.initialize()
        if not isinstance(result, dict):
            raise RuntimeError("UNKNOWN: initialize result is not a dict")

        auth_kind = result.get("auth_kind")
        if not self.policy.validate_auth_kind(auth_kind):
            raise RuntimeError(f"UNKNOWN: rejected auth_kind {auth_kind}")

        capabilities = result.get("capabilities")
        if not isinstance(capabilities, dict):
            raise RuntimeError("UNKNOWN: malformed or missing capabilities")

        return {
            "protocol_version": result.get("protocol_version", 1),
            "provider_id": provider_id,
            "capabilities": capabilities,
            "live_process_started": self._live_process_started,
        }

    def open_session(self, provider_id: str, *, cwd: str) -> str:
        session = self.conn.new_session(cwd=cwd)
        if not isinstance(session, dict) or not session.get("session_id"):
            raise RuntimeError("UNKNOWN: malformed session response")
        return session["session_id"]

    def prompt(self, provider_id: str, session_id: str, payload: dict[str, Any], timeout_seconds: int | None = None) -> bytes:
        # We explicitly model "one prompt" through standard protocol lifecycle - we do NOT auto-retry.
        try:
            updates = []
            def capture_update(update: dict[str, Any]) -> None:
                updates.append(update)

            # Elicitation/Safety handlers explicit denial
            def handle_permission_request(req: Any) -> Any:
                return {"granted": False, "reason": "unsupported/denied"}
            def handle_file_request(req: Any) -> Any:
                return {"granted": False, "reason": "unsupported/denied"}
            def handle_terminal_request(req: Any) -> Any:
                return {"granted": False, "reason": "unsupported/denied"}
            def handle_elicitation(req: Any) -> Any:
                return {"granted": False, "reason": "unsupported/denied"}
            def handle_unknown_extension(req: Any) -> Any:
                return {"granted": False, "reason": "unsupported/denied"}

            raw_response = self.conn.prompt(
                session_id=session_id,
                payload=payload,
                timeout_seconds=timeout_seconds,
                on_update=capture_update,
                on_permission=handle_permission_request,
                on_file=handle_file_request,
                on_terminal=handle_terminal_request,
                on_elicitation=handle_elicitation,
                on_extension=handle_unknown_extension,
            )

            # Preserve raw sequence inside the byte return block if desired,
            # or just return the final raw_response bytes exactly. Core collects this raw.
            # To preserve evidence of updates, we will serialize them alongside the response,
            # or rely on the connection double capturing it.

            # Pack raw response + session updates to pass out through the mock relay
            if not isinstance(raw_response, dict):
                # if the mock returns bytes directly we just pass it
                if isinstance(raw_response, bytes):
                    return raw_response
                return str(raw_response).encode("utf-8")

            # Store the capture in the dict if it's a JSON-like object
            raw_response["_acp_session_updates"] = updates
            return json.dumps(raw_response).encode("utf-8")

        except TimeoutError:
            raise
        except Exception as e:
            raise RuntimeError(f"UNKNOWN: {str(e)}") from e

    def cancel(self, provider_id: str, session_id: str) -> None:
        self.conn.cancel(session_id)

    def close(self, provider_id: str, session_id: str) -> None:
        self.conn.close(session_id)
