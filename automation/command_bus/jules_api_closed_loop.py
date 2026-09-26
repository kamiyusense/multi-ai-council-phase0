"""Thin mockable connector for the durable Jules API closed loop.

No live GitHub Actions/Jules transport is implemented here.  Existing command
bus persistence, executor reservation, publication gates, and retry=0 semantics
are composed behind injected adapters.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Protocol

from .executor import make_executor_request
from .executor_backend import ExecutorContentsClient
from .jules_publication import PublicationState, fast_forward_allowed, validate_jules_publication
from .ledger import InMemoryLedger
from .state_machine import StateMachine
from .validator import validate_command, validate_receipt, validate_state


@dataclass(frozen=True)
class ClosedLoopResult:
    status: str
    reason: str
    receipt: dict[str, Any] | None = None


@dataclass(frozen=True)
class PersistenceResult:
    status: str
    reason: str


class TargetReadback(Protocol):
    def read_target(self, repository: str, pr_number: int) -> dict[str, Any] | None: ...


class DispatchReservationBackend(Protocol):
    def append(self, kind: str, loop_id: str, record: dict[str, Any]) -> Any: ...


class JulesWorkflowAdapter(Protocol):
    def submit(self, command: dict[str, Any], reservation: dict[str, Any]) -> dict[str, Any]: ...


class JulesPublicationReadback(Protocol):
    def find_candidates(self, command: dict[str, Any], submission: dict[str, Any]) -> list[dict[str, Any]] | None: ...


class FastForwardAdapter(Protocol):
    def fast_forward(self, *, branch: str, expected_head: str, resulting_commit: str) -> dict[str, Any]: ...
    def read_head(self, branch: str) -> str | None: ...


class TerminalPersistence(Protocol):
    def persist_terminal(self, receipt: dict[str, Any], state: dict[str, Any]) -> PersistenceResult: ...


def command_record_path(loop_id: str, round_number: int) -> str:
    return f"commands/{loop_id}/{round_number:06d}.json"


def receipt_record_path(loop_id: str, round_number: int) -> str:
    return f"receipts/{loop_id}/{round_number:06d}.json"


def loop_state_path(loop_id: str) -> str:
    return f"state/{loop_id}.json"


class GitHubCommandBusBackend:
    """Read/write the existing command/state/receipt layout without retrying."""

    def __init__(self, client: ExecutorContentsClient, *, branch: str, ref: str | None = None):
        self.client, self.branch, self.ref = client, branch, ref or branch

    def load_ledger(self, *, loop_id: str, round_number: int, command_id: str | None = None) -> InMemoryLedger:
        s = self.client.get(loop_state_path(loop_id), self.ref)
        c = self.client.get(command_record_path(loop_id, round_number), self.ref)
        if s is None or c is None:
            raise ValueError("durable command/state missing")
        state, command = json.loads(s.text), json.loads(c.text)
        validate_state(state); validate_command(command)
        if state.get("loop_id") != loop_id or command.get("loop_id") != loop_id or command.get("round") != round_number:
            raise ValueError("durable command/state identity mismatch")
        if command_id is not None and command.get("command_id") != command_id:
            raise ValueError("durable command identity mismatch")
        ledger = InMemoryLedger(state); ledger.add_command(command)
        r = self.client.get(receipt_record_path(loop_id, round_number), self.ref)
        if r is not None:
            receipt = json.loads(r.text); validate_receipt(receipt)
            if receipt.get("loop_id") != loop_id or receipt.get("command_id") != command["command_id"]:
                raise ValueError("durable receipt identity mismatch")
            ledger.add_receipt(receipt)
        return ledger

    def persist_terminal(self, receipt: dict[str, Any], state: dict[str, Any]) -> PersistenceResult:
        try:
            validate_receipt(receipt); validate_state(state)
            loop_id, round_number = receipt["loop_id"], receipt.get("round")
            if not isinstance(round_number, int) or round_number < 1 or state.get("loop_id") != loop_id:
                raise ValueError("terminal identity mismatch")
            rp = receipt_record_path(loop_id, round_number); rt = _canonical(receipt)
            if self.client.get(rp, self.branch) is None:
                try: self.client.create(rp, rt, f"append command receipt {receipt['receipt_id']}", self.branch)
                except Exception: pass  # ambiguous create: read back, never resend
            rr = self.client.get(rp, self.branch)
            if rr is None or _json(rr.text) != receipt:
                return PersistenceResult("UNKNOWN", "terminal receipt write/readback unresolved")
            sp = loop_state_path(loop_id); st = _canonical(state); current = self.client.get(sp, self.branch)
            if current is None:
                return PersistenceResult("UNKNOWN", "mutable state missing")
            if _json(current.text) != state:
                try: self.client.update(sp, st, current.sha, f"update command state {loop_id}", self.branch)
                except Exception: pass  # ambiguous update: read back, never resend
            sr = self.client.get(sp, self.branch)
            if sr is None or _json(sr.text) != state:
                return PersistenceResult("UNKNOWN", "state write/readback unresolved")
            return PersistenceResult("ACCEPTED", "terminal receipt/state verified")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return PersistenceResult("UNKNOWN", str(exc))


class JulesApiClosedLoop:
    def __init__(self, *, ledger: InMemoryLedger, target_reader: TargetReadback,
                 reservation_backend: DispatchReservationBackend,
                 workflow_adapter: JulesWorkflowAdapter,
                 publication_reader: JulesPublicationReadback,
                 fast_forward_adapter: FastForwardAdapter,
                 terminal_backend: TerminalPersistence | None = None):
        self.ledger, self.target_reader = ledger, target_reader
        self.reservation_backend, self.workflow_adapter = reservation_backend, workflow_adapter
        self.publication_reader, self.fast_forward_adapter = publication_reader, fast_forward_adapter
        self.terminal_backend = terminal_backend

    def run(self, command_id: str) -> ClosedLoopResult:
        terminal = self.ledger.terminal_for(command_id)
        if terminal: return ClosedLoopResult("NO-OP", "terminal receipt already exists", terminal)
        command = next((c for c in self.ledger.commands if c.get("command_id") == command_id), None)
        if command is None: return ClosedLoopResult("NO-OP", "command not found")
        try:
            validate_command(command); self._validate_command(command)
            sm = StateMachine(self.ledger.state)
            if sm.mark_expired(): return self._terminal(command, "BLOCKED", "expired", False)
            if (reason := sm.blocked_reason()): return self._terminal(command, "BLOCKED", reason, False)
        except (ValueError, TypeError, KeyError) as exc:
            return self._terminal(command, "BLOCKED", str(exc), False)

        target = self._target(command)
        if isinstance(target, ClosedLoopResult): return target
        if (problem := self._target_problem(command, target)):
            return self._terminal(command, *problem, False, head=target.get("head"))

        reservation = self._reservation(command)
        try: reserved = self.reservation_backend.append("request", command["loop_id"], reservation)
        except Exception as exc: return self._terminal(command, "UNKNOWN", f"dispatch reservation failed: {exc}", False, head=target["head"])
        if reserved.status == "BLOCKED": return self._terminal(command, "BLOCKED", "duplicate dispatch reservation; dispatch not repeated", False, head=target["head"])
        if reserved.status != "ACCEPTED": return self._terminal(command, "UNKNOWN", f"dispatch reservation unavailable: {reserved.reason}", False, head=target["head"])

        try: submission = self.workflow_adapter.submit(command, reservation)
        except Exception as exc: return self._terminal(command, "UNKNOWN", f"workflow submit ambiguity; do not resend: {exc}", True, head=target["head"])
        if (problem := self._submission_problem(command, submission)):
            return self._terminal(command, *problem, True, head=target["head"])

        try: candidates = self.publication_reader.find_candidates(command, submission)
        except Exception as exc: return self._terminal(command, "UNKNOWN", f"publication readback failed: {exc}", True, head=target["head"])
        if candidates is None or len(candidates) != 1:
            reason = "publication readback unavailable" if candidates is None else ("Jules result not found" if len(candidates) == 0 else "multiple candidate Jules results")
            return self._terminal(command, "UNKNOWN", reason, True, head=target["head"])
        publication = candidates[0]
        if (problem := self._publication_problem(command, submission, publication)):
            return self._terminal(command, *problem, True, head=target["head"])

        decision = validate_jules_publication(
            expected_target_head=command["expected_target_head"], current_target_head=target.get("head"),
            resulting_commit=publication.get("resulting_commit"), parent_shas=publication.get("parent_shas"),
            comparison_base_branch=publication.get("pr_base_branch"), expected_base_branch=command["starting_branch"],
            changed_paths=publication.get("changed_paths"), allowed_paths=set(command["allowed_paths"]),
            tests_passed=publication.get("tests_passed"), compileall_passed=publication.get("compileall_passed"),
            diff_check_passed=publication.get("diff_check_passed"), retry_count=publication.get("retry_count"),
            fallback_used=publication.get("fallback_used"), task_submitted=publication.get("task_submitted"),
            jules_task_started=publication.get("jules_task_started"), model_started=publication.get("model_started"),
            github_mutation_uncertainty=publication.get("github_mutation_uncertainty"), main_direct_write=publication.get("main_direct_write"),
        )
        if decision.state is not PublicationState.PASS:
            return self._terminal(command, decision.state.value, decision.reason, True, head=target["head"])

        fresh = self._target(command)
        if isinstance(fresh, ClosedLoopResult): return fresh
        if (problem := self._target_problem(command, fresh)):
            return self._terminal(command, *problem, True, head=fresh.get("head"))
        ff = fast_forward_allowed(decision, current_target_head=fresh["head"], expected_target_head=command["expected_target_head"],
                                  resulting_commit=publication["resulting_commit"], ancestry_is_fast_forward=self._ff_ancestry(command, publication))
        if ff.state is not PublicationState.PASS:
            return self._terminal(command, ff.state.value, ff.reason, True, head=fresh["head"])

        try: write = self.fast_forward_adapter.fast_forward(branch=command["starting_branch"], expected_head=command["expected_target_head"], resulting_commit=publication["resulting_commit"])
        except Exception: write = {"status": "UNKNOWN"}
        try: readback = self.fast_forward_adapter.read_head(command["starting_branch"])
        except Exception: readback = None
        if readback != publication["resulting_commit"]:
            return self._terminal(command, "UNKNOWN", "fast-forward write not proven by readback; do not resend", True, head=readback)
        if not isinstance(write, dict) or write.get("status") not in {"WRITTEN", "UNKNOWN"}:
            return self._terminal(command, "UNKNOWN", "fast-forward adapter result malformed", True, head=readback)
        refs = [f"workflow-run:{submission['workflow_run_id']}", f"jules-session:{submission['session_id']}",
                f"result-commit:{publication['resulting_commit']}", f"result-tree:{publication['result_tree']}"]
        return self._terminal(command, "DONE", "closed-loop publication complete", True, head=readback, evidence_refs=refs, outcome="COMPLETE")

    def _target(self, command: dict[str, Any]) -> dict[str, Any] | ClosedLoopResult:
        try: value = self.target_reader.read_target(command["expected_repo"], command["expected_pr"])
        except Exception as exc: return self._terminal(command, "UNKNOWN", f"target readback failed: {exc}", False)
        if not isinstance(value, dict): return self._terminal(command, "UNKNOWN", "target readback unavailable", False)
        return value

    @staticmethod
    def _target_problem(command: dict[str, Any], target: dict[str, Any]) -> tuple[str, str] | None:
        for key in ("head", "tree", "branch", "default_branch"):
            if target.get(key) is None: return "UNKNOWN", f"target {key} unavailable"
        if target["branch"] != command["starting_branch"]: return "BLOCKED", "target branch mismatch"
        if target["branch"] == target["default_branch"]: return "BLOCKED", "main/default branch write forbidden"
        if target["head"] != command["expected_target_head"]: return "BLOCKED", "STALE_TARGET: PR #4 head changed"
        if target["tree"] != command["expected_target_tree"]: return "BLOCKED", "STALE_TARGET: PR #4 tree changed"
        return None

    @staticmethod
    def _validate_command(c: dict[str, Any]) -> None:
        required = {"expected_target_tree", "starting_branch", "allowed_paths", "path_policy"}
        if not required <= c.keys(): raise ValueError("incomplete Jules API command")
        if c["retry"] != 0 or c["fallback"] != "disabled": raise ValueError("unsafe retry/fallback policy")
        if c["starting_branch"] in {"main", "master", "default"}: raise ValueError("main/default branch forbidden")
        if not c["expected_target_tree"]: raise ValueError("expected target tree required")
        if not isinstance(c["allowed_paths"], list) or not c["allowed_paths"]: raise ValueError("allowed paths required")
        if not isinstance(c["path_policy"], list): raise ValueError("path policy required")

    @staticmethod
    def _reservation(c: dict[str, Any]) -> dict[str, Any]:
        return make_executor_request(request_id=f"{c['command_id']}-dispatch", loop_id=c["loop_id"], round=c["round"],
            correlation_id=c["correlation_id"], executor_role="jules-api-dispatcher", executor_kind="github-actions",
            action="RESERVE_JULES_API_WORKFLOW_DISPATCH", capability="jules-api-workflow-dispatch-reservation",
            objective="reserve exactly one Jules API workflow dispatch for this command", input_refs=[f"command:{c['command_id']}"],
            allowed_actions=["SUBMIT_ONCE", "READBACK"], prohibited_actions=["RETRY", "FALLBACK", "MAIN_WRITE", "MERGE", "FORCE_PUSH"],
            expected_repo=c["expected_repo"], expected_pr=c["expected_pr"], expected_target_head=c["expected_target_head"],
            expected_target_tree=c["expected_target_tree"], path_policy=c["path_policy"], expires_at=c["expires_at"], requires_github_write=True)

    @staticmethod
    def _submission_problem(c: dict[str, Any], s: Any) -> tuple[str, str] | None:
        if not isinstance(s, dict): return "UNKNOWN", "workflow submit result malformed"
        if s.get("ambiguous") is True or s.get("status") == "UNKNOWN": return "UNKNOWN", "workflow submit ambiguity; do not resend"
        if s.get("status") != "SUBMITTED" or s.get("task_submitted") is not True: return "BLOCKED", "workflow did not prove one Jules submission"
        if s.get("repository") != c["expected_repo"]: return "BLOCKED", "workflow repository mismatch"
        if s.get("starting_branch") != c["starting_branch"]: return "BLOCKED", "workflow starting branch mismatch"
        if not s.get("workflow_run_id") or not s.get("session_id"): return "UNKNOWN", "workflow/session correlation unavailable"
        if s.get("retry_count") is None or s.get("fallback_used") is None: return "UNKNOWN", "workflow retry/fallback unavailable"
        if s["retry_count"] != 0 or s["fallback_used"] is not False: return "BLOCKED", "workflow retry/fallback policy violated"
        return None

    @staticmethod
    def _publication_problem(c: dict[str, Any], s: dict[str, Any], p: Any) -> tuple[str, str] | None:
        if not isinstance(p, dict): return "UNKNOWN", "publication malformed"
        if p.get("repository") != c["expected_repo"]: return "BLOCKED", "publication repository mismatch"
        if p.get("workflow_run_id") != s.get("workflow_run_id") or p.get("session_id") != s.get("session_id"): return "UNKNOWN", "publication correlation mismatch"
        if p.get("starting_branch") != c["starting_branch"]: return "BLOCKED", "publication starting branch mismatch"
        if not p.get("resulting_commit") or not p.get("result_tree") or not isinstance(p.get("pr_number"), int): return "UNKNOWN", "publication commit/tree/PR identity unavailable"
        if p.get("merge_base") is None: return "UNKNOWN", "merge-base unavailable"
        if p["merge_base"] != c["expected_target_head"]: return "BLOCKED", "merge-base mismatch"
        if p.get("ahead_by") != 1 or p.get("behind_by") != 0: return "BLOCKED", "publication ancestry is not one clean child"
        if p.get("pr_base_branch") != c["starting_branch"]: return "BLOCKED", "Jules PR base mismatch"
        changed = p.get("changed_paths")
        if not isinstance(changed, list): return "UNKNOWN", "changed paths unavailable"
        policy = {x.get("path"): set(x.get("allowed_ops", [])) for x in c["path_policy"] if isinstance(x, dict)}
        seen = set()
        for x in changed:
            if not isinstance(x, dict): return "UNKNOWN", "changed path malformed"
            path, op = x.get("path"), x.get("operation"); seen.add(path)
            if path not in policy: return "BLOCKED", f"unexpected path: {path}"
            if op not in policy[path]: return "BLOCKED", f"unexpected operation: {op}"
        if seen != set(c["allowed_paths"]): return "BLOCKED", "changed path set does not exactly match command"
        return None

    @staticmethod
    def _ff_ancestry(c: dict[str, Any], p: dict[str, Any]) -> bool | None:
        if p.get("merge_base") is None: return None
        return p.get("parent_shas") == [c["expected_target_head"]] and p.get("merge_base") == c["expected_target_head"] and p.get("behind_by") == 0

    def _terminal(self, c: dict[str, Any], state: str, reason: str, send_attempted: bool,
                  *, head: str | None = None, evidence_refs: list[str] | None = None, outcome: str | None = None) -> ClosedLoopResult:
        canonical = state if state in {"DONE", "BLOCKED", "FAILED", "UNKNOWN", "CANCELLED"} else "UNKNOWN"
        receipt = {"schema_version": 1, "receipt_id": f"{c['loop_id']}/{c['round']:06d}", "command_id": c["command_id"],
            "loop_id": c["loop_id"], "round": c["round"], "correlation_id": c["correlation_id"], "state": canonical,
            "executed_once": True, "github_head_before": c.get("expected_target_head"), "github_head_after": head,
            "external_send_attempted": send_attempted, "external_send_readback_verified": "YES" if outcome == "COMPLETE" else "NO",
            "retry_count": 0, "fallback_used": False, "evidence_refs": list(evidence_refs or []), "reason": reason}
        if outcome: receipt["outcome"] = outcome
        self.ledger.add_receipt(receipt); self.ledger.state["last_receipt_id"] = receipt["receipt_id"]; self.ledger.state["last_command_id"] = c["command_id"]
        if canonical == "DONE": self.ledger.state["round"], self.ledger.state["state"] = c["round"], "COMPLETE"
        elif canonical in {"UNKNOWN", "BLOCKED"}: self.ledger.state["state"] = canonical
        else: self.ledger.state["state"] = "FAILED"
        if self.terminal_backend is not None:
            saved = self.terminal_backend.persist_terminal(receipt, self.ledger.state)
            if saved.status != "ACCEPTED": return ClosedLoopResult("UNKNOWN", f"terminal persistence unresolved; do not replay: {saved.reason}", receipt)
        return ClosedLoopResult(outcome or canonical, reason, receipt)


def _canonical(value: dict[str, Any]) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def _json(text: str) -> Any:
    return json.loads(text)
