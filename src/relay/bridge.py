from __future__ import annotations

from typing import Any

from src.phase0_core.adapter import CoreProviderAdapter


class RelayProviderAdapterBridge(CoreProviderAdapter):
    """Static/mock bridge; never starts a live provider."""

    def __init__(self, *, simulate_timeout=False, simulate_failure=False,
                 simulate_malformed=False, simulate_unknown=False,
                 simulate_no_cli=False, simulate_error_in_collect=False):
        self.simulate_timeout = simulate_timeout
        self.simulate_failure = simulate_failure
        self.simulate_malformed = simulate_malformed
        self.simulate_unknown = simulate_unknown
        self.simulate_no_cli = simulate_no_cli
        self.simulate_error_in_collect = simulate_error_in_collect
        self.dispatch_count = 0
        self.collect_count = 0
        self.abort_calls: list[tuple[str, str]] = []

    def prepare(self, case_context: dict[str, Any]) -> dict[str, Any]:
        return {"case_id": case_context.get("case_id"),
                "provider_id": case_context.get("provider_id"),
                "session_id": case_context.get("session_id"),
                "payload": case_context.get("payload", {})}

    def preflight(self, prepared_context: dict[str, Any]) -> dict[str, Any]:
        if self.simulate_no_cli:
            raise RuntimeError("CLI unavailable")
        return {"ok": True, "live_ready": False}

    def dispatch(self, prepared_context: dict[str, Any]) -> dict[str, Any]:
        if self.simulate_failure:
            raise RuntimeError("Mock failure on dispatch")
        self.dispatch_count += 1
        return {
            "process_id": "mock_id",
            "provider_id": prepared_context.get("provider_id"),
            "session_id": prepared_context.get("session_id"),
            "live_process_started": False,
        }

    def collect(self, process_handle: dict[str, Any]) -> dict[str, Any]:
        self.collect_count += 1
        if self.simulate_timeout:
            raise TimeoutError("Timeout")
        if self.simulate_error_in_collect:
            raise RuntimeError("Mock collect error")
        if self.simulate_malformed:
            return {"stdout": "malformed", "rawResponse": "{}"}
        if self.simulate_unknown:
            return {"stdout": "unknown", "rawResponse": None}
        return {"stdout": "mock", "rawResponse": '{"answer_state":"ANSWER"}'}

    def abort(self, process_handle: dict[str, Any]) -> dict[str, bool]:
        self.abort_calls.append(
            (process_handle.get("provider_id"), process_handle.get("session_id"))
        )
        return {"aborted": True}

    def classify(self, raw_result: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(raw_result, dict) or raw_result.get("rawResponse") is None:
            return {"execution_state": "UNKNOWN", "success": False}
        if raw_result.get("stdout") == "malformed":
            return {"execution_state": "INVALID_OUTPUT", "success": False}
        return {"execution_state": "COMPLETE", "participation_state": "PARTICIPANT",
                "success": True, "rawResponse": raw_result["rawResponse"]}
