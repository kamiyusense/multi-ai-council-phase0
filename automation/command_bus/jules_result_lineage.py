"""Validate captured formal claim/command/dispatch/session/result bindings.

This pure check does not authenticate arbitrary JSON or perform a Jules GET.
Production callers must supply authenticated readbacks; mock replay remains
MOCK. A branch name, actor or PR title alone never establishes Jules lineage.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import re
from typing import Any

from .blue_jules_result_event import EXPECTED_REPOSITORY, EventLineage
from .blue_work_reconcile_prepare import _positive, _sha, _time
from .cloud_work_lanes import lane_identity
from .jules_semiauto_request_v2 import validate_request
from .loop_id_claim import verify_command_claim
from .jules_session_acceptance import extract_session_acceptance, verify_session_acceptance_readback
from .jules_session_readonly import _exact_time


def validate_formal_command(request: dict[str, Any], claim: dict[str, Any], *, now: datetime,
                            historical: bool = False) -> None:
    if not isinstance(now, datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("aware clock required")
    if (not isinstance(request, dict) or type(request.get("schema_version")) is not int
            or type(request.get("retry")) is not int or not isinstance(claim, dict)
            or type(claim.get("schema_version")) is not int or type(claim.get("retry")) is not int):
        raise ValueError("formal schema/retry types invalid")
    # Archived expired commands may establish source lineage, never dispatch.
    at = _time(request["created_at"]) if historical else now
    validate_request(request, now=at)
    if _time(request["created_at"]) > now or _time(claim["claimed_at"]) > _time(request["created_at"]):
        raise ValueError("future command or claim after command")
    verify_command_claim(request, claim, require_dispatchable_current=True)


@dataclass(frozen=True)
class LineageDecision:
    status: str
    reason: str
    lineage: EventLineage | None = None
    session_id: str | None = None
    lane: str | None = None
    result_pr: int | None = None
    result_head: str | None = None
    result_tree: str | None = None
    allowed_paths: tuple[str, ...] | None = None


def verify_result_lineage(*, lane: str, request: Any, claim: Any, command_commit: Any,
                          dispatch_run: Any, dispatch_job: Any, dispatch_log: Any,
                          acceptance: Any, session_readback: Any,
                          result_pr: Any, comparison: Any, now: datetime,
                          result_commit: Any = None) -> LineageDecision:
    try:
        identity = lane_identity(lane)
        validate_formal_command(request, claim, now=now, historical=True)
        if claim["lane_id"] != identity["jules_lane"]:
            raise ValueError("Jules lane mismatch")
        if not isinstance(command_commit, dict) or not _sha(command_commit.get("sha")):
            raise ValueError("command commit unavailable")
        files = command_commit.get("files")
        if not isinstance(files, list) or len(files) != 1 or files[0].get("filename") != (
                "automation/command_bus/jules_api_requests/" + request["command_id"] + ".json") or files[0].get("status") != "added":
            raise ValueError("command publication was not one append-only file")
        if (not isinstance(dispatch_run, dict) or not _positive(dispatch_run.get("id"))
                or dispatch_run.get("head_sha") != command_commit["sha"]
                or dispatch_run.get("path") != ".github/workflows/jules-chat-semiauto.yml"
                or dispatch_run.get("event") != "push" or dispatch_run.get("status") != "completed"
                or dispatch_run.get("conclusion") != "success"
                or type(dispatch_run.get("run_attempt")) is not int or dispatch_run["run_attempt"] != 1
                or dispatch_run.get("repository", {}).get("full_name") != EXPECTED_REPOSITORY):
            raise ValueError("dispatch workflow binding unavailable")
        accepted = extract_session_acceptance(acceptance, expected_branch=request["work_branch"])
        observed = verify_session_acceptance_readback(accepted, session_readback)
        if _exact_time(acceptance.get("createTime")) != _exact_time(session_readback.get("createTime")):
            raise ValueError("exact provider createTime differs from acceptance capture")
        if "updateTime" in session_readback and _exact_time(session_readback["updateTime"]) < _exact_time(session_readback["createTime"]):
            raise ValueError("provider updateTime precedes createTime")
        if (not isinstance(dispatch_job, dict) or not _positive(dispatch_job.get("id"))
                or dispatch_job.get("run_id") != dispatch_run["id"]
                or dispatch_job.get("head_sha") != command_commit["sha"]
                or dispatch_job.get("status") != "completed" or dispatch_job.get("conclusion") != "success"
                or not isinstance(dispatch_log, str)):
            raise ValueError("dispatch job/log binding unavailable")
        # Match executed output, excluding echoed shell source/variable text.
        accepted_names = re.findall(r"(?m)^(?:[0-9TZ:.-]+ )?Jules session accepted: (sessions/[0-9]+)\s*$", dispatch_log)
        if accepted_names != [accepted.session_name]:
            raise ValueError("dispatch log session acceptance mismatch/ambiguous")
        timing_lines = re.findall(r"(?m)^(?:[0-9TZ:.-]+ )?Jules session timing read back: (sessions/[0-9]+) at ([^\s]+)\s*$", dispatch_log)
        if timing_lines != [(accepted.session_name, accepted.accepted_at_jst)]:
            raise ValueError("dispatch log executed timing readback missing/ambiguous")
        accepted_at = _time(accepted.session_create_time)
        if not (_time(request["created_at"]) <= accepted_at < _time(request["expires_at"]) and accepted_at <= now):
            raise ValueError("session acceptance outside command lifetime")
        for record in (acceptance, session_readback):
            if record.get("sourceContext", {}).get("source") != "sources/github/" + EXPECTED_REPOSITORY:
                raise ValueError("session repository mismatch")
        if session_readback.get("state") != "COMPLETED":
            raise ValueError("Jules result session not completed")
        if not isinstance(result_pr, dict) or not _positive(result_pr.get("number")):
            raise ValueError("result PR identity missing")
        if result_pr.get("state") != "open" or result_pr.get("merged") is not False:
            raise ValueError("result PR not open/unmerged")
        for side in ("head", "base"):
            if result_pr.get(side, {}).get("repo", {}).get("full_name") != EXPECTED_REPOSITORY:
                raise ValueError("result repository/fork mismatch")
        if (result_pr["base"].get("ref") != request["work_branch"]
                or result_pr["base"].get("sha") != request["expected_target_head"]
                or not _sha(result_pr["head"].get("sha"))):
            raise ValueError("result base/HEAD mismatch")
        expected_url = f"https://github.com/{EXPECTED_REPOSITORY}/pull/{result_pr['number']}"
        outputs = session_readback.get("outputs")
        if not isinstance(outputs, list) or len(outputs) != 1 or any(not isinstance(x, dict) for x in outputs):
            raise ValueError("session outputs unavailable")
        pr_outputs = [x["pullRequest"] for x in outputs if "pullRequest" in x]
        if len(pr_outputs) != 1 or not isinstance(pr_outputs[0], dict) or pr_outputs[0].get("url") != expected_url:
            raise ValueError("session output does not uniquely identify result PR")
        if (not isinstance(comparison, dict) or comparison.get("status") not in {"ahead", "identical"}
                or comparison.get("base_commit", {}).get("sha") != request["expected_target_head"]
                or comparison.get("merge_base_commit", {}).get("sha") != request["expected_target_head"]):
            raise ValueError("exact result ancestry unavailable")
        if comparison["base_commit"].get("commit", {}).get("tree", {}).get("sha") != request["expected_target_tree"]:
            raise ValueError("comparison base tree does not match formal snapshot")
        if (not isinstance(result_commit, dict) or result_commit.get("sha") != result_pr["head"]["sha"]
                or not _sha(result_commit.get("tree", {}).get("sha"))):
            raise ValueError("pinned result Git commit HEAD/tree unavailable")
        # REST compare returns commits, NOT a head_commit field. Require all
        # pages (total_commits) and the actual final SHA, even beyond 250 commits.
        commits = comparison.get("commits")
        total = comparison.get("total_commits")
        if type(total) is not int or not isinstance(commits, list) or len(commits) != total:
            raise ValueError("comparison commits incomplete")
        shas = [c.get("sha") for c in commits if isinstance(c, dict)]
        if len(shas) != total or any(not _sha(s) for s in shas) or len(set(shas)) != total:
            raise ValueError("comparison commit identities invalid")
        if comparison["status"] == "ahead":
            if not shas or shas[-1] != result_pr["head"]["sha"]:
                raise ValueError("comparison final HEAD mismatch")
        elif total != 0 or result_pr["head"]["sha"] != request["expected_target_head"]:
            raise ValueError("identical comparison HEAD mismatch")
        return LineageDecision("VERIFIED_SNAPSHOT", "captured lineage bindings verified; source authentication is caller responsibility",
                               EventLineage(request["command_id"], request["work_branch"], request["expected_target_head"], EXPECTED_REPOSITORY),
                               observed.session_id, lane, result_pr["number"], result_pr["head"]["sha"],
                               result_commit["tree"]["sha"], tuple(request["allowed_paths"]))
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError) as exc:
        return LineageDecision("UNKNOWN", str(exc))
