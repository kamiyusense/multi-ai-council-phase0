"""Two-layer closed-loop reviewer: deterministic guard + Claude semantic review (STATIC contract).

The live reviewer is the Claude Routine.  It must not be a string matcher, and
it must not be a free-form judge either.  The work is split:

1. ``precheck`` (deterministic, code) decides what is mechanically certain:
   whether this PR is a closed-loop task at all, task metadata, duplicate
   events and terminal receipts, duplicate correctives, the corrective round,
   the path fence (unauthorized or deleted files), "same content, different
   commit", and the integrity of every durable record it reads.
2. Claude's **semantic review** judges what code cannot: whether each
   acceptance criterion is really met, whether the root cause is fixed rather
   than the symptom, whether tests were weakened, whether other behaviour broke,
   whether a regression test is missing, and whether every finding from the
   previous round is actually resolved.  It returns a
   ``CLAUDE_SEMANTIC_REVIEW_V1`` record (``validate_semantic_review``).
3. ``combine`` merges both into one decision with fixed precedence rules, so
   no layer can override the other where it must not:
   * a guard finding (for example an unauthorized second file) always means
     NEEDS_CORRECTION; a semantic PASS cannot override it;
   * PASS needs every criterion met, no major finding, every previous finding
     resolved and, when the task names test commands, a passing exact-head test
     run.  Green tests with an unmet criterion are NEEDS_CORRECTION;
   * BLOCKED is accepted only for reasons that a corrective cannot fix
     (``BLOCKING_REASONS``).  Any other "blocked" is turned into
     NEEDS_CORRECTION, because an ordinary failure is a reason to correct, not
     to stop;
   * a finding that repeats from an earlier round escalates the corrective to
     a root-cause review instead of asking for the same surface fix again;
   * when the corrective budget is used up, the task is isolated
     (TASK_BLOCKED for this task only); the campaign continues with other tasks.
4. ``build_corrective`` writes the ``@jules`` message from structured findings:
   what is wrong, expected behaviour, allowed scope, reproduction, required
   regression test and pass condition.
5. ``render_receipt`` and ``parse_receipt`` keep the machine record exact: one
   JSON object, schema-checked, with a real UTC timestamp, rendered by code and
   never hand-formatted.

Everything is a pure function of GitHub state plus the semantic review
record.  The same state gives the same decision, so restarts and replays are
safe.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from typing import Any

from .claude_closed_loop_protocol import (
    CORRECTIVE_MARKER, RECEIPT_MARKER, TASK_MARKER, TASK_PROFILE, _block, linked_issue,
)

SEMANTIC_PROFILE = "CLAUDE_SEMANTIC_REVIEW_V1"
RECEIPT_PROFILE = "CLAUDE_CLOSED_LOOP_REVIEW_V2"
TASK_KINDS = {"proof", "code_change"}
FINDING_CATEGORIES = {
    "acceptance_unmet", "root_cause_not_fixed", "behaviour_regression", "missing_regression_test",
    "weakened_test", "interface_break", "docs_contract_drift", "design_issue", "scope_violation", "other",
}
SEVERITIES = {"major", "minor"}
# Reasons that a corrective cannot fix; anything else is a correctable failure.
BLOCKING_REASONS = {
    "external_dependency_missing", "permission_missing", "contradictory_requirements",
    "outside_approved_scope", "billing_or_provider_boundary", "destructive_operation_required",
}
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_UTC = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}Z$")
_STATUS_OP = {"added": "ADD", "modified": "MODIFY"}

# precheck outcomes
NOT_A_TASK, NO_OP, TASK_BLOCKED, PROCEED = "NOT_A_TASK", "NO_OP", "TASK_BLOCKED", "PROCEED"
# final verdicts
PASS, NEEDS_CORRECTION, BLOCKED = "PASS", "NEEDS_CORRECTION", "BLOCKED"


@dataclass(frozen=True)
class Precheck:
    status: str
    reason: str
    issue: int | None = None
    task: dict[str, Any] | None = None
    round: int | None = None
    guard_findings: tuple[dict[str, Any], ...] = ()
    previous_findings: tuple[dict[str, Any], ...] = ()
    existing_corrective: bool = False
    existing_next_issue: int | None = None


@dataclass(frozen=True)
class Decision:
    verdict: str
    decision: str            # ADOPT_RECORDED / CORRECTIVE_REQUESTED / CORRECTIVE_EXISTS / TASK_BLOCKED
    reason: str
    round: int
    findings: tuple[dict[str, Any], ...] = ()
    escalate_root_cause: bool = False
    writes: tuple[str, ...] = ()


# ---------------------------------------------------------------- task metadata
def validate_task_v2(task: Any, *, pr_base: str) -> str | None:
    """None when the task is complete and consistent; ``proof`` and ``code_change`` tasks are both accepted."""
    if not isinstance(task, dict) or task.get("profile") != TASK_PROFILE:
        return "task block is not CLAUDE_CLOSED_LOOP_TASK_V1"
    kind = task.get("kind", "proof")
    if kind not in TASK_KINDS:
        return f"unknown task kind {kind!r}"
    for key in ("task_id", "loop_id", "correlation_id", "expected_target_branch"):
        if not isinstance(task.get(key), str) or not task[key]:
            return f"task {key} missing"
    if not task["correlation_id"].startswith(task["task_id"]):
        return "correlation_id does not belong to task_id"
    for key in ("generation", "max_corrective_rounds", "live_slot"):
        if isinstance(task.get(key), bool) or not isinstance(task.get(key), int):
            return f"task {key} must be an integer"
    if task["generation"] < 1 or task["max_corrective_rounds"] < 0:
        return "task generation/max_corrective_rounds out of range"
    if not _SHA40.fullmatch(str(task.get("expected_target_head") or "")):
        return "expected_target_head must be a 40-hex sha"
    paths = task.get("allowed_paths")
    if not isinstance(paths, list) or not paths or any(
            not isinstance(p, dict) or not p.get("path") or p.get("op") not in {"ADD", "MODIFY"} for p in paths):
        return "allowed_paths malformed"
    if kind == "proof":
        lines = task.get("required_lines")
        if not isinstance(lines, list) or not lines or any(not isinstance(l, str) or not l for l in lines):
            return "required_lines malformed"
    else:
        criteria = task.get("acceptance_criteria")
        if not isinstance(criteria, list) or not criteria or any(not isinstance(c, str) or not c for c in criteria):
            return "code_change task needs acceptance_criteria"
        tests = task.get("test_commands")
        if not isinstance(tests, list) or not tests or any(not isinstance(t, str) or not t for t in tests):
            return "code_change task needs test_commands"
    if pr_base != task["expected_target_branch"]:
        return f"PR base {pr_base!r} is not the expected target branch {task['expected_target_branch']!r}"
    return None


# ---------------------------------------------------------------- receipts
def finding_fingerprint(finding: dict[str, Any]) -> str:
    """Stable identity of a finding across rounds (category + scope + normalized description)."""
    what = re.sub(r"[^a-z0-9]+", " ", str(finding.get("what_is_wrong", "")).lower()).strip()
    scope = ",".join(sorted(finding.get("scope_paths") or []))
    return hashlib.sha256(f"{finding.get('category')}|{scope}|{what}".encode()).hexdigest()[:16]


def render_receipt(*, summary: str, record: dict[str, Any]) -> str:
    """The issue comment body: human summary, then exactly one schema-valid JSON object."""
    validate_receipt(record)
    return f"{summary.strip()}\n\n{RECEIPT_MARKER}\n{json.dumps(record, ensure_ascii=False, sort_keys=True)}\n-->\n"


def parse_receipt(comment: str) -> dict[str, Any]:
    """Strict parse of a v2 receipt: the block must be one JSON object and nothing else."""
    start = comment.index(RECEIPT_MARKER) + len(RECEIPT_MARKER)
    inner = comment[start:comment.index("-->", start)].strip()
    return validate_receipt(json.loads(inner))


_RECEIPT_KEYS = {"profile", "task_id", "loop_id", "correlation_id", "generation", "round", "phase", "pr",
                 "pr_head_sha", "pr_head_tree", "expected_target_head", "observed_base_head", "verdict", "decision",
                 "criteria", "findings", "escalate_root_cause", "tests", "live_slot", "corrective_comment",
                 "next_issue", "wake_event", "reviewed_at"}


def validate_receipt(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) != _RECEIPT_KEYS:
        raise ValueError("receipt keys mismatch")
    if record["profile"] != RECEIPT_PROFILE:
        raise ValueError("unsupported receipt profile")
    if record["verdict"] not in {PASS, NEEDS_CORRECTION, BLOCKED}:
        raise ValueError("receipt verdict invalid")
    if not _SHA40.fullmatch(str(record["pr_head_sha"])) or not _SHA40.fullmatch(str(record["pr_head_tree"])):
        raise ValueError("receipt head/tree invalid")
    if not _UTC.fullmatch(str(record["reviewed_at"])):
        raise ValueError("reviewed_at must be a real UTC timestamp YYYY-MM-DDTHH:MM:SSZ")
    if not isinstance(record["findings"], list) or not isinstance(record["round"], int):
        raise ValueError("receipt findings/round malformed")
    if record["phase"] not in {"NEEDS_CORRECTION", "FINAL"}:
        raise ValueError("receipt phase invalid")
    if not isinstance(record["criteria"], list) or any(
            not isinstance(c, dict) or set(c) != {"criterion", "met", "evidence"} for c in record["criteria"]):
        raise ValueError("receipt criteria malformed")
    return record


def _receipts(comments: list[str]) -> list[dict[str, Any]]:
    """v1 and v2 receipts; a broken record raises (it is never written over)."""
    return [r for c in comments if RECEIPT_MARKER in c for r in _block(c, RECEIPT_MARKER)]


# ---------------------------------------------------------------- layer 1: deterministic guard
def precheck(*, pr: dict[str, Any], issue_body: str | None, issue_comments: list[str], pr_comments: list[str],
             files: list[dict[str, Any]], head_tree: str, head_changes_files: bool = True,
             open_issue_titles: dict[str, int] | None = None) -> Precheck:
    issue = linked_issue(pr.get("body") or "")
    if issue is None or issue_body is None or TASK_MARKER not in issue_body:
        return Precheck(NOT_A_TASK, "no link to a closed-loop task issue")
    try:
        tasks = _block(issue_body, TASK_MARKER)
    except (ValueError, json.JSONDecodeError) as exc:
        return Precheck(TASK_BLOCKED, f"task block unreadable: {exc}", issue)
    if len(tasks) != 1:
        return Precheck(TASK_BLOCKED, "issue must hold exactly one task block", issue)
    task = tasks[0]
    if (problem := validate_task_v2(task, pr_base=pr.get("base", ""))) is not None:
        return Precheck(TASK_BLOCKED, problem, issue, task)
    try:
        receipts = [r for r in _receipts(issue_comments) if r.get("correlation_id") == task["correlation_id"]]
        correctives = [c for x in pr_comments if CORRECTIVE_MARKER in x for c in _block(x, CORRECTIVE_MARKER)]
    except (ValueError, json.JSONDecodeError) as exc:
        return Precheck(NO_OP, f"durable record unreadable ({exc}); nothing is written over it", issue, task)
    if any(r.get("verdict") == PASS for r in receipts):
        return Precheck(NO_OP, "already PASS for this correlation", issue, task)
    if any(r.get("pr_head_sha") == pr.get("head") for r in receipts):
        return Precheck(NO_OP, "this head was already reviewed", issue, task)
    if receipts and (not head_changes_files or any(r.get("pr_head_tree") == head_tree for r in receipts)):
        return Precheck(NO_OP, "same content as an already reviewed head", issue, task)
    failed = [r for r in receipts if r.get("verdict") in {"FAIL", NEEDS_CORRECTION}]
    rnd = 1 + len(failed)
    previous = tuple(f for r in failed[-1:] for f in r.get("findings") or [])
    guard = []
    allowed = {p["path"]: p["op"] for p in task["allowed_paths"]}
    for f in files:
        path, status = f.get("filename") or f.get("path"), f.get("status")
        if path not in allowed:
            guard.append({"category": "scope_violation", "severity": "major", "scope_paths": [path],
                          "what_is_wrong": f"{path} is changed but is not an allowed path",
                          "expected_behavior": f"only {sorted(allowed)} change",
                          "reproduction": "gh pr view --json files", "regression_test": "none",
                          "pass_condition": f"revert every change to {path}"})
        elif status in {"removed", "renamed"} or _STATUS_OP.get(status) != allowed[path]:
            guard.append({"category": "scope_violation", "severity": "major", "scope_paths": [path],
                          "what_is_wrong": f"{path} has status {status}, allowed operation is {allowed[path]}",
                          "expected_behavior": f"{path} is {allowed[path]}", "reproduction": "gh pr view --json files",
                          "regression_test": "none", "pass_condition": f"{path} with operation {allowed[path]}"})
    existing = any(c.get("pr_head_sha") == pr.get("head") and c.get("correlation_id") == task["correlation_id"]
                   for c in correctives)
    nxt = (task.get("next_task") or {}).get("title")
    return Precheck(PROCEED, "precheck passed", issue, task, rnd, tuple(guard), previous, existing,
                    (open_issue_titles or {}).get(nxt) if nxt else None)


# ---------------------------------------------------------------- layer 2: Claude semantic review record
def validate_semantic_review(record: Any, *, task: dict[str, Any], previous: tuple[dict[str, Any], ...]) -> dict:
    if not isinstance(record, dict) or record.get("profile") != SEMANTIC_PROFILE:
        raise ValueError("semantic review profile missing")
    if record.get("verdict") not in {PASS, NEEDS_CORRECTION, BLOCKED}:
        raise ValueError("semantic verdict invalid")
    criteria = record.get("criteria")
    expected = task.get("acceptance_criteria") or task.get("required_lines") or []
    if not isinstance(criteria, list) or [c.get("criterion") for c in criteria] != list(expected):
        raise ValueError("semantic review must judge every acceptance criterion, in order")
    if any(not isinstance(c.get("met"), bool) or not str(c.get("evidence") or "").strip() for c in criteria):
        raise ValueError("each criterion needs met + evidence")
    for f in record.get("findings") or []:
        if f.get("category") not in FINDING_CATEGORIES or f.get("severity") not in SEVERITIES:
            raise ValueError("finding category/severity invalid")
        for key in ("what_is_wrong", "expected_behavior", "pass_condition"):
            if not str(f.get(key) or "").strip():
                raise ValueError(f"finding needs {key}")
        if not isinstance(f.get("scope_paths"), list) or not f["scope_paths"]:
            raise ValueError("finding needs scope_paths")
    resolved = {r.get("fingerprint"): r for r in record.get("previous_findings_resolved") or []}
    for p in previous:
        r = resolved.get(finding_fingerprint(p))
        if r is None or not isinstance(r.get("resolved"), bool) or not str(r.get("evidence") or "").strip():
            raise ValueError("every previous finding must be judged resolved or not, with evidence")
    tests = record.get("tests")
    if not isinstance(tests, dict) or tests.get("result") not in {"PASS", "FAIL", "NOT_RUN"}:
        raise ValueError("semantic review must report tests")
    if record["verdict"] == BLOCKED and record.get("blocked_reason") is None:
        raise ValueError("BLOCKED needs blocked_reason")
    return record


# ---------------------------------------------------------------- merge
def combine(pre: Precheck, review: dict[str, Any]) -> Decision:
    assert pre.status == PROCEED and pre.task is not None and pre.round is not None
    task, rnd = pre.task, pre.round
    findings = list(pre.guard_findings) + list(review.get("findings") or [])
    unmet = [c for c in review["criteria"] if not c["met"]]
    unresolved = [r for r in review.get("previous_findings_resolved") or [] if not r["resolved"]]
    tests_needed = bool(task.get("test_commands"))
    tests_ok = review["tests"]["result"] == "PASS" or (not tests_needed and review["tests"]["result"] == "NOT_RUN")
    for c in unmet:
        findings.append({"category": "acceptance_unmet", "severity": "major", "scope_paths":
                         [p["path"] for p in task["allowed_paths"]], "what_is_wrong": f"criterion not met: {c['criterion']}",
                         "expected_behavior": c["criterion"], "reproduction": c["evidence"],
                         "regression_test": "a test that fails until the criterion holds",
                         "pass_condition": c["criterion"]})
    if not tests_ok:
        findings.append({"category": "behaviour_regression" if review["tests"]["result"] == "FAIL" else "other",
                         "severity": "major", "scope_paths": [p["path"] for p in task["allowed_paths"]],
                         "what_is_wrong": f"exact-head tests {review['tests']['result']}",
                         "expected_behavior": "every task test command passes on the PR head",
                         "reproduction": "; ".join(task.get("test_commands") or []) or "n/a",
                         "regression_test": "existing suite", "pass_condition": "all task test commands pass"})
    if review["verdict"] == BLOCKED and review.get("blocked_reason") in BLOCKING_REASONS and not pre.guard_findings:
        return Decision(BLOCKED, TASK_BLOCKED, f"not correctable: {review['blocked_reason']}", rnd,
                        tuple(findings), writes=("receipt",))
    majors = [f for f in findings if f.get("severity") == "major"]
    if review["verdict"] == PASS and not majors and not unresolved and not unmet and tests_ok:
        writes = ("receipt",) if pre.existing_next_issue or not task.get("next_task") else ("next_issue", "receipt")
        return Decision(PASS, "ADOPT_RECORDED", "guard clean, every criterion met, tests pass", rnd, tuple(findings),
                        writes=writes)
    if not findings:  # semantic NEEDS_CORRECTION / non-blocking BLOCKED without concrete findings
        findings.append({"category": "other", "severity": "major", "scope_paths":
                         [p["path"] for p in task["allowed_paths"]], "what_is_wrong": review.get("summary", "review failed"),
                         "expected_behavior": "see acceptance criteria", "reproduction": "review the PR head",
                         "regression_test": "as required by the task", "pass_condition": "all criteria met"})
    if rnd > task["max_corrective_rounds"]:
        return Decision(NEEDS_CORRECTION, TASK_BLOCKED, "corrective budget used; task isolated, campaign continues",
                        rnd, tuple(findings), writes=("receipt",))
    seen = {finding_fingerprint(p) for p in pre.previous_findings}
    escalate = any(finding_fingerprint(f) in seen for f in findings) or bool(unresolved)
    if pre.existing_corrective:
        return Decision(NEEDS_CORRECTION, "CORRECTIVE_EXISTS", "corrective for this head already posted", rnd,
                        tuple(findings), escalate, ("receipt",))
    return Decision(NEEDS_CORRECTION, "CORRECTIVE_REQUESTED", "correctable failure", rnd, tuple(findings), escalate,
                    ("corrective", "receipt"))


def build_corrective(decision: Decision, *, task: dict[str, Any], pr_head_sha: str) -> str:
    """The single ``@jules`` message: specific, scoped, testable."""
    scope = sorted({p["path"] for p in task["allowed_paths"]})
    lines = ["@jules Review round {} found {} issue(s). Please fix them in this pull request.".format(
        decision.round, len(decision.findings)), ""]
    if decision.escalate_root_cause:
        lines += ["**Root-cause review requested.** The same problem was reported in the previous round, so the "
                  "last fix only addressed a symptom. Before changing code, explain in the commit message why "
                  "the failure happens, then fix that cause.", ""]
    for n, f in enumerate(decision.findings, start=1):
        lines += [f"{n}. **{f['category']}** ({f['severity']}) in {', '.join(f['scope_paths'])}",
                  f"   - What is wrong: {f['what_is_wrong']}",
                  f"   - Expected behaviour: {f['expected_behavior']}",
                  f"   - How to reproduce: {f.get('reproduction') or 'see above'}",
                  f"   - Regression test to add or keep: {f.get('regression_test') or 'none'}",
                  f"   - Passes when: {f['pass_condition']}"]
    lines += ["", f"Change only: {', '.join(scope)}. Do not change any other file, and do not weaken or delete "
              "existing tests.", ""]
    if task.get("test_commands"):
        lines += ["Run before pushing: " + "; ".join(f"`{c}`" for c in task["test_commands"]), ""]
    marker = {"correlation_id": task["correlation_id"], "pr_head_sha": pr_head_sha, "round": decision.round}
    lines.append(f"{CORRECTIVE_MARKER} {json.dumps(marker, sort_keys=True)} -->")
    return "\n".join(lines) + "\n"
