from __future__ import annotations

import json
import unittest
from dataclasses import dataclass
from pathlib import Path

from automation.command_bus.executor_backend import ExecutorContent, GitHubExecutorBackend
from automation.command_bus.jules_api_closed_loop import GitHubCommandBusBackend, JulesApiClosedLoop

HERE = Path(__file__).resolve().parents[1]
HIST = json.loads((HERE / "fixtures" / "jules_api_smoke_20260925.json").read_text())
REPO = HIST["repository"]
BRANCH = HIST["starting_branch"]
HEAD = HIST["target_before"]["head"]
TREE = HIST["target_before"]["tree"]
RESULT = HIST["publication"]["resulting_commit"]
RESULT_TREE = HIST["publication"]["result_tree"]
PATH = HIST["publication"]["changed_paths"][0]["path"]
LOOP = "jules-api-closed-loop-fixture-001"
COMMAND_ID = LOOP + "-000001"


def command(**changes):
    value = {
        "schema_version": 1, "command_id": COMMAND_ID, "loop_id": LOOP, "round": 1,
        "correlation_id": LOOP + "-round-1", "target": "work", "action": "JULES_API_CLOSED_LOOP",
        "expected_repo": REPO, "expected_pr": 4, "expected_target_head": HEAD,
        "expected_target_tree": TREE, "starting_branch": BRANCH,
        "allowed_paths": [PATH], "path_policy": [{"path": PATH, "allowed_ops": ["MODIFY"]}],
        "requires_live_model": True, "requires_github_write": True,
        "retry": 0, "fallback": "disabled", "expires_at": "2099-01-01T00:00:00+00:00",
    }
    value.update(changes); return value


def state(**changes):
    value = {"schema_version": 1, "loop_id": LOOP, "state": "RUNNING", "round": 0,
             "max_rounds": 6, "expires_at": "2099-01-01T00:00:00+00:00", "stop_requested": False,
             "last_command_id": COMMAND_ID, "last_receipt_id": None, "expected_target": "work", "retry_policy": 0}
    value.update(changes); return value


def target(**changes):
    value = {"repository": REPO, "pr_number": 4, "branch": BRANCH, "default_branch": "main", "head": HEAD, "tree": TREE}
    value.update(changes); return value


def submission(**changes):
    value = {"status": "SUBMITTED", "ambiguous": False, "repository": REPO,
             "workflow_run_id": HIST["workflow"]["run_id"], "session_id": HIST["jules"]["session_id"],
             "starting_branch": BRANCH, "task_submitted": True, "retry_count": 0, "fallback_used": False}
    value.update(changes); return value


def publication(**changes):
    h = HIST["publication"]
    value = {"repository": REPO, "workflow_run_id": HIST["workflow"]["run_id"],
             "session_id": HIST["jules"]["session_id"], "starting_branch": BRANCH,
             "resulting_commit": RESULT, "result_tree": RESULT_TREE, "parent_shas": [HEAD],
             "merge_base": HEAD, "ahead_by": 1, "behind_by": 0, "pr_number": h["pr_number"],
             "pr_base_branch": BRANCH, "changed_paths": [{"path": PATH, "operation": "MODIFY", "symlink": False}],
             "tests_passed": True, "compileall_passed": True, "diff_check_passed": True,
             "retry_count": 0, "fallback_used": False, "task_submitted": True,
             "jules_task_started": True, "model_started": True,
             "github_mutation_uncertainty": False, "main_direct_write": False}
    value.update(changes); return value


class FakeContents:
    def __init__(self): self.files, self.n = {}, 0
    def seed(self, path, value): self.n += 1; self.files[path] = ExecutorContent(path, json.dumps(value, sort_keys=True, separators=(",", ":")), f"s{self.n}")
    def get(self, path, ref): return self.files.get(path)
    def list(self, prefix, ref): return [v for k, v in self.files.items() if k.startswith(prefix)]
    def create(self, path, text, message, branch):
        if path in self.files: raise RuntimeError("exists")
        self.n += 1; self.files[path] = ExecutorContent(path, text, f"s{self.n}"); return self.files[path]
    def update(self, path, text, sha, message, branch):
        current = self.files.get(path)
        if current is None or current.sha != sha: raise RuntimeError("stale")
        self.n += 1; self.files[path] = ExecutorContent(path, text, f"s{self.n}"); return self.files[path]


class TargetReader:
    def __init__(self, *values): self.values, self.calls = list(values) or [target()], 0
    def read_target(self, repository, pr_number):
        i = min(self.calls, len(self.values) - 1); self.calls += 1; return dict(self.values[i])


class Workflow:
    def __init__(self, value=None, exc=None): self.value, self.exc, self.calls = value or submission(), exc, 0
    def submit(self, command, reservation):
        self.calls += 1
        if self.exc: raise self.exc
        return dict(self.value)


class Publications:
    def __init__(self, values=None): self.values = [publication()] if values is None else values
    def find_candidates(self, command, submission): return self.values


class FastForward:
    def __init__(self, *, readback=RESULT, status="WRITTEN", exc=None): self.readback, self.status, self.exc, self.write_calls = readback, status, exc, 0
    def fast_forward(self, **kwargs):
        self.write_calls += 1
        if self.exc: raise self.exc
        return {"status": self.status}
    def read_head(self, branch): return self.readback


def build(*, cmd=None, targets=None, sub=None, candidates=None, ff=None, seed_terminal=False, duplicate_reservation=False):
    cmd = cmd or command(); client = FakeContents(); client.seed(f"commands/{LOOP}/000001.json", cmd); client.seed(f"state/{LOOP}.json", state())
    if seed_terminal:
        client.seed(f"receipts/{LOOP}/000001.json", {"schema_version": 1, "receipt_id": f"{LOOP}/000001", "command_id": COMMAND_ID,
            "loop_id": LOOP, "correlation_id": cmd["correlation_id"], "state": "DONE", "executed_once": True,
            "retry_count": 0, "fallback_used": False, "evidence_refs": []})
    durable = GitHubCommandBusBackend(client, branch="feature/chat-work-command-bus")
    ledger = durable.load_ledger(loop_id=LOOP, round_number=1, command_id=COMMAND_ID)
    reservations = GitHubExecutorBackend(client, branch="feature/chat-work-command-bus")
    if duplicate_reservation:
        reservations.append("request", LOOP, JulesApiClosedLoop._reservation(cmd))
    workflow = Workflow(sub); fast = ff or FastForward()
    runner = JulesApiClosedLoop(ledger=ledger, target_reader=TargetReader(*(targets or [target(), target()])),
        reservation_backend=reservations, workflow_adapter=workflow, publication_reader=Publications(candidates),
        fast_forward_adapter=fast, terminal_backend=durable)
    return runner, ledger, client, workflow, fast, durable


class JulesApiClosedLoopTests(unittest.TestCase):
    def test_history_fixture_is_not_runtime_constant(self):
        self.assertFalse(HIST["runtime_fixed_values"]); self.assertEqual(HIST["workflow"]["run_id"], 36123668456)

    def test_pass_closes_loop_and_recovery_is_noop(self):
        runner, ledger, client, workflow, ff, durable = build()
        result = runner.run(COMMAND_ID)
        self.assertEqual(result.status, "COMPLETE"); self.assertEqual(workflow.calls, 1); self.assertEqual(ff.write_calls, 1)
        self.assertEqual(ledger.state["state"], "COMPLETE")
        receipt = json.loads(client.get(f"receipts/{LOOP}/000001.json", "x").text)
        self.assertEqual(receipt["state"], "DONE"); self.assertEqual(receipt["outcome"], "COMPLETE")
        recovered = durable.load_ledger(loop_id=LOOP, round_number=1, command_id=COMMAND_ID)
        again = JulesApiClosedLoop(ledger=recovered, target_reader=TargetReader(), reservation_backend=GitHubExecutorBackend(client, branch="x"),
            workflow_adapter=Workflow(), publication_reader=Publications(), fast_forward_adapter=FastForward())
        self.assertEqual(again.run(COMMAND_ID).status, "NO-OP")

    def test_stale_head_and_tree_block_before_submit(self):
        for t in (target(head="f"*40), target(tree="e"*40)):
            runner, _, _, workflow, ff, _ = build(targets=[t])
            self.assertEqual(runner.run(COMMAND_ID).status, "BLOCKED"); self.assertEqual(workflow.calls, 0); self.assertEqual(ff.write_calls, 0)

    def test_target_becomes_stale_immediately_before_write(self):
        runner, _, _, workflow, ff, _ = build(targets=[target(), target(head="d"*40)])
        self.assertEqual(runner.run(COMMAND_ID).status, "BLOCKED"); self.assertEqual(workflow.calls, 1); self.assertEqual(ff.write_calls, 0)

    def test_parent_base_merge_base_mismatch_block(self):
        for p in (publication(parent_shas=["c"*40]), publication(pr_base_branch="main"), publication(merge_base="b"*40)):
            self.assertEqual(build(candidates=[p])[0].run(COMMAND_ID).status, "BLOCKED")

    def test_unrelated_delete_rename_and_inexact_path_set_block(self):
        variants = [
            [{"path": "src/relay/dispatcher.py", "operation": "MODIFY"}],
            [{"path": PATH, "operation": "DELETE"}],
            [{"path": PATH, "operation": "RENAME"}],
            [{"path": PATH, "operation": "MODIFY"}, {"path": "README.md", "operation": "MODIFY"}],
        ]
        for changed in variants:
            self.assertEqual(build(candidates=[publication(changed_paths=changed)])[0].run(COMMAND_ID).status, "BLOCKED")

    def test_test_failure_and_unknown(self):
        self.assertEqual(build(candidates=[publication(tests_passed=False)])[0].run(COMMAND_ID).status, "BLOCKED")
        self.assertEqual(build(candidates=[publication(tests_passed=None)])[0].run(COMMAND_ID).status, "UNKNOWN")

    def test_duplicate_reservation_blocks_without_submit(self):
        runner, _, _, workflow, ff, _ = build(duplicate_reservation=True)
        self.assertEqual(runner.run(COMMAND_ID).status, "BLOCKED"); self.assertEqual(workflow.calls, 0); self.assertEqual(ff.write_calls, 0)

    def test_terminal_receipt_is_noop(self):
        runner, *_ = build(seed_terminal=True); self.assertEqual(runner.run(COMMAND_ID).status, "NO-OP")

    def test_submit_ambiguity_is_unknown_and_not_resent(self):
        runner, _, _, workflow, ff, _ = build(sub=submission(status="UNKNOWN", ambiguous=True))
        self.assertEqual(runner.run(COMMAND_ID).status, "UNKNOWN"); self.assertEqual(workflow.calls, 1); self.assertEqual(ff.write_calls, 0)

    def test_missing_or_multiple_publications_are_unknown(self):
        self.assertEqual(build(candidates=[])[0].run(COMMAND_ID).status, "UNKNOWN")
        self.assertEqual(build(candidates=[publication(), publication(pr_number=11)])[0].run(COMMAND_ID).status, "UNKNOWN")

    def test_fast_forward_ambiguity_requires_readback_and_never_resends(self):
        ff = FastForward(readback=HEAD, status="UNKNOWN")
        result = build(ff=ff)[0].run(COMMAND_ID)
        self.assertEqual(result.status, "UNKNOWN"); self.assertEqual(ff.write_calls, 1)
        ff = FastForward(readback=RESULT, exc=RuntimeError("timeout"))
        result = build(ff=ff)[0].run(COMMAND_ID)
        self.assertEqual(result.status, "COMPLETE"); self.assertEqual(ff.write_calls, 1)

    def test_main_write_attempt_blocks(self):
        cmd = command(starting_branch="main")
        runner, _, _, workflow, ff, _ = build(cmd=cmd, targets=[target(branch="main", default_branch="main")])
        self.assertEqual(runner.run(COMMAND_ID).status, "BLOCKED"); self.assertEqual(workflow.calls, 0); self.assertEqual(ff.write_calls, 0)

    def test_retry_and_fallback_policy_block(self):
        for key, value in (("retry", 1), ("fallback", True)):
            runner, ledger, _, workflow, _, _ = build(); ledger.commands[0][key] = value
            self.assertEqual(runner.run(COMMAND_ID).status, "BLOCKED"); self.assertEqual(workflow.calls, 0)
        for sub in (submission(retry_count=1), submission(fallback_used=True)):
            self.assertEqual(build(sub=sub)[0].run(COMMAND_ID).status, "BLOCKED")
        for p in (publication(retry_count=1), publication(fallback_used=True)):
            self.assertEqual(build(candidates=[p])[0].run(COMMAND_ID).status, "BLOCKED")

    def test_exact_branch_required_at_submit_and_publication(self):
        self.assertEqual(build(sub=submission(starting_branch="main"))[0].run(COMMAND_ID).status, "BLOCKED")
        self.assertEqual(build(candidates=[publication(starting_branch="main")])[0].run(COMMAND_ID).status, "BLOCKED")

    def test_publication_identity_and_correlation_required(self):
        for p in (publication(resulting_commit=None), publication(result_tree=None), publication(pr_number=None), publication(session_id="other")):
            self.assertEqual(build(candidates=[p])[0].run(COMMAND_ID).status, "UNKNOWN")

    def test_ancestry_must_be_one_clean_child(self):
        for p in (publication(ahead_by=2), publication(behind_by=1)):
            self.assertEqual(build(candidates=[p])[0].run(COMMAND_ID).status, "BLOCKED")

    def test_main_direct_write_and_mutation_uncertainty_gate(self):
        self.assertEqual(build(candidates=[publication(main_direct_write=True)])[0].run(COMMAND_ID).status, "BLOCKED")
        self.assertEqual(build(candidates=[publication(github_mutation_uncertainty="UNKNOWN")])[0].run(COMMAND_ID).status, "UNKNOWN")


if __name__ == "__main__":
    unittest.main()
