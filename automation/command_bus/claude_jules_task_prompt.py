"""Bounded Jules task specification and prompt renderer for the Claude AUTO loop.

The renderer emits the twelve sections required by the carrier's
``docs/JULES_TASK_PROMPT_SPEC.md`` (section 3) in their mandatory order.  A
task specification is a plain JSON object so the Claude controller can keep
its roadmap and corrective tasks as durable GitHub records.  Pure code: no I/O.
"""
from __future__ import annotations

import copy
import re
from typing import Any

SIZE_CLASSES = ("SHORT", "MEDIUM", "LONG")
TASK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,39}$")
CHECK_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,63}$")
_GLOB = re.compile(r"[*?\[\]]")
# Commands that never terminate on their own are forbidden (spec section 12).
_OPEN_ENDED = re.compile(
    r"(runserver|--watch|\bwatch\b|\bserve\b|npm start|yarn start|tail -f|sleep\s+\d{3,}|while true)",
    re.IGNORECASE,
)
# Keep room for the operation-bounds suffix and the carrier wrapper (12000 cap).
MAX_TASK_PROMPT_CHARS = 9000
MANDATORY_DO_NOT_TOUCH = (
    "retry=0",
    "fallback=disabled",
    "no Merge",
    "no direct default-branch write",
    "no force push, history rewrite, rebase or branch deletion",
    "no live provider/model/API call",
    "no secrets, credentials, billing, settings or permission changes",
    "no workflow changes unless a workflow path is explicitly allowed",
)
MANDATORY_ACCEPTANCE = (
    "Each semantic requirement above has a direct assertion/proof.",
    "No vacuous tests (`pass`, `assertTrue(True)`, unrelated assertions).",
    "Changed paths are exactly within the allowlist.",
    "Existing green tests alone are not sufficient.",
)
MANDATORY_STOP = (
    "an out-of-scope change is required",
    "a safety/permission/live/architecture boundary is reached",
    "the checked-out work branch is not the expected snapshot",
)
_LIST_FIELDS = (
    "read_first", "do_not_touch", "reuse", "semantics", "negative_cases",
    "acceptance", "validation_commands", "stop_conditions",
)
REQUIRED_KEYS = {
    "schema_version", "task_id", "size", "task_class", "goal", "non_goals",
    "allowed_paths", "acceptance_checks", "publication", *_LIST_FIELDS,
}


def validate_task_spec(spec: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(spec, dict) or set(spec) != REQUIRED_KEYS:
        raise ValueError("task spec keys mismatch")
    if spec["schema_version"] != 1 or isinstance(spec["schema_version"], bool):
        raise ValueError("unsupported task spec schema")
    if not isinstance(spec["task_id"], str) or not TASK_ID_RE.fullmatch(spec["task_id"]):
        raise ValueError("invalid task_id")
    if spec["size"] not in SIZE_CLASSES:
        raise ValueError("size must be SHORT, MEDIUM or LONG")
    for key in ("task_class", "goal", "non_goals", "publication"):
        if not isinstance(spec[key], str) or not spec[key].strip():
            raise ValueError(f"{key} must be non-empty text")
    for key in _LIST_FIELDS:
        value = spec[key]
        if not isinstance(value, list) or not value or any(
            not isinstance(item, str) or not item.strip() or "\x00" in item for item in value
        ):
            raise ValueError(f"{key} must be a non-empty list of text")
    for command in spec["validation_commands"]:
        if _OPEN_ENDED.search(command):
            raise ValueError("validation commands must be finite")
    paths = spec["allowed_paths"]
    if not isinstance(paths, list) or not 1 <= len(paths) <= 20:
        raise ValueError("allowed_paths must contain 1..20 entries")
    seen: set[str] = set()
    for item in paths:
        if not isinstance(item, dict) or set(item) != {"path", "allowed_ops"}:
            raise ValueError("allowed path entry must be {path, allowed_ops}")
        path, ops = item["path"], item["allowed_ops"]
        if (not isinstance(path, str) or not path or _GLOB.search(path) or path.startswith("/")
                or ".." in path.split("/") or path.endswith("/") or "\\" in path):
            raise ValueError("allowed paths must be exact relative file paths")
        if path in seen:
            raise ValueError("duplicate allowed path")
        if not isinstance(ops, list) or not ops or any(op not in {"ADD", "MODIFY"} for op in ops) or len(set(ops)) != len(ops):
            raise ValueError("allowed_ops permits only ADD/MODIFY")
        seen.add(path)
    checks = spec["acceptance_checks"]
    if not isinstance(checks, list) or not checks or len(set(checks)) != len(checks) or any(
        not isinstance(item, str) or not CHECK_ID_RE.fullmatch(item) for item in checks
    ):
        raise ValueError("acceptance_checks must be unique machine check ids")
    return spec


def render_task_prompt(spec: dict[str, Any], *, loop_label: str) -> str:
    """Render the mandatory 12-section bounded prompt for one Jules mission."""
    validate_task_spec(spec)
    if not isinstance(loop_label, str) or not re.fullmatch(r"Loop [0-9]{3,6}", loop_label):
        raise ValueError("loop_label must be 'Loop NNN'")

    def bullets(items: list[str] | tuple[str, ...]) -> str:
        return "\n".join(f"- {item.strip()}" for item in items)

    def numbered(items: list[str]) -> str:
        return "\n".join(f"{index}. {item.strip()}" for index, item in enumerate(items, 1))

    do_not_touch = list(spec["do_not_touch"]) + [x for x in MANDATORY_DO_NOT_TOUCH if x not in spec["do_not_touch"]]
    acceptance = list(spec["acceptance"]) + [x for x in MANDATORY_ACCEPTANCE if x not in spec["acceptance"]]
    acceptance.append("Machine acceptance check ids: " + ", ".join(spec["acceptance_checks"]))
    stops = list(spec["stop_conditions"]) + [x for x in MANDATORY_STOP if x not in spec["stop_conditions"]]
    sections = [
        f"{loop_label} — bounded {spec['size']} {spec['task_class'].strip()}.",
        f"Goal:\n{spec['goal'].strip()}\nNon-goals: {spec['non_goals'].strip()}",
        f"Read first:\n{bullets(spec['read_first'])}",
        "Allowed changed paths only:\n" + "\n".join(
            f"- {item['path']} ({','.join(item['allowed_ops'])})" for item in spec["allowed_paths"]
        ),
        f"Hard scope / Do Not Touch:\n{bullets(do_not_touch)}",
        f"Reuse-first:\n{bullets(spec['reuse'])}\n- Do not duplicate or weaken accepted semantics.",
        f"Required semantics:\n{numbered(spec['semantics'])}",
        f"Negative/tamper cases:\n{bullets(spec['negative_cases'])}",
        f"Acceptance criteria:\n{bullets(acceptance)}",
        f"Validation:\n{chr(10).join(spec['validation_commands'])}",
        f"Publication:\n{spec['publication'].strip()}\nDo not Merge.",
        f"Stop and report instead of guessing if:\n{bullets(stops)}",
    ]
    prompt = "\n\n".join(sections)
    if len(prompt) > MAX_TASK_PROMPT_CHARS:
        raise ValueError("rendered task prompt exceeds bounded size")
    return prompt


def path_policy(spec: dict[str, Any]) -> list[dict[str, Any]]:
    validate_task_spec(spec)
    return [copy.deepcopy(item) for item in spec["allowed_paths"]]


def corrective_task_spec(spec: dict[str, Any], *, attempt: int, findings: list[dict[str, Any]],
                         reduce_size: bool = False) -> dict[str, Any]:
    """Derive a new bounded corrective mission from an inspected failure.

    The corrective gets its own task id (and therefore its own Loop claim,
    command and work branch); it is never a resend of the original command.
    """
    validate_task_spec(spec)
    if isinstance(attempt, bool) or not isinstance(attempt, int) or not 1 <= attempt <= 5:
        raise ValueError("corrective attempt must be 1..5")
    if not findings:
        raise ValueError("corrective task requires concrete findings")
    base = re.sub(r"-fix[0-9]+$", "", spec["task_id"])
    new = copy.deepcopy(spec)
    new["task_id"] = f"{base[:34]}-fix{attempt}"
    if reduce_size:
        new["size"] = {"LONG": "MEDIUM", "MEDIUM": "SHORT", "SHORT": "SHORT"}[spec["size"]]
    new["task_class"] = f"corrective for {spec['task_id']}: {spec['task_class']}"
    details = []
    for item in findings:
        category = item.get("category") if isinstance(item, dict) else None
        detail = item.get("detail") if isinstance(item, dict) else None
        if not isinstance(category, str) or not isinstance(detail, str) or not detail.strip():
            raise ValueError("finding requires category and detail")
        details.append(f"Fix independently observed {category}: {detail.strip()}")
    new["semantics"] = details + list(spec["semantics"])
    validate_task_spec(new)
    return new
