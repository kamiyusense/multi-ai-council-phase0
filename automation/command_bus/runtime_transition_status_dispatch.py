"""Mockable Status workflow dispatch/readback coordinator.

This module deliberately contains no live GitHub transport.  A controller must
inject a transport that can list workflow runs, submit exactly one prepared
workflow_dispatch request, read one workflow run, and read Issue #33.

The coordinator never retries.  It snapshots run identities before dispatch,
performs at most one dispatch call, identifies exactly one new run after a
confirmed submission, verifies the terminal run result, and finally verifies
that Issue #33 reflects the expected durable Runtime projection.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .loop_status_issue import RUNTIME_END, RUNTIME_START, extract_managed_block
from .runtime_transition_status import PreparedStatusWorkflowCall

_STATUS_ISSUE = 33
_EXPECTED_WORKFLOW = ".github/workflows/loop-status-signal.yml"
_DISPLAY_ICONS = {
    "SEMI_AUTO": "🟢",
    "AUTO": "🟣",
    "IDLE": "🟡",
    "BLOCKED": "🔴",
    "STOPPED": "⚫",
}


@dataclass(frozen=True)
class StatusDispatchReadbackResult:
    status: str
    stage: str
    reason: str
    workflow_run_id: int | None = None


class StatusWorkflowTransport(Protocol):
    """Transport contract; production GitHub I/O is intentionally not provided."""

    def list_runs(self, workflow: str, code_ref: str) -> list[dict[str, Any]] | None: ...
    def dispatch(self, call: PreparedStatusWorkflowCall) -> str: ...
    def read_run(self, workflow_run_id: int) -> dict[str, Any] | None: ...


class StatusIssueReadback(Protocol):
    def read_issue(self, issue_number: int) -> dict[str, Any] | None: ...


class StatusWorkflowDispatchReadback:
    """Perform one bounded dispatch attempt followed by deterministic readback."""

    def __init__(self, transport: StatusWorkflowTransport, issue_reader: StatusIssueReadback):
        self.transport = transport
        self.issue_reader = issue_reader
        self._attempted: set[tuple[Any, ...]] = set()

    def execute(self, call: PreparedStatusWorkflowCall) -> StatusDispatchReadbackResult:
        try:
            self._validate_call(call)
        except (TypeError, ValueError) as exc:
            return StatusDispatchReadbackResult("BLOCKED", "validate", str(exc))

        identity = self._call_identity(call)
        if identity in self._attempted:
            return StatusDispatchReadbackResult(
                "BLOCKED",
                "replay_guard",
                "this exact Status dispatch was already attempted; retry=0",
            )

        try:
            before = self.transport.list_runs(call.workflow, call.code_ref)
            before_ids = self._run_ids(before)
        except Exception as exc:
            return StatusDispatchReadbackResult(
                "UNKNOWN", "pre_dispatch_readback", f"workflow run baseline unavailable: {exc}"
            )

        self._attempted.add(identity)
        dispatch_error: Exception | None = None
        try:
            dispatch_status = self.transport.dispatch(call)
        except Exception as exc:  # ambiguous send: read back once, never resend
            dispatch_status = "UNKNOWN"
            dispatch_error = exc

        try:
            after = self.transport.list_runs(call.workflow, call.code_ref)
            after_ids = self._run_ids(after)
        except Exception as exc:
            return StatusDispatchReadbackResult(
                "UNKNOWN",
                "run_identity",
                f"dispatch attempted once but workflow run readback failed; do not retry: {exc}",
            )

        new_ids = sorted(after_ids - before_ids)

        if dispatch_status != "ACCEPTED":
            observed = f"; observed new runs={new_ids}" if new_ids else ""
            detail = f": {dispatch_error}" if dispatch_error is not None else ""
            return StatusDispatchReadbackResult(
                "UNKNOWN",
                "dispatch",
                f"dispatch result is not independently confirmed{detail}{observed}; do not retry",
                new_ids[0] if len(new_ids) == 1 else None,
            )

        if len(new_ids) != 1:
            return StatusDispatchReadbackResult(
                "UNKNOWN",
                "run_identity",
                f"confirmed dispatch did not produce exactly one identifiable new workflow run: {new_ids}",
            )
        run_id = new_ids[0]

        try:
            run = self.transport.read_run(run_id)
            self._validate_run(run, run_id, call)
        except Exception as exc:
            return StatusDispatchReadbackResult(
                "UNKNOWN", "run_readback", f"workflow run identity/readback is unverifiable: {exc}", run_id
            )

        if run["status"] != "completed":
            return StatusDispatchReadbackResult(
                "UNKNOWN", "run_conclusion", "workflow run is not terminal; no polling/retry is performed", run_id
            )
        if run["conclusion"] != "success":
            return StatusDispatchReadbackResult(
                "BLOCKED",
                "run_conclusion",
                f"workflow completed without success: {run['conclusion']}",
                run_id,
            )

        try:
            issue = self.issue_reader.read_issue(_STATUS_ISSUE)
            self._validate_issue(issue, call)
        except Exception as exc:
            return StatusDispatchReadbackResult(
                "UNKNOWN",
                "issue_readback",
                f"Issue #33 does not prove the expected Status projection: {exc}",
                run_id,
            )

        return StatusDispatchReadbackResult(
            "VERIFIED",
            "issue_readback",
            "one Status workflow dispatch, terminal success, and exact Issue #33 projection were verified",
            run_id,
        )

    @staticmethod
    def _validate_call(call: PreparedStatusWorkflowCall) -> None:
        if not isinstance(call, PreparedStatusWorkflowCall):
            raise ValueError("PreparedStatusWorkflowCall is required")
        if call.workflow != _EXPECTED_WORKFLOW:
            raise ValueError("unexpected Status workflow")
        if call.code_ref != "main":
            raise ValueError("Status executable code ref must be main")
        if set(call.inputs) != {"loop_id", "state_ref"}:
            raise ValueError("Status workflow inputs must be exactly loop_id and state_ref")
        if call.inputs["loop_id"] == "" or call.inputs["state_ref"] in {"", "main", "master"}:
            raise ValueError("unsafe Status workflow inputs")
        if call.display_state not in _DISPLAY_ICONS:
            raise ValueError("invalid expected display state")
        if not isinstance(call.event_id, str) or not call.event_id:
            raise ValueError("event_id is required")
        if isinstance(call.generation, bool) or not isinstance(call.generation, int) or call.generation < 1:
            raise ValueError("invalid generation")

    @staticmethod
    def _call_identity(call: PreparedStatusWorkflowCall) -> tuple[Any, ...]:
        return (
            call.workflow,
            call.code_ref,
            call.inputs["loop_id"],
            call.inputs["state_ref"],
            call.event_id,
            call.generation,
            call.display_state,
            call.transition_status,
        )

    @staticmethod
    def _run_ids(runs: list[dict[str, Any]] | None) -> set[int]:
        if not isinstance(runs, list):
            raise ValueError("workflow run list unavailable")
        result: set[int] = set()
        for run in runs:
            if not isinstance(run, dict):
                raise ValueError("workflow run list entry malformed")
            run_id = run.get("id", run.get("workflow_run_id"))
            if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id < 1:
                raise ValueError("workflow run id unavailable")
            if run_id in result:
                raise ValueError("duplicate workflow run id")
            result.add(run_id)
        return result

    @staticmethod
    def _validate_run(run: dict[str, Any] | None, run_id: int, call: PreparedStatusWorkflowCall) -> None:
        if not isinstance(run, dict):
            raise ValueError("workflow run missing")
        observed_id = run.get("id", run.get("workflow_run_id"))
        if observed_id != run_id:
            raise ValueError("workflow run id mismatch")
        path = run.get("path", run.get("workflow"))
        if path != call.workflow:
            raise ValueError("workflow path mismatch")
        event = run.get("event")
        if event != "workflow_dispatch":
            raise ValueError("workflow event mismatch")
        code_ref = run.get("head_branch", run.get("code_ref"))
        if code_ref != call.code_ref:
            raise ValueError("workflow code ref mismatch")
        attempt = run.get("run_attempt")
        if attempt != 1:
            raise ValueError("workflow rerun/retry is forbidden")
        if run.get("status") not in {"queued", "in_progress", "completed"}:
            raise ValueError("workflow status unavailable")
        if run.get("status") == "completed" and not isinstance(run.get("conclusion"), str):
            raise ValueError("workflow conclusion unavailable")

    @staticmethod
    def _validate_issue(issue: dict[str, Any] | None, call: PreparedStatusWorkflowCall) -> None:
        if not isinstance(issue, dict):
            raise ValueError("Issue readback unavailable")
        if issue.get("number", issue.get("issue_number")) != _STATUS_ISSUE:
            raise ValueError("Issue identity mismatch")
        if issue.get("state") != "open":
            raise ValueError("Status Issue is not open")
        icon = _DISPLAY_ICONS[call.display_state]
        expected_title = f"🚦 Phase 0 Loop Status — {icon} {call.display_state}"
        if issue.get("title") != expected_title:
            raise ValueError("Issue title projection mismatch")
        body = issue.get("body")
        if not isinstance(body, str):
            raise ValueError("Issue body unavailable")
        runtime = extract_managed_block(body, RUNTIME_START, RUNTIME_END)
        if runtime is None:
            raise ValueError("Runtime managed block missing")
        required = (
            f"# {icon} Runtime: {call.display_state}",
            f"- Loop: `{call.inputs['loop_id']}`",
            f"- Last durable progress: `generation {call.generation}; receipt {call.event_id}`",
        )
        if any(fragment not in runtime for fragment in required):
            raise ValueError("Runtime managed block projection mismatch")
