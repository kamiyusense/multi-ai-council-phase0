from __future__ import annotations

import unittest

from automation.command_bus.loop_status_issue import RUNTIME_END, RUNTIME_START
from automation.command_bus.runtime_transition_coordinator import StatusRefreshPlan
from automation.command_bus.runtime_transition_status import prepare_status_workflow_call
from automation.command_bus.runtime_transition_status_dispatch import StatusWorkflowDispatchReadback


def prepared(**changes):
    values = {
        "loop_id": "loop-015",
        "state_ref": "runtime-ledger",
        "event_id": "receipt-owner-2",
        "generation": 2,
        "display_state": "IDLE",
        "transition_status": "TERMINAL",
    }
    values.update(changes)
    return prepare_status_workflow_call(StatusRefreshPlan(**values))


def run(run_id=102, **changes):
    value = {
        "id": run_id,
        "path": ".github/workflows/loop-status-signal.yml",
        "event": "workflow_dispatch",
        "head_branch": "main",
        "run_attempt": 1,
        "status": "completed",
        "conclusion": "success",
    }
    value.update(changes)
    return value


def issue(call=None, **changes):
    call = call or prepared()
    icon = {
        "SEMI_AUTO": "🟢",
        "AUTO": "🟣",
        "IDLE": "🟡",
        "BLOCKED": "🔴",
        "STOPPED": "⚫",
    }[call.display_state]
    body = (
        f"{RUNTIME_START}\n"
        f"# {icon} Runtime: {call.display_state}\n\n"
        f"- Loop: `{call.inputs['loop_id']}`\n"
        f"- Last durable progress: `generation {call.generation}; receipt {call.event_id}`\n"
        f"{RUNTIME_END}\n"
    )
    value = {
        "number": 33,
        "state": "open",
        "title": f"🚦 Phase 0 Loop Status — {icon} {call.display_state}",
        "body": body,
    }
    value.update(changes)
    return value


class Transport:
    def __init__(self, *, before=None, after=None, dispatch_status="ACCEPTED", dispatch_exc=None, run_value=None):
        self.before = list(before if before is not None else [{"id": 101}])
        self.after = list(after if after is not None else [{"id": 101}, {"id": 102}])
        self.dispatch_status = dispatch_status
        self.dispatch_exc = dispatch_exc
        self.run_value = run_value if run_value is not None else run()
        self.list_calls = 0
        self.dispatch_calls = 0
        self.read_calls = 0

    def list_runs(self, workflow, code_ref):
        self.list_calls += 1
        return self.before if self.list_calls == 1 else self.after

    def dispatch(self, call):
        self.dispatch_calls += 1
        if self.dispatch_exc:
            raise self.dispatch_exc
        return self.dispatch_status

    def read_run(self, workflow_run_id):
        self.read_calls += 1
        return self.run_value


class IssueReader:
    def __init__(self, value=None):
        self.value = value if value is not None else issue()
        self.calls = 0

    def read_issue(self, issue_number):
        self.calls += 1
        return self.value


class StatusWorkflowDispatchReadbackTests(unittest.TestCase):
    def test_verified_one_dispatch_run_and_issue_projection(self):
        transport = Transport()
        reader = IssueReader()
        result = StatusWorkflowDispatchReadback(transport, reader).execute(prepared())
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(result.workflow_run_id, 102)
        self.assertEqual(transport.dispatch_calls, 1)
        self.assertEqual(transport.list_calls, 2)
        self.assertEqual(transport.read_calls, 1)
        self.assertEqual(reader.calls, 1)

    def test_ambiguous_dispatch_reads_back_but_never_promotes_or_retries(self):
        transport = Transport(dispatch_exc=TimeoutError("ambiguous"))
        reader = IssueReader()
        adapter = StatusWorkflowDispatchReadback(transport, reader)
        result = adapter.execute(prepared())
        self.assertEqual(result.status, "UNKNOWN")
        self.assertEqual(result.stage, "dispatch")
        self.assertEqual(result.workflow_run_id, 102)
        self.assertEqual(transport.dispatch_calls, 1)
        self.assertEqual(transport.list_calls, 2)
        self.assertEqual(transport.read_calls, 0)
        self.assertEqual(reader.calls, 0)
        again = adapter.execute(prepared())
        self.assertEqual(again.status, "BLOCKED")
        self.assertEqual(again.stage, "replay_guard")
        self.assertEqual(transport.dispatch_calls, 1)

    def test_missing_or_multiple_new_run_is_unknown_without_issue_read(self):
        for after in ([{"id": 101}], [{"id": 101}, {"id": 102}, {"id": 103}]):
            transport = Transport(after=after)
            reader = IssueReader()
            result = StatusWorkflowDispatchReadback(transport, reader).execute(prepared())
            self.assertEqual(result.status, "UNKNOWN")
            self.assertEqual(result.stage, "run_identity")
            self.assertEqual(transport.dispatch_calls, 1)
            self.assertEqual(transport.read_calls, 0)
            self.assertEqual(reader.calls, 0)

    def test_run_identity_retry_or_nonterminal_is_unknown(self):
        variants = (
            run(path=".github/workflows/other.yml"),
            run(event="push"),
            run(head_branch="feature/x"),
            run(run_attempt=2),
            run(status="in_progress", conclusion=None),
        )
        for value in variants:
            transport = Transport(run_value=value)
            reader = IssueReader()
            result = StatusWorkflowDispatchReadback(transport, reader).execute(prepared())
            self.assertEqual(result.status, "UNKNOWN")
            self.assertEqual(reader.calls, 0)

    def test_failed_workflow_blocks_without_issue_read(self):
        transport = Transport(run_value=run(conclusion="failure"))
        reader = IssueReader()
        result = StatusWorkflowDispatchReadback(transport, reader).execute(prepared())
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.stage, "run_conclusion")
        self.assertEqual(reader.calls, 0)

    def test_issue_title_runtime_state_loop_and_progress_must_match(self):
        call = prepared()
        variants = (
            issue(call, title="wrong"),
            issue(call, body=f"{RUNTIME_START}\n# 🟡 Runtime: IDLE\n{RUNTIME_END}\n"),
            issue(call, state="closed"),
            issue(call, number=34),
        )
        for value in variants:
            transport = Transport()
            reader = IssueReader(value)
            result = StatusWorkflowDispatchReadback(transport, reader).execute(call)
            self.assertEqual(result.status, "UNKNOWN")
            self.assertEqual(result.stage, "issue_readback")

    def test_invalid_prepared_call_blocks_before_transport(self):
        transport = Transport()
        reader = IssueReader()
        result = StatusWorkflowDispatchReadback(transport, reader).execute("not-a-call")
        self.assertEqual(result.status, "BLOCKED")
        self.assertEqual(result.stage, "validate")
        self.assertEqual(transport.list_calls, 0)
        self.assertEqual(transport.dispatch_calls, 0)
        self.assertEqual(reader.calls, 0)


if __name__ == "__main__":
    unittest.main()
