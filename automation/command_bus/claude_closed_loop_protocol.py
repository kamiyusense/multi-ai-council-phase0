"""GitHub-native closed-loop protocol: the reviewer's decision as deterministic code (STATIC reference).

The live reviewer is the Claude Routine "Claude closed-loop reviewer v1"
(prompt v1.3).  It wakes on ``pull_request.opened`` / ``pull_request.synchronize``
and follows the rules written here.  This module is the same rule set as pure
functions over GitHub state, so that:

* the rules are fixed by unit tests (duplicate events, duplicate correctives,
  restart, stale head, unrelated PRs, malformed metadata, blocker isolation,
  transient reads, receipt replay);
* the live receipts on GitHub can be re-checked independently of the Routine
  (``verify_live_receipt``).

GitHub is the only state.  A decision depends only on: the PR (number, head,
base, body, files, file content), the task issue (body with the
``claude-closed-loop-task v1`` block, comments with
``claude-closed-loop-receipt v1`` blocks) and the PR's comments (``@jules``
correctives with ``claude-closed-loop-corrective v1`` blocks).  A fresh process
reading the same state therefore takes the same decision, and a state that
already holds the outcome yields a NO-OP: restart and replay are safe by
construction.

Writes are never decided twice: the decision names at most one receipt, one
corrective and one next issue, each guarded by a marker that a re-run finds.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Any, Callable

TASK_MARKER = "<!-- claude-closed-loop-task v1"
RECEIPT_MARKER = "<!-- claude-closed-loop-receipt v1"
CORRECTIVE_MARKER = "<!-- claude-closed-loop-corrective v1"
TASK_PROFILE = "CLAUDE_CLOSED_LOOP_TASK_V1"
_LINK = re.compile(r"\b(?:fixes|closes|resolves)\s+#([0-9]+)\b", re.I)
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_STATUS_OP = {"added": "ADD", "modified": "MODIFY"}

# outcomes
NOT_A_TASK = "NOT_A_TASK"            # unrelated PR: no write at all
NO_OP = "NO_OP"                      # terminal or already handled: no write
TASK_BLOCKED = "TASK_BLOCKED"        # bad metadata: one receipt, no Jules instruction
PASS = "PASS"
CORRECTIVE = "CORRECTIVE"            # FAIL within budget: receipt + one @jules comment
CORRECTIVE_EXISTS = "CORRECTIVE_EXISTS"  # FAIL, corrective for this head already posted: receipt only
BUDGET_EXHAUSTED = "BUDGET_EXHAUSTED"


@dataclass(frozen=True)
class Decision:
    outcome: str
    reason: str
    issue: int | None = None
    phase: str | None = None
    round: int | None = None
    checks: dict[str, str] = field(default_factory=dict)
    writes: tuple[str, ...] = ()     # the writes this decision allows, in order


def _block(text: str, marker: str) -> list[Any]:
    """Every JSON object inside ``marker ... -->`` blocks of ``text`` (malformed blocks raise)."""
    found = []
    start = 0
    while (i := text.find(marker, start)) != -1:
        end = text.find("-->", i)
        if end == -1:
            raise ValueError("unterminated marker block")
        inner = text[i + len(marker):end].strip()
        if not inner.startswith("{"):
            raise ValueError("marker block does not start with a JSON object")
        # One JSON object, decoded exactly; formatting debris after its closing brace (seen live: a
        # stray "``" in the CLP-002 round-1 receipt) is ignored, anything malformed inside still raises.
        obj, _ = json.JSONDecoder().raw_decode(inner)
        found.append(obj)
        start = end + 3
    return found


def linked_issue(pr_body: str) -> int | None:
    numbers = {int(n) for n in _LINK.findall(pr_body or "")}
    return numbers.pop() if len(numbers) == 1 else None


def validate_task(task: Any, *, pr_base: str) -> str | None:
    """None when the task metadata is complete and consistent, else the reason it is blocked."""
    if not isinstance(task, dict) or task.get("profile") != TASK_PROFILE:
        return "task block is not CLAUDE_CLOSED_LOOP_TASK_V1"
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
    lines = task.get("required_lines")
    if not isinstance(lines, list) or not lines or any(not isinstance(l, str) or not l for l in lines):
        return "required_lines malformed"
    first = task.get("first_submission_lines")
    if first is not None and (not isinstance(first, list) or not first or first == lines):
        return "first_submission_lines malformed"
    if pr_base != task["expected_target_branch"]:
        return f"PR base {pr_base!r} is not the expected target branch {task['expected_target_branch']!r}"
    return None


def _content_lines(text: str) -> list[str]:
    return [line for line in text.split("\n") if line.strip()]


def inspect(task: dict[str, Any], *, pr_base: str, files: list[dict[str, Any]],
            contents: dict[str, str]) -> tuple[str, str, dict[str, str]]:
    """``(verdict, phase, checks)`` for the exact PR head."""
    allowed = {p["path"]: p["op"] for p in task["allowed_paths"]}
    changed = {f.get("filename") or f.get("path"): f.get("status") for f in files}
    checks: dict[str, str] = {}
    ok_paths = set(changed) == set(allowed) and all(_STATUS_OP.get(s) == allowed[p] for p, s in changed.items())
    checks["paths_exact"] = "PASS" if ok_paths else f"FAIL: changed {sorted(changed.items())}"
    path = task["allowed_paths"][0]["path"]
    text = contents.get(path)
    if text is None:
        checks["required_lines"] = checks["no_extra_content"] = checks["whitespace"] = "FAIL: file unreadable"
        phase = "FINAL"
    else:
        body = _content_lines(text)
        stripped = [l.rstrip() for l in body]
        missing = [l for l in task["required_lines"] if l not in stripped]
        extra = [l for l in stripped if l not in task["required_lines"]]
        checks["required_lines"] = "PASS" if not missing else f"FAIL: missing {missing}"
        checks["no_extra_content"] = "PASS" if not extra else f"FAIL: extra {extra}"
        bad_ws = [l for l in text.split("\n") if l != l.rstrip(" \t") or "\t" in l]
        checks["whitespace"] = "PASS" if not bad_ws else f"FAIL: {len(bad_ws)} line(s)"
        first = task.get("first_submission_lines")
        phase = "NEEDS_CORRECTION" if first is not None and stripped == first else "FINAL"
    checks["base_branch"] = "PASS" if pr_base == task["expected_target_branch"] else f"FAIL: base {pr_base}"
    verdict = PASS if all(v == "PASS" for v in checks.values()) else "FAIL"
    return verdict, phase, checks


def decide(*, pr: dict[str, Any], issue_body: str | None, issue_comments: list[str],
           pr_comments: list[str], files: list[dict[str, Any]], contents: dict[str, str],
           head_changes_files: bool = True) -> Decision:
    """The reviewer's decision for one wake, from GitHub state only."""
    issue = linked_issue(pr.get("body") or "")
    if issue is None or issue_body is None or TASK_MARKER not in issue_body:
        return Decision(NOT_A_TASK, "no Fixes/Closes/Resolves link to a closed-loop task issue")
    try:
        tasks = _block(issue_body, TASK_MARKER)
    except (ValueError, json.JSONDecodeError) as exc:
        return Decision(TASK_BLOCKED, f"task block unreadable: {exc}", issue, writes=("receipt",))
    if len(tasks) != 1:
        return Decision(TASK_BLOCKED, "issue must hold exactly one task block", issue, writes=("receipt",))
    task = tasks[0]
    if (problem := validate_task(task, pr_base=pr.get("base", ""))) is not None:
        return Decision(TASK_BLOCKED, problem, issue, writes=("receipt",))
    try:
        receipts = [r for c in issue_comments if RECEIPT_MARKER in c for r in _block(c, RECEIPT_MARKER)]
        correctives = [r for c in pr_comments if CORRECTIVE_MARKER in c for r in _block(c, CORRECTIVE_MARKER)]
    except (ValueError, json.JSONDecodeError) as exc:
        return Decision(TASK_BLOCKED, f"durable record unreadable: {exc}", issue)  # never write over a broken record
    mine = [r for r in receipts if r.get("correlation_id") == task["correlation_id"]]
    if any(r.get("verdict") == PASS for r in mine):
        return Decision(NO_OP, "already PASS for this correlation", issue)
    if any(r.get("pr_head_sha") == pr.get("head") for r in mine):
        return Decision(NO_OP, "this head was already reviewed", issue)
    if mine and not head_changes_files:
        return Decision(NO_OP, "empty commit since the last review", issue)
    rnd = 1 + sum(1 for r in mine if r.get("verdict") == "FAIL")
    verdict, phase, checks = inspect(task, pr_base=pr.get("base", ""), files=files, contents=contents)
    if verdict == PASS:
        writes = ("next_issue", "receipt") if task.get("next_task") else ("receipt",)
        return Decision(PASS, "all checks passed", issue, phase, rnd, checks, writes)
    if rnd > task["max_corrective_rounds"]:
        return Decision(BUDGET_EXHAUSTED, "corrective budget used", issue, phase, rnd, checks, ("receipt",))
    if any(c.get("pr_head_sha") == pr.get("head") and c.get("correlation_id") == task["correlation_id"]
           for c in correctives):
        return Decision(CORRECTIVE_EXISTS, "corrective for this head already posted", issue, phase, rnd, checks,
                        ("receipt",))
    return Decision(CORRECTIVE, "FAIL within the corrective budget", issue, phase, rnd, checks,
                    ("corrective", "receipt"))


def read_with_retry(read: Callable[[], Any], *, attempts: int = 3, backoff: tuple[float, ...] = (0, 5, 30),
                    sleep: Callable[[float], None] = time.sleep, transient: tuple[type, ...] = (OSError, TimeoutError)):
    """Bounded retry for a read-only GitHub call; writes are never passed here."""
    if not 1 <= attempts <= len(backoff):
        raise ValueError("attempts must fit the backoff table")
    last: Exception | None = None
    for n in range(attempts):
        if backoff[n]:
            sleep(backoff[n])
        try:
            return read()
        except transient as exc:
            last = exc
    raise last  # type: ignore[misc]


def verify_live_receipt(receipt: dict[str, Any], decision: Decision, *, pr: dict[str, Any]) -> list[str]:
    """Differences between a live Routine receipt and this module's decision for the same state."""
    problems = []
    expected_verdict = PASS if decision.outcome == PASS else ("FAIL" if decision.outcome in {
        CORRECTIVE, CORRECTIVE_EXISTS, BUDGET_EXHAUSTED} else "UNKNOWN")
    if receipt.get("verdict") != expected_verdict:
        problems.append(f"verdict {receipt.get('verdict')} != {expected_verdict}")
    if receipt.get("pr_head_sha") != pr.get("head"):
        problems.append("receipt names another head")
    if decision.phase and receipt.get("phase", decision.phase) != decision.phase:
        problems.append(f"phase {receipt.get('phase')} != {decision.phase}")
    if decision.round and receipt.get("round") != decision.round:
        problems.append(f"round {receipt.get('round')} != {decision.round}")
    return problems
