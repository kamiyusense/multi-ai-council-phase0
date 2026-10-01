"""BWJ-6 formal candidates only. No claim reservation, branch or command write.

Reuse the carrier schema-v3 claim and formal V2 request validators verbatim.
Every candidate must be re-collected/reserved/read back before a future dispatch.
"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta
import re
from typing import Any

from .blue_jules_result_event import EXPECTED_REPOSITORY
from .blue_work_reconcile_prepare import _sha, _time
from .cloud_work_lanes import lane_identity
from .loop_id_claim import DUPLICATE_GUARD, claim_filename, extract_numbered_loop, lane_display_for
from .jules_result_lineage import validate_formal_command

PROMPT_SECTIONS = ("Goal:", "Read first:", "Allowed changed paths only:", "Hard scope / Do Not Touch:",
                   "Reuse-first:", "Required semantics:", "Negative/tamper cases:", "Acceptance criteria:",
                   "Validation:", "Publication:", "Stop and report instead of guessing if:")


def _reserved_number(command_id: str) -> int | None:
    parsed = extract_numbered_loop(command_id)
    if parsed is not None:
        return int(parsed[0])
    # Current GitHub retains historical 015b/043b corrective IDs. Protect their
    # numeric namespace; this never validates them for a fresh dispatch.
    legacy = re.fullmatch(r"relay-dev-loop-([0-9]{3,6})[a-z]-[a-z0-9][a-z0-9._-]{0,63}", command_id)
    return int(legacy[1]) if legacy else None


@dataclass(frozen=True)
class NextTaskPlan:
    status: str
    reason: str
    claim: dict | None = None
    command: dict | None = None
    claim_path: str | None = None
    command_path: str | None = None
    external_write_attempted: bool = False
    reservation_state: str = "NOT_RESERVED"


def used_loop_numbers(*, tree_entries: Any, branch_refs: Any, complete: Any) -> set[int]:
    if complete is not True or not isinstance(tree_entries, list) or not isinstance(branch_refs, list):
        raise ValueError("complete global claims/commands/work branches required")
    used: set[int] = set()
    paths = set()
    for row in tree_entries:
        if not isinstance(row, dict) or not isinstance(row.get("path"), str):
            raise ValueError("global ledger tree unreadable")
        path = row["path"]
        if path in paths:
            raise ValueError("duplicate ledger path")
        paths.add(path)
        if path.startswith("automation/command_bus/loop_id_claims/"):
            if row.get("type") == "tree":
                continue
            match = re.fullmatch(r"automation/command_bus/loop_id_claims/([0-9]{3,6})\.json", path)
            if match is None or row.get("type") != "blob":
                raise ValueError("malformed global claim path")
            used.add(int(match[1]))
        if path.startswith("automation/command_bus/jules_api_requests/relay-dev-loop-"):
            number = _reserved_number(path.rsplit("/", 1)[-1].removesuffix(".json"))
            if number is None or not path.endswith(".json"):
                raise ValueError("malformed numbered command path")
            used.add(number)
    seen_refs = set()
    for row in branch_refs:
        if not isinstance(row, dict) or not isinstance(row.get("ref"), str) or row["ref"] in seen_refs:
            raise ValueError("work branch refs unreadable/duplicate")
        ref = row["ref"]
        seen_refs.add(ref)
        if ref.startswith("refs/heads/jules-work/relay-dev-loop-"):
            # Jules descendant branches can append a provider suffix longer
            # than command_id's formal size. Reserve the numeric prefix only;
            # such a descendant is never accepted as a dispatch command.
            match = re.fullmatch(r"refs/heads/jules-work/relay-dev-loop-([0-9]{3,6})[a-z]?-[a-z0-9][a-z0-9._-]*", ref)
            if match is None:
                raise ValueError("malformed Jules work branch")
            used.add(int(match[1]))
    return used


def prepare_next_jules(*, lane: str, task_id: str, prompt: str, allowed_paths: list[str],
                       target: Any, tree_entries: Any, branch_refs: Any, ledger_complete: Any,
                       now: datetime, expires_at: str, review_decision: str,
                       previous_finding: str | None = None, current_finding: str | None = None,
                       meaningful_delta: bool | None = None) -> NextTaskPlan:
    try:
        metadata = lane_identity(lane)
        if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("aware current time required")
        if review_decision != "PASS":
            return NextTaskPlan("BLOCKED", "independent captured review PASS required; no automatic corrective dispatch")
        if previous_finding is not None and previous_finding == current_finding and meaningful_delta is not True:
            return NextTaskPlan("BLOCKED", "same finding without meaningful corrective delta; diagnose before another task")
        if not isinstance(target, dict) or target.get("repository") != EXPECTED_REPOSITORY:
            raise ValueError("fresh target repository unavailable")
        if not _sha(target.get("head")) or not _sha(target.get("tree")):
            raise ValueError("fresh target HEAD/tree unavailable")
        if target.get("expected_head") != target["head"] or target.get("expected_tree") != target["tree"]:
            return NextTaskPlan("STALE", "target HEAD/tree changed")
        used = used_loop_numbers(tree_entries=tree_entries, branch_refs=branch_refs, complete=ledger_complete)
        number = max(used, default=0) + 1
        if number > 999999:
            raise ValueError("global Loop namespace exhausted")
        loop_id = f"{number:03d}"
        command_id = f"relay-dev-loop-{loop_id}-{task_id}"
        if not isinstance(task_id, str) or extract_numbered_loop(command_id) is None:
            raise ValueError("task identity invalid")
        if not isinstance(prompt, str) or any(section not in prompt for section in PROMPT_SECTIONS):
            raise ValueError("formal Task Prompt sections missing")
        if not all(bound in prompt for bound in ("retry=0", "fallback=disabled", "no Merge", "no live", "no vacuous tests")):
            raise ValueError("Task Prompt safety/acceptance bounds missing")
        if _time(expires_at) > now + timedelta(hours=2):
            raise ValueError("next task expiry exceeds formal lifetime")
        claim = {"schema_version": 3, "loop_number": number, "loop_id": loop_id, "task_id": task_id,
                 "command_id": command_id, "target_branch": target.get("branch"), "expected_target_head": target["head"],
                 "work_branch": f"jules-work/{command_id}", "state": "CLAIMED", "claimed_at": now.isoformat(),
                 "duplicate_guard": DUPLICATE_GUARD, "retry": 0, "fallback": "disabled",
                 "lane_id": metadata["jules_lane"], "lane_display": lane_display_for(metadata["jules_lane"]),
                 "expected_target_tree": target["tree"]}
        command = {"schema_version": 2, "profile": "JULES_CHAT_SEMIAUTO_V2", "command_id": command_id,
                   "target_repo": EXPECTED_REPOSITORY, "target_branch": target.get("branch"),
                   "work_branch": claim["work_branch"], "expected_target_head": target["head"],
                   "expected_target_tree": target["tree"], "allowed_paths": deepcopy(allowed_paths),
                   "prompt": prompt, "created_at": now.isoformat(), "expires_at": expires_at,
                   "retry": 0, "fallback": "disabled", "merge_allowed": False, "force_push_allowed": False}
        validate_formal_command(command, claim, now=now)
        return NextTaskPlan("PREPARED", "formal candidate only; global reservation and publication NOT performed",
                            claim, command, "automation/command_bus/loop_id_claims/" + claim_filename(loop_id),
                            f"automation/command_bus/jules_api_requests/{command_id}.json")
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return NextTaskPlan("UNKNOWN", str(exc))


def recheck_next_jules(plan: NextTaskPlan, *, target: dict, tree_entries: list,
                       branch_refs: list, ledger_complete: bool, now: datetime) -> NextTaskPlan:
    """Check an unreserved candidate again. Never move to RESERVED/SENT."""
    try:
        if not isinstance(plan, NextTaskPlan) or plan.status != "PREPARED" or plan.reservation_state != "NOT_RESERVED":
            raise ValueError("unreserved prepared candidate required")
        validate_formal_command(plan.command, plan.claim, now=now)
        if (plan.external_write_attempted is not False
                or plan.claim_path != "automation/command_bus/loop_id_claims/" + claim_filename(plan.claim["loop_id"])
                or plan.command_path != f"automation/command_bus/jules_api_requests/{plan.command['command_id']}.json"):
            raise ValueError("next package publication paths/state mismatch")
        if (target.get("repository") != plan.command["target_repo"] or target.get("branch") != plan.command["target_branch"]
                or target.get("head") != plan.claim["expected_target_head"] or target.get("tree") != plan.claim["expected_target_tree"]):
            return NextTaskPlan("STALE", "canonical target changed before reservation")
        used = used_loop_numbers(tree_entries=tree_entries, branch_refs=branch_refs, complete=ledger_complete)
        if plan.claim["loop_number"] in used:
            return NextTaskPlan("BLOCKED", "global Loop collision; no retry or new number chosen automatically")
        return plan
    except (ValueError, TypeError, KeyError, AttributeError) as exc:
        return NextTaskPlan("UNKNOWN", str(exc))
