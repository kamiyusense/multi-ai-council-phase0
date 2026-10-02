"""Claude's independent inspection of one Jules result and the repair decision.

Inputs are facts Claude gathered itself (fresh GitHub compare/readback, its
own test run on the exact candidate head, its own semantic review per
acceptance check).  Jules' summary, the PR body and Actions badges are never
inputs.  Pure code: the caller persists the returned record create-only.

Decisions follow the carrier Controller Operating Guide: evaluate a
Controller-safe small repair before any corrective; a corrective is a new
bounded mission (new claim/command/work branch), never a resend; missing
evidence is UNKNOWN and leads only to further safe investigation.
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass
from typing import Any

from .claude_jules_dispatch import EVIDENCE_ROOT, canonical_json, sha256_of
from .claude_jules_task_prompt import validate_task_spec
from .github_backend import GitHubContentsClient

INSPECTION_PROFILE = "CLAUDE_AUTO_JULES_INSPECTION_V1"
MINOR_CATEGORIES = {
    "typo", "docs_wording", "missing_import", "fixture_value", "assertion_message",
    "deterministic_value", "local_vacuous_test",
}
MAJOR_CATEGORIES = {
    "semantic_gap", "architecture", "multi_file", "spec_conflict", "path_fence",
    "ancestry", "delete_or_rename", "test_failure", "vacuous_test", "missing_negative_case",
}
REVIEWER_CHECKS = ("negative_cases_exercised", "regression_suite_reviewed")
MAX_SMALL_REPAIR_FILES = 2
MAX_SMALL_REPAIRS_PER_COMMAND = 1
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_STATUS_OP = {"added": "ADD", "modified": "MODIFY"}


@dataclass(frozen=True)
class InspectionOutcome:
    verdict: str
    decision: str
    record: dict[str, Any]


def inspection_path(command_id: str, head_sha: str) -> str:
    if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", command_id or "") or not _SHA40.fullmatch(head_sha or ""):
        raise ValueError("unsafe inspection identity")
    return f"{EVIDENCE_ROOT}/claude-auto-inspections/{command_id}/{head_sha}.json"


def find_vacuous_tests(sources: dict[str, str]) -> list[dict[str, str]]:
    """Detect tests that cannot fail (spec section 9) in changed test files."""
    findings: list[dict[str, str]] = []
    for path, text in sorted(sources.items()):
        try:
            tree = ast.parse(text)
        except SyntaxError as exc:
            findings.append({"category": "test_failure", "path": path, "detail": f"syntax error: {exc.msg}"})
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or not node.name.startswith("test"):
                continue
            body = [n for n in node.body if not (isinstance(n, ast.Expr) and isinstance(getattr(n, "value", None), ast.Constant) and isinstance(n.value.value, str))]
            if not body or all(isinstance(n, ast.Pass) for n in body):
                findings.append({"category": "local_vacuous_test", "path": path, "detail": f"{node.name} has no body"})
                continue
            asserts = 0
            constant_only = True
            for sub in ast.walk(node):
                if isinstance(sub, ast.Assert):
                    asserts += 1
                    if not isinstance(sub.test, ast.Constant):
                        constant_only = False
                elif isinstance(sub, ast.Call):
                    name = sub.func.attr if isinstance(sub.func, ast.Attribute) else getattr(sub.func, "id", "")
                    if name.startswith("assert"):
                        asserts += 1
                        if not sub.args or not all(isinstance(arg, ast.Constant) for arg in sub.args):
                            constant_only = False
                    elif "assert" in name.lower() or name.lstrip("_").startswith(("check", "verify", "expect")):
                        asserts += 1  # delegated assertion helper
                        constant_only = False
            if asserts == 0:
                findings.append({"category": "local_vacuous_test", "path": path, "detail": f"{node.name} asserts nothing"})
            elif constant_only:
                findings.append({"category": "local_vacuous_test", "path": path, "detail": f"{node.name} only asserts constants"})
    return findings


def _check(name: str, state: str, detail: str) -> dict[str, str]:
    return {"check": name, "state": state, "detail": detail}


def inspect_result(
    *, intent: dict[str, Any], task_spec: dict[str, Any], lineage: dict[str, Any] | None,
    compare: dict[str, Any] | None, candidate_tree: str | None, test_evidence: dict[str, Any] | None,
    changed_test_sources: dict[str, str] | None, acceptance_observations: dict[str, Any] | None,
    reviewer_findings: list[dict[str, Any]], prior_inspections: list[dict[str, Any]],
    inspected_at: str, repair_of: str | None = None,
) -> InspectionOutcome:
    request = intent["carrier_request"]
    candidate = (lineage or {}).get("candidate_head") if repair_of is None else (compare or {}).get("head_sha")
    checks: list[dict[str, str]] = []
    findings: list[dict[str, Any]] = [dict(item) for item in reviewer_findings]
    unknown: list[str] = []

    # 1. session/command lineage (already verified against workflow + PR).
    if not isinstance(lineage, dict) or lineage.get("command_id") != request["command_id"]:
        checks.append(_check("session_command", "UNKNOWN", "lineage not verified")); unknown.append("lineage")
    else:
        checks.append(_check("session_command", "PASS", f"session {lineage['session_id']} / run {lineage['workflow_run_id']}"))

    # 2. ancestry from the exact snapshot.
    if not isinstance(compare, dict) or not _SHA40.fullmatch(str(candidate or "")):
        checks.append(_check("ancestry", "UNKNOWN", "compare readback unavailable")); unknown.append("ancestry")
    elif (compare.get("base_sha") != request["expected_target_head"] or compare.get("merge_base") != request["expected_target_head"]
          or compare.get("behind_by") != 0 or not isinstance(compare.get("ahead_by"), int) or compare["ahead_by"] < 1
          or compare.get("head_sha") != candidate):
        checks.append(_check("ancestry", "FAIL", "candidate is not a clean descendant of the snapshot"))
        findings.append({"category": "ancestry", "detail": "candidate is not a clean descendant of the expected snapshot"})
    else:
        checks.append(_check("ancestry", "PASS", f"{compare['ahead_by']} commit(s) ahead of snapshot"))

    # 3/4. allowlist, operations, deletes and renames.
    policy = {item["path"]: set(item["allowed_ops"]) for item in task_spec["allowed_paths"]}
    files = (compare or {}).get("files")
    changed_paths: list[str] = []
    if not isinstance(files, list):
        checks.append(_check("allowlist", "UNKNOWN", "changed files unavailable")); unknown.append("files")
    else:
        fence, destructive = [], []
        for item in files:
            path, status = (item or {}).get("path"), (item or {}).get("status")
            changed_paths.append(path)
            if status in {"removed", "renamed"}:
                destructive.append(path)
            elif path not in policy or _STATUS_OP.get(status) not in policy[path]:
                fence.append(path)
        if set(request["allowed_paths"]) != set(policy):
            fence.append("<task spec/carrier allowlist mismatch>")
        if not files:
            fence.append("<empty change set>")
        checks.append(_check("allowlist", "FAIL" if fence else "PASS", ", ".join(map(str, fence)) or "within allowlist"))
        checks.append(_check("delete_rename", "FAIL" if destructive else "PASS", ", ".join(map(str, destructive)) or "none"))
        for path in fence:
            findings.append({"category": "path_fence", "detail": f"change outside allowlist: {path}"})
        for path in destructive:
            findings.append({"category": "delete_or_rename", "detail": f"forbidden delete/rename: {path}"})

    # 5/7. semantics: every acceptance check plus reviewer checks need explicit evidence.
    required = list(task_spec["acceptance_checks"]) + list(REVIEWER_CHECKS)
    observations = acceptance_observations if isinstance(acceptance_observations, dict) else {}
    for name in required:
        item = observations.get(name)
        if not isinstance(item, dict) or item.get("result") not in {"PASS", "FAIL"} or not str(item.get("evidence") or "").strip():
            checks.append(_check(f"acceptance:{name}", "UNKNOWN", "no direct evidence")); unknown.append(name)
        elif item["result"] == "FAIL":
            checks.append(_check(f"acceptance:{name}", "FAIL", str(item["evidence"])))
            findings.append({"category": item.get("category") or "semantic_gap", "detail": f"{name}: {item['evidence']}"})
        else:
            checks.append(_check(f"acceptance:{name}", "PASS", str(item["evidence"])))

    # 6. test validity.
    if changed_test_sources is None:
        checks.append(_check("test_validity", "UNKNOWN", "changed test sources not read")); unknown.append("test_sources")
    else:
        vacuous = find_vacuous_tests(changed_test_sources)
        findings.extend(vacuous)
        checks.append(_check("test_validity", "FAIL" if vacuous else "PASS", f"{len(vacuous)} vacuous finding(s)"))

    # 8/9. Claude's own regression run on the exact candidate head/tree.
    ev = test_evidence if isinstance(test_evidence, dict) else None
    if ev is None or ev.get("head_sha") != candidate or ev.get("tree_sha") != candidate_tree or not candidate_tree:
        checks.append(_check("exact_head_tests", "UNKNOWN", "no test run bound to the exact candidate head/tree")); unknown.append("tests")
    elif not isinstance(ev.get("tests_run"), int) or ev["tests_run"] < 1 or ev.get("exit_code") is None:
        checks.append(_check("exact_head_tests", "UNKNOWN", "test run incomplete")); unknown.append("tests")
    elif ev["exit_code"] != 0 or ev.get("failures") != 0 or ev.get("errors") != 0:
        checks.append(_check("exact_head_tests", "FAIL", f"exit={ev['exit_code']} failures={ev.get('failures')} errors={ev.get('errors')}"))
        findings.append({"category": "test_failure", "detail": f"regression run failed on {candidate}"})
    else:
        checks.append(_check("exact_head_tests", "PASS", f"{ev['tests_run']} tests on {candidate}"))

    # 10. evidence consistency.
    checks.append(_check("evidence_binding", "PASS", f"intent {intent['intent_sha256']}"))

    verdict, decision, reason = _decide(findings, unknown, prior_inspections, task_spec, repair_of)
    record = {
        "schema_version": 1,
        "profile": INSPECTION_PROFILE,
        "command_id": request["command_id"],
        "task_id": task_spec["task_id"],
        "intent_sha256": intent["intent_sha256"],
        "candidate_head": candidate,
        "candidate_tree": candidate_tree,
        "repair_of": repair_of,
        "changed_paths": sorted(p for p in changed_paths if isinstance(p, str)),
        "checks": checks,
        "findings": findings,
        "verdict": verdict,
        "decision": decision,
        "reason": reason,
        "inspected_at": inspected_at,
        "self_report_used": False,
    }
    record["inspection_sha256"] = sha256_of(record)
    return InspectionOutcome(verdict, decision, record)


def _family(task_id: str) -> str:
    return re.sub(r"-fix[0-9]+$", "", task_id)


def _decide(findings: list[dict[str, Any]], unknown: list[str], prior: list[dict[str, Any]],
            spec: dict[str, Any], repair_of: str | None) -> tuple[str, str, str]:
    categories = {str(item.get("category")) for item in findings}
    unknown_categories = categories - MINOR_CATEGORIES - MAJOR_CATEGORIES
    family_failures = [p for p in prior if _family(p.get("task_id", "")) == _family(spec["task_id"])
                       and p.get("verdict") in {"FAIL_MINOR", "FAIL_MAJOR"}]
    if not findings and not unknown:
        return "PASS", "ADOPT_CANDIDATE", "all independent checks passed"
    if unknown_categories:
        return "UNKNOWN", "INVESTIGATE", f"unclassified findings: {sorted(unknown_categories)}"
    if unknown and not findings:
        return "UNKNOWN", "INVESTIGATE", f"evidence missing: {sorted(set(unknown))}"
    if len(family_failures) >= 2:
        return "FAIL_MAJOR", "STOP_HUMAN", "repeated failures on the same mission; prompt/architecture review required"
    paths = {item.get("path") for item in findings if item.get("path")}
    allowed = {item["path"] for item in spec["allowed_paths"]}
    small = (
        categories <= MINOR_CATEGORIES and not unknown and repair_of is None
        and len(paths) <= MAX_SMALL_REPAIR_FILES and paths <= allowed
    )
    if small:
        return "FAIL_MINOR", "CLAUDE_SMALL_REPAIR", "localized unambiguous defect; Controller-safe repair"
    if unknown:
        return "UNKNOWN", "INVESTIGATE", "failures found but evidence incomplete; investigate before corrective"
    if family_failures:
        return "FAIL_MAJOR", "JULES_CORRECTIVE_REDUCED", "second failure: corrective with reduced size and sharper negatives"
    return "FAIL_MAJOR", "JULES_CORRECTIVE", "substantial correction needs a new bounded Jules mission"


_INSPECTION_KEYS = {
    "schema_version", "profile", "command_id", "task_id", "intent_sha256", "candidate_head",
    "candidate_tree", "repair_of", "changed_paths", "checks", "findings", "verdict", "decision",
    "reason", "inspected_at", "self_report_used", "inspection_sha256",
}
_DECISIONS = {
    "PASS": {"ADOPT_CANDIDATE"},
    "FAIL_MINOR": {"CLAUDE_SMALL_REPAIR"},
    "FAIL_MAJOR": {"JULES_CORRECTIVE", "JULES_CORRECTIVE_REDUCED", "STOP_HUMAN"},
    "UNKNOWN": {"INVESTIGATE"},
}


def validate_inspection_record(record: Any) -> dict[str, Any]:
    """Re-validate a stored inspection before any decision is taken from it."""
    if not isinstance(record, dict) or set(record) != _INSPECTION_KEYS:
        raise ValueError("inspection record keys mismatch")
    if record["schema_version"] != 1 or record["profile"] != INSPECTION_PROFILE:
        raise ValueError("unsupported inspection record")
    if record["inspection_sha256"] != sha256_of({k: v for k, v in record.items() if k != "inspection_sha256"}):
        raise ValueError("inspection record digest mismatch")
    if record["decision"] not in _DECISIONS.get(record["verdict"], set()):
        raise ValueError("inspection verdict/decision inconsistent")
    if record["self_report_used"] is not False:
        raise ValueError("inspection relied on a self report")
    inspection_path(record["command_id"], record["candidate_head"])
    if record["verdict"] == "PASS":
        if record["findings"] or any(c.get("state") != "PASS" for c in record["checks"]) or not record["checks"]:
            raise ValueError("PASS inspection carries non-PASS checks or findings")
        if not _SHA40.fullmatch(record["candidate_tree"] or ""):
            raise ValueError("PASS inspection lacks the candidate tree")
    if record["repair_of"] is not None and not _SHA40.fullmatch(record["repair_of"]):
        raise ValueError("invalid repair_of")
    return record


class InspectionStore:
    def __init__(self, client: GitHubContentsClient, *, data_branch: str):
        self.client, self.branch = client, data_branch

    def persist(self, record: dict[str, Any]) -> str:
        path = inspection_path(record["command_id"], record["candidate_head"])
        validate_inspection_record(record)
        existing = self.client.get(path, self.branch)
        if existing is not None:
            return "RECOVERED" if json.loads(existing.text) == record else "BLOCKED"
        try:
            self.client.create(path, canonical_json(record), f"Claude AUTO inspection {record['verdict']}", self.branch)
        except Exception:
            pass  # readback decides; never resend
        readback = self.client.get(path, self.branch)
        if readback is None or json.loads(readback.text) != record:
            return "UNKNOWN"
        return "CREATED"

    def get(self, command_id: str, head_sha: str) -> dict[str, Any] | None:
        content = self.client.get(inspection_path(command_id, head_sha), self.branch)
        return None if content is None else json.loads(content.text)

    def list_all(self) -> list[dict[str, Any]]:
        prefix = f"{EVIDENCE_ROOT}/claude-auto-inspections/"
        records = []
        for content in self.client.list(prefix, self.branch):
            record = validate_inspection_record(json.loads(content.text))
            if content.path != inspection_path(record["command_id"], record["candidate_head"]):
                raise ValueError("inspection record path mismatch")
            records.append(record)
        return records


def validate_small_repair(
    *, inspection: dict[str, Any], task_spec: dict[str, Any], repair_compare: dict[str, Any] | None,
    repairs_already_made: int,
) -> tuple[str, str]:
    """Gate a Claude small-repair candidate before it is re-inspected."""
    validate_task_spec(task_spec)
    if inspection.get("decision") != "CLAUDE_SMALL_REPAIR":
        return "BLOCKED", "inspection did not select a small repair"
    if repairs_already_made >= MAX_SMALL_REPAIRS_PER_COMMAND:
        return "BLOCKED", "small-repair budget used; prepare a Jules corrective instead"
    if not isinstance(repair_compare, dict):
        return "UNKNOWN", "repair compare unavailable"
    if repair_compare.get("base_sha") != inspection["candidate_head"] or repair_compare.get("behind_by") != 0:
        return "BLOCKED", "repair must descend from the inspected candidate"
    allowed = {item["path"] for item in task_spec["allowed_paths"]}
    files = repair_compare.get("files") or []
    if not files or len(files) > MAX_SMALL_REPAIR_FILES:
        return "BLOCKED", "repair must touch 1..2 files"
    for item in files:
        if item.get("status") != "modified" or item.get("path") not in allowed:
            return "BLOCKED", f"repair outside fence: {item.get('path')}"
    return "PASS", "small repair stays within fence; re-inspect the repaired head"
