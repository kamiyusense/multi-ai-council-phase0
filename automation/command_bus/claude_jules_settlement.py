"""Provider-settlement source for the Claude AUTO timeout path (STATIC contract + read-only adapter).

A task timeout must never start another provider while the first one may still
be working.  ``ClaudeJulesAutoLoop`` therefore isolates a timed-out task only
when the reconciler reports ``SETTLED``.  Until now the production reconciler
only re-read result PRs and always answered ``UNKNOWN``.

This module defines where a positive settlement can come from without creating
new authority:

* The existing carrier workflow ``jules-session-readback.yml`` performs ONE
  Jules session GET per append-only status request
  (``automation/command_bus/jules_api_status_requests/<name>.json``) and prints
  ``Jules session readback: name=sessions/<id> state=<STATE> pr_url=<url|NONE>``.
  Adding such a request is a provider read and stays a separately approved
  action; nothing here adds one.
* Claude records what it read from that job as a create-only
  ``CLAUDE_AUTO_PROVIDER_SETTLEMENT_OBSERVATION_V1`` record, bound to the
  command, the accepted Jules session, the status-request commit, the workflow
  run and the job.
* ``settlement_status`` turns the verified records of one command into
  ``SETTLED`` / ``RUNNING`` / ``UNKNOWN``.  Absence of a PR is never evidence.

State mapping is deliberately conservative: only ``COMPLETED`` and ``FAILED``
are settled; every state that can still progress (including awaiting/paused)
counts as ``RUNNING``; anything unrecognised is ``UNKNOWN``.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any, Callable, Iterable

from .claude_jules_dispatch import EVIDENCE_ROOT, sha256_of

SETTLEMENT_PROFILE = "CLAUDE_AUTO_PROVIDER_SETTLEMENT_OBSERVATION_V1"
READBACK_WORKFLOW = "jules-session-readback.yml"
STATUS_REQUEST_DIR = "automation/command_bus/jules_api_status_requests"
SETTLED_STATES = frozenset({"COMPLETED", "FAILED"})
UNSETTLED_STATES = frozenset({"QUEUED", "PLANNING", "AWAITING_PLAN_APPROVAL", "AWAITING_USER_FEEDBACK",
                              "IN_PROGRESS", "PAUSED", "RUNNING"})
_READBACK_LOG = re.compile(r"Jules session readback: name=sessions/([0-9]{1,32}) state=([A-Z_]{1,40}) pr_url=(\S+)")
_SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_DIGITS = re.compile(r"^[0-9]{1,32}$")
_KEYS = {"schema_version", "profile", "command_id", "session_id", "status_request_path", "status_request_commit",
         "workflow_run_id", "job_id", "log_line", "provider_state", "source", "observed_at", "observation_sha256"}


def classify_provider_state(raw: Any) -> str:
    if raw in SETTLED_STATES:
        return "SETTLED"
    if raw in UNSETTLED_STATES:
        return "RUNNING"
    return "UNKNOWN"


def settlement_path(command_id: str, workflow_run_id: str) -> str:
    if not _SAFE_ID.fullmatch(command_id or "") or not _DIGITS.fullmatch(str(workflow_run_id or "")):
        raise ValueError("unsafe settlement identity")
    return f"{EVIDENCE_ROOT}/claude-auto-settlement-observations/{command_id}/{workflow_run_id}.json"


def _time(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ValueError("timestamp required")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must carry a timezone")
    return parsed


def build_settlement_observation(*, command_id: str, status_request_path: str, status_request_commit: str,
                                 workflow_run_id: str, job_id: str, log_line: str, observed_at: str,
                                 source: str = "github-mcp get_job_logs") -> dict[str, Any]:
    matches = _READBACK_LOG.findall(log_line or "")
    if len(matches) != 1:
        raise ValueError("log line must contain exactly one Jules session readback")
    session_id, state, _pr = matches[0]
    record = {"schema_version": 1, "profile": SETTLEMENT_PROFILE, "command_id": command_id,
              "session_id": session_id, "status_request_path": status_request_path,
              "status_request_commit": status_request_commit, "workflow_run_id": str(workflow_run_id),
              "job_id": str(job_id), "log_line": log_line.strip(), "provider_state": state, "source": source,
              "observed_at": observed_at}
    record["observation_sha256"] = sha256_of(record)
    return validate_settlement_observation(record)


def validate_settlement_observation(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict) or set(record) != _KEYS:
        raise ValueError("settlement observation keys mismatch")
    if record["schema_version"] != 1 or record["profile"] != SETTLEMENT_PROFILE:
        raise ValueError("unsupported settlement observation")
    if record["observation_sha256"] != sha256_of({k: v for k, v in record.items() if k != "observation_sha256"}):
        raise ValueError("settlement observation digest mismatch")
    settlement_path(record["command_id"], record["workflow_run_id"])
    if not _DIGITS.fullmatch(str(record["job_id"])) or not _DIGITS.fullmatch(str(record["session_id"])):
        raise ValueError("settlement observation ids must be numeric")
    if not _SHA40.fullmatch(str(record["status_request_commit"])):
        raise ValueError("status request commit must be a full sha")
    path = str(record["status_request_path"])
    if not re.fullmatch(rf"{re.escape(STATUS_REQUEST_DIR)}/[a-z0-9][a-z0-9._-]{{0,63}}\.json", path):
        raise ValueError("status request path outside the readback route")
    matches = _READBACK_LOG.findall(record["log_line"])
    if len(matches) != 1 or matches[0][:2] != (record["session_id"], record["provider_state"]):
        raise ValueError("log line does not carry the recorded session/state")
    _time(record["observed_at"])
    return record


def settlement_status(records: Iterable[dict[str, Any]], *, command_id: str, accepted_session_id: str | None,
                      dispatched_at: str, run_verified: Callable[[dict[str, Any]], bool]) -> tuple[str, str]:
    """``(status, evidence_ref)`` for one command from its recorded readbacks.

    Every record must belong to the command and to the accepted session, be
    observed after the dispatch and point at a REST-verified readback run.
    Settled states never revert, so a later unsettled readback after a settled
    one is a contradiction and yields UNKNOWN instead of either answer.
    """
    if not isinstance(accepted_session_id, str) or not _DIGITS.fullmatch(accepted_session_id):
        return "UNKNOWN", "accepted Jules session unknown; settlement cannot be bound"
    start = _time(dispatched_at)
    usable: list[dict[str, Any]] = []
    for raw in records:
        try:
            record = validate_settlement_observation(raw)
        except (KeyError, TypeError, ValueError) as exc:
            return "UNKNOWN", f"settlement record invalid: {exc}"
        if record["command_id"] != command_id:
            continue
        if record["session_id"] != accepted_session_id:
            return "UNKNOWN", "settlement record names another Jules session"
        if _time(record["observed_at"]) < start:
            continue  # predates this dispatch: proves nothing about it
        try:
            verified = bool(run_verified(record))
        except Exception as exc:  # transport failure is never a settlement
            return "UNKNOWN", f"readback run verification failed: {exc}"
        if not verified:
            return "UNKNOWN", f"readback run {record['workflow_run_id']} not verified for this request"
        usable.append(record)
    if not usable:
        return "UNKNOWN", "no verified provider readback after the dispatch"
    usable.sort(key=lambda r: (_time(r["observed_at"]), int(r["workflow_run_id"])))
    states = [classify_provider_state(r["provider_state"]) for r in usable]
    latest = usable[-1]
    ref = f"{READBACK_WORKFLOW} run {latest['workflow_run_id']} job {latest['job_id']}: {latest['provider_state']}"
    if "SETTLED" in states and states[-1] != "SETTLED":
        return "UNKNOWN", "provider readbacks contradict (unsettled after settled)"
    return states[-1], ref


def verify_readback_run(record: dict[str, Any], *, git: Any, rest: Any, carrier_branch: str) -> bool:
    """REST/git proof that the record's run is the readback of exactly its status request."""
    path, commit = record["status_request_path"], record["status_request_commit"]
    if git.added_by(carrier_branch, path) != [commit]:
        return False
    content = git.show(commit, path)
    try:
        request = json.loads(content) if content is not None else None
    except json.JSONDecodeError:
        return False
    if not isinstance(request, dict) or str(request.get("session_id")) != record["session_id"]:
        return False
    runs = [r for r in rest.workflow_runs_for_commit(READBACK_WORKFLOW, commit) if r.get("event") == "push"]
    if len(runs) != 1 or str(runs[0].get("id")) != record["workflow_run_id"]:
        return False
    if runs[0].get("status") != "completed" or runs[0].get("conclusion") != "success":
        return False
    return record["job_id"] in {str(job.get("id")) for job in rest.run_jobs(runs[0]["id"])}
