"""Pure, minimal durable Session capture contract; never authenticates JSON.

Future authorized callers project a CREATE response immediately, and a GET
response at completion. Exact provider time is retained, not reconstructed
from a seconds-only log. No API, secret, prompt, raw body or dispatch function.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from typing import Any

from .blue_jules_result_event import EXPECTED_REPOSITORY
from .blue_work_reconcile_prepare import _positive, _sha
from .cloud_work_lanes import lane_identity
from .jules_result_lineage import validate_formal_command
from .jules_session_readonly import _exact_time

KINDS = {"JULES_CREATE_RESPONSE", "JULES_GET_RESPONSE"}
STATES = {"QUEUED", "PLANNING", "AWAITING_PLAN_APPROVAL", "AWAITING_USER_FEEDBACK",
          "IN_PROGRESS", "PAUSED", "FAILED", "COMPLETED"}
KEYS = {"schema_version", "authentication", "source_kind", "session_id", "create_time",
        "repository", "starting_branch", "command_id", "loop_id", "lane", "target_branch",
        "target_head", "target_tree", "dispatch_commit", "dispatch_run", "dispatch_job",
        "captured_at", "state", "output_prs", "update_time", "retry", "fallback"}
ERROR = "Session capture unavailable or inconsistent"


def capture_session_evidence(provider: Any, *, request: dict, claim: dict,
                             dispatch_run: dict, dispatch_job: dict, source_kind: str,
                             captured_at: str, now: datetime) -> dict:
    """Allowlist projection. Output is UNAUTHENTICATED_CAPTURE, never PASS.

    Provider outputs 0/2 can be recorded for diagnosis, but cannot authenticate
    a unique completed result. Unknown output shapes/URLs are rejected outright.
    """
    try:
        validate_formal_command(request, claim, now=now, historical=True)
        if source_kind not in KINDS or not isinstance(provider, dict):
            raise ValueError(ERROR)
        name = provider.get("name")
        if not isinstance(name, str) or not re.fullmatch(r"sessions/[0-9]+", name):
            raise ValueError(ERROR)
        create = provider.get("createTime")
        instant, observed = _exact_time(create), _exact_time(captured_at)
        if not (_exact_time(request["created_at"]) <= instant < _exact_time(request["expires_at"])
                and instant <= observed <= _exact_time(now.isoformat())):
            raise ValueError(ERROR)
        if source_kind == 'JULES_CREATE_RESPONSE' and observed >= _exact_time(request['expires_at']):
            raise ValueError(ERROR)
        context = provider.get("sourceContext")
        if (not isinstance(context, dict) or context.get("source") != "sources/github/" + EXPECTED_REPOSITORY
                or context.get("githubRepoContext", {}).get("startingBranch") != request["work_branch"]):
            raise ValueError(ERROR)
        state = provider.get("state")
        if state not in STATES:
            raise ValueError(ERROR)
        if (not _positive(dispatch_run.get("id")) or not _sha(dispatch_run.get("head_sha"))
                or dispatch_run.get("repository", {}).get("full_name") != EXPECTED_REPOSITORY
                or dispatch_run.get("event") != "push"
                or dispatch_run.get("path") != ".github/workflows/jules-chat-semiauto.yml"
                or type(dispatch_run.get("run_attempt")) is not int or dispatch_run["run_attempt"] != 1
                or not _positive(dispatch_job.get("id")) or dispatch_job.get("run_id") != dispatch_run["id"]
                or dispatch_job.get("head_sha") != dispatch_run["head_sha"]):
            raise ValueError(ERROR)
        outputs = provider.get("outputs", [])
        if not isinstance(outputs, list):
            raise ValueError(ERROR)
        prs = []
        for output in outputs:
            if not isinstance(output, dict) or not isinstance(output.get("pullRequest"), dict):
                raise ValueError(ERROR)
            url = output["pullRequest"].get("url")
            match = re.fullmatch(r"https://github\.com/" + re.escape(EXPECTED_REPOSITORY) + r"/pull/([1-9][0-9]*)", url) if isinstance(url, str) else None
            if match is None:
                raise ValueError(ERROR)
            prs.append(int(match[1]))
        update = provider.get("updateTime")
        if update is not None and not instant <= _exact_time(update) <= observed:
            raise ValueError(ERROR)
        lane = next(l for l in ("blue", "yellow", "green", "red") if lane_identity(l)["jules_lane"] == claim["lane_id"])
        return {"schema_version": 1, "authentication": "UNAUTHENTICATED_CAPTURE",
                "source_kind": source_kind, "session_id": name.split("/")[1], "create_time": create,
                "repository": EXPECTED_REPOSITORY, "starting_branch": request["work_branch"],
                "command_id": request["command_id"], "loop_id": claim["loop_id"], "lane": lane,
                "target_branch": request["target_branch"], "target_head": request["expected_target_head"],
                "target_tree": request["expected_target_tree"], "dispatch_commit": dispatch_run["head_sha"],
                "dispatch_run": dispatch_run["id"], "dispatch_job": dispatch_job["id"],
                "captured_at": captured_at, "state": state, "output_prs": prs,
                "update_time": update, "retry": 0, "fallback": "disabled"}
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, StopIteration):
        raise ValueError(ERROR) from None


def validate_session_evidence(evidence: Any, *, source: dict, now: datetime) -> None:
    """Reproject the stored contract and cross-bind formal source identities."""
    try:
        if (not isinstance(evidence, dict) or set(evidence) != KEYS
                or type(evidence["schema_version"]) is not int or evidence["schema_version"] != 1
                or type(evidence["retry"]) is not int or evidence["retry"] != 0
                or evidence["fallback"] != "disabled"
                or not isinstance(evidence["output_prs"], list)
                or any(not _positive(p) for p in evidence["output_prs"])):
            raise ValueError(ERROR)
        provider = {"name": "sessions/" + evidence["session_id"], "createTime": evidence["create_time"],
                    "state": evidence["state"], "sourceContext": {"source": "sources/github/" + evidence["repository"],
                    "githubRepoContext": {"startingBranch": evidence["starting_branch"]}},
                    "outputs": [{"pullRequest": {"url": f"https://github.com/{EXPECTED_REPOSITORY}/pull/{p}"}} for p in evidence["output_prs"]]}
        if evidence["update_time"] is not None:
            provider["updateTime"] = evidence["update_time"]
        projected = capture_session_evidence(provider, request=source["request"], claim=source["claim"],
                    dispatch_run=source["dispatch_run"], dispatch_job=source["dispatch_job"],
                    source_kind=evidence["source_kind"], captured_at=evidence["captured_at"], now=now)
        if projected != evidence:
            raise ValueError(ERROR)
    except (ValueError, TypeError, KeyError, AttributeError):
        raise ValueError(ERROR) from None


def _validate_capture_pair(acceptance: Any, completed: Any, *, source: dict, now: datetime) -> None:
    """Exact capture bindings, not provider authentication or adoption."""
    validate_session_evidence(acceptance, source=source, now=now)
    validate_session_evidence(completed, source=source, now=now)
    stable = KEYS - {"source_kind", "captured_at", "state", "output_prs", "update_time", "create_time"}
    if (acceptance["source_kind"] != "JULES_CREATE_RESPONSE" or completed["source_kind"] != "JULES_GET_RESPONSE"
            or any(acceptance[k] != completed[k] for k in stable)
            or _exact_time(acceptance["create_time"]) != _exact_time(completed["create_time"])
            or _exact_time(acceptance["captured_at"]) > _exact_time(completed["captured_at"])
            or completed["state"] != "COMPLETED"
            or completed["output_prs"] != [source["result_pr"]["number"]]
            or _exact_time(source["acceptance"]["createTime"]) != _exact_time(acceptance["create_time"])
            or _exact_time(source["session_readback"]["createTime"]) != _exact_time(completed["create_time"])
            or source["acceptance"]["name"] != "sessions/" + acceptance["session_id"]
            or source["session_readback"]["name"] != "sessions/" + completed["session_id"]):
        raise ValueError(ERROR)


def validate_capture_pair(acceptance: Any, completed: Any, *, source: dict, now: datetime) -> None:
    try:
        _validate_capture_pair(acceptance, completed, source=source, now=now)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        raise ValueError(ERROR) from None


def evidence_fingerprint(evidence: dict) -> str:
    """Content identity only; a hash does not authenticate its origin."""
    return hashlib.sha256(json.dumps(evidence, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
