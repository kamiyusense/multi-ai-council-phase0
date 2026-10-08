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
* A record is only a pointer.  Its digest proves the record was not altered
  after it was written, never that its content came from the provider.
  ``verify_readback`` therefore re-reads the job's own Actions log over REST,
  extracts the one genuine readback line independently and requires the record
  to match it.  Ordering uses the job's REST timestamps, never ``observed_at``.
* ``settlement_status`` turns the verified records of one command into
  ``SETTLED`` / ``RUNNING`` / ``UNKNOWN``.  Absence of a PR is never evidence.

HTTP cost: the workflow on main makes one session GET, plus one activities GET
unless the request sets ``"include_activities": false``.  ``prepare_status_request``
always sets it to false.  The workflow that actually runs is the one on the
carrier branch, and on 2026-10-07 that copy (blob 3672250) ignored the field and
always made both GETs.  A prepared request is therefore only one GET when
``jules_readback_workflow_probe`` reports ``ONE_GET_CONFIRMED`` for the carrier
workflow at send time; the request says so in ``requires_preflight``.

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
READBACK_PREFIX = "Jules session readback:"
# The workflow prints exactly one such line; the optional accepted_at_jst field
# was added later, so both shapes are accepted, but only as a whole line.
_READBACK_LOG = re.compile(r"Jules session readback: name=sessions/([0-9]{1,32}) state=([A-Z_]{1,40})"
                           r"(?: accepted_at_jst=\S+)? pr_url=(\S+)")
_LOG_TIMESTAMP = re.compile(r"^\ufeff?[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.]+Z ?")
MAX_STATUS_REQUESTS_PER_COMMAND = 3
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
    log_line = _LOG_TIMESTAMP.sub("", (log_line or "").strip(), count=1)
    match = _READBACK_LOG.fullmatch(log_line)
    if match is None:
        raise ValueError("log line must be exactly one Jules session readback line")
    session_id, state, _pr = match.groups()
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
    match = _READBACK_LOG.fullmatch(record["log_line"]) if isinstance(record["log_line"], str) else None
    if match is None or match.groups()[:2] != (record["session_id"], record["provider_state"]):
        raise ValueError("log line does not carry the recorded session/state")
    _time(record["observed_at"])
    return record


class ReadbackUnavailable(Exception):
    """A GitHub read needed to verify a readback failed; reading again later is safe."""


class ReadbackMismatch(Exception):
    """The record and GitHub disagree; never retried into a settlement."""


def readback_lines(log_text: str) -> list[str]:
    """Every genuine readback line of one job log, timestamps stripped.

    A line counts only when it *starts* with the readback prefix (the step's
    script echo starts with ``echo`` and the agent-message line with another
    prefix).  A prefixed line that is not the exact readback shape is not
    skipped: it makes the log unusable, because it may be an injected line.
    """
    found = []
    for raw in (log_text or "").splitlines():
        body = _LOG_TIMESTAMP.sub("", raw, count=1).rstrip("\r")
        if not body.startswith(READBACK_PREFIX):
            continue
        if _READBACK_LOG.fullmatch(body) is None:
            raise ReadbackMismatch("unrecognised readback line in the job log")
        found.append(body)
    return found


def settlement_status(records: Iterable[dict[str, Any]], *, command_id: str, accepted_session_id: str | None,
                      dispatched_at: str, verify: Callable[[dict[str, Any]], dict[str, Any]]) -> tuple[str, str]:
    """``(status, evidence_ref)`` for one command from its recorded readbacks.

    ``verify`` returns the GitHub-verified facts of one record (see
    ``verify_readback``) or raises.  Only those facts decide: the job log's own
    session/state and the job's REST start/completion times.  A readback whose
    job started before the dispatch proves nothing about it and is ignored.
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
            return "UNKNOWN", "settlement record names another Jules session; identity mismatch"
        try:
            facts = verify(record)
        except ReadbackUnavailable as exc:
            return "UNKNOWN", f"provider readback unavailable: {exc}"
        except ReadbackMismatch as exc:
            return "UNKNOWN", f"provider readback contradiction: {exc}"
        except Exception as exc:  # anything unexpected is never a settlement
            return "UNKNOWN", f"provider readback contradiction: verification raised {type(exc).__name__}"
        if facts.get("session_id") != accepted_session_id:
            return "UNKNOWN", "provider readback contradiction: job log names another session"
        if _time(facts["job_started_at"]) < start:
            continue  # this GET ran before the dispatch: proves nothing about it
        if _time(record["observed_at"]) < _time(facts["job_completed_at"]):
            return "UNKNOWN", "provider readback contradiction: record predates its own job"
        usable.append(facts)
    if not usable:
        return "UNKNOWN", "no verified provider readback after the dispatch"
    usable.sort(key=lambda f: (_time(f["job_completed_at"]), int(f["workflow_run_id"])))
    states = [classify_provider_state(f["provider_state"]) for f in usable]
    latest = usable[-1]
    ref = f"{READBACK_WORKFLOW} run {latest['workflow_run_id']} job {latest['job_id']}: {latest['provider_state']}"
    if "SETTLED" in states and states[-1] != "SETTLED":
        return "UNKNOWN", "provider readback contradiction: unsettled after settled"
    return states[-1], ref


def verify_readback(record: dict[str, Any], *, git: Any, rest: Any, carrier_branch: str) -> dict[str, Any]:
    """Independently re-derive what the record claims, from git, REST and the job's own log.

    Binds: request path added exactly once by the recorded commit, request
    content (session, and command when present), exactly one push run of the
    readback workflow for that commit (first attempt, completed, success), its
    single job (first attempt, success) and that job's log, which must hold
    exactly one genuine readback line equal to the recorded one.

    Raises ``ReadbackUnavailable`` when a read fails (bounded re-read is safe)
    and ``ReadbackMismatch`` for any disagreement.
    """
    path, commit = record["status_request_path"], record["status_request_commit"]
    try:
        added = git.added_by(carrier_branch, path)
        content = git.show(commit, path)
        runs = rest.workflow_runs_for_commit(READBACK_WORKFLOW, commit)
    except Exception as exc:
        raise ReadbackUnavailable(f"request/run read failed: {type(exc).__name__}") from exc
    if added != [commit]:
        raise ReadbackMismatch("status request is not added exactly once by the recorded commit")
    try:
        request = json.loads(content) if content is not None else None
    except json.JSONDecodeError:
        request = None
    if not isinstance(request, dict) or str(request.get("session_id")) != record["session_id"]:
        raise ReadbackMismatch("status request names another session")
    if "command_id" in request and request["command_id"] != record["command_id"]:
        raise ReadbackMismatch("status request belongs to another command")
    runs = [r for r in runs if r.get("event") == "push"]
    if len(runs) != 1 or str(runs[0].get("id")) != record["workflow_run_id"]:
        raise ReadbackMismatch("readback run is not the single push run of the request commit")
    run = runs[0]
    if run.get("head_sha") != commit or run.get("run_attempt") != 1:
        raise ReadbackMismatch("readback run is a re-run or for another commit")
    if run.get("status") != "completed" or run.get("conclusion") != "success":
        raise ReadbackMismatch("readback run did not complete successfully")
    try:
        jobs = rest.run_jobs(run["id"])
    except Exception as exc:
        raise ReadbackUnavailable(f"job list read failed: {type(exc).__name__}") from exc
    if len(jobs) != 1 or str(jobs[0].get("id")) != record["job_id"]:
        raise ReadbackMismatch("recorded job is not the single job of the readback run")
    job = jobs[0]
    if job.get("run_attempt") != 1 or job.get("conclusion") != "success" or job.get("status") != "completed":
        raise ReadbackMismatch("readback job is a re-run or did not succeed")
    try:
        started, completed = _time(job.get("started_at")), _time(job.get("completed_at"))
    except (TypeError, ValueError) as exc:
        raise ReadbackMismatch("readback job times are missing") from exc
    if completed < started:
        raise ReadbackMismatch("readback job times are inconsistent")
    try:
        log_text = rest.job_log(job["id"])
    except Exception as exc:
        raise ReadbackUnavailable(f"job log read failed: {type(exc).__name__}") from exc
    if not isinstance(log_text, str) or not log_text:
        raise ReadbackUnavailable("job log is empty or unreadable")
    lines = readback_lines(log_text)
    if len(lines) != 1:
        raise ReadbackMismatch(f"job log holds {len(lines)} readback lines, expected exactly one")
    session_id, state, _pr = _READBACK_LOG.fullmatch(lines[0]).groups()
    if session_id != record["session_id"]:
        raise ReadbackMismatch("job log names another session")
    if lines[0] != record["log_line"] or state != record["provider_state"]:
        raise ReadbackMismatch("recorded state differs from the job log")
    return {"session_id": session_id, "provider_state": state, "workflow_run_id": record["workflow_run_id"],
            "job_id": record["job_id"], "job_started_at": job["started_at"], "job_completed_at": job["completed_at"]}


def observation_from_readback_run(*, command_id: str, status_request_path: str, git: Any, rest: Any,
                                  carrier_branch: str, observed_at: str) -> dict[str, Any]:
    """Build a settlement record FROM GitHub (request commit, run, job, job log) and verify it before returning.

    Read-only: nothing is written and no provider is called.  The log line is
    extracted here, never supplied by the caller, so the record cannot carry a
    transcribed state.  Raises ``ReadbackUnavailable`` / ``ReadbackMismatch``.
    """
    try:
        commits = git.added_by(carrier_branch, status_request_path)
        runs = None
        if len(commits) == 1:
            runs = [r for r in rest.workflow_runs_for_commit(READBACK_WORKFLOW, commits[0]) if r.get("event") == "push"]
            jobs = rest.run_jobs(runs[0]["id"]) if len(runs) == 1 else []
    except Exception as exc:
        raise ReadbackUnavailable(f"request/run read failed: {type(exc).__name__}") from exc
    if len(commits) != 1:
        raise ReadbackMismatch("status request is not added exactly once")
    if runs is None or len(runs) != 1 or len(jobs) != 1:
        raise ReadbackMismatch("no single readback run/job for the request commit")
    try:
        log_text = rest.job_log(jobs[0]["id"])
    except Exception as exc:
        raise ReadbackUnavailable(f"job log read failed: {type(exc).__name__}") from exc
    lines = readback_lines(log_text or "")
    if len(lines) != 1:
        raise ReadbackMismatch(f"job log holds {len(lines)} readback lines, expected exactly one")
    record = build_settlement_observation(
        command_id=command_id, status_request_path=status_request_path, status_request_commit=commits[0],
        workflow_run_id=str(runs[0]["id"]), job_id=str(jobs[0]["id"]), log_line=lines[0], observed_at=observed_at,
        source="github-rest actions/jobs/logs (read-only, extracted by observation_from_readback_run)")
    verify_readback(record, git=git, rest=rest, carrier_branch=carrier_branch)
    return record


def status_request_path(name: str) -> str:
    if not _SAFE_ID.fullmatch(name or "") or len(name) > 59:
        raise ValueError("unsafe status request name")
    return f"{STATUS_REQUEST_DIR}/{name}.json"


def prepare_status_request(*, command_id: str, session_id: str, attempt: int, existing_paths: Iterable[str],
                           not_before: str, now: str) -> dict[str, Any]:
    """PREPARE-ONLY: the exact carrier file a settlement read would add.  Writes nothing.

    Adding the file triggers one provider GET, which is a separately approved
    LIVE action.  The request carries ``include_activities: false`` so one
    request is exactly one ``GET /v1alpha/sessions/<id>``, provided the carrier
    workflow passes the one-GET preflight (``requires_preflight``).  ``attempt`` is
    1-based and capped at ``MAX_STATUS_REQUESTS_PER_COMMAND``; the name is
    derived from (command, session, attempt) so re-preparing is idempotent and a
    second attempt can never reuse the first one's path.  ``not_before`` is the
    earliest time the attempt is useful (backoff); preparing earlier is refused.
    """
    if not _SAFE_ID.fullmatch(command_id or "") or not _DIGITS.fullmatch(str(session_id or "")):
        raise ValueError("unsafe status request identity")
    if type(attempt) is not int or not 1 <= attempt <= MAX_STATUS_REQUESTS_PER_COMMAND:
        raise ValueError(f"status request attempt must be 1..{MAX_STATUS_REQUESTS_PER_COMMAND}")
    if _time(now) < _time(not_before):
        raise ValueError("status request prepared before its backoff ended")
    digest = sha256_of({"command_id": command_id, "session_id": str(session_id)})[:16]
    path = status_request_path(f"settle-{digest}-a{attempt}")
    existing = set(existing_paths)
    if path in existing:
        raise ValueError("status request for this attempt already exists; read its run instead of resending")
    prior = {status_request_path(f"settle-{digest}-a{n}") for n in range(1, attempt)}
    if not prior <= existing:
        raise ValueError("earlier status request attempts are missing; attempts must be contiguous")
    body = {"session_id": str(session_id), "command_id": command_id, "include_activities": False,
            "purpose": f"settlement-readback-{command_id}-a{attempt}"[:120]}
    return {"path": path, "content": json.dumps(body, indent=2, sort_keys=True) + "\n", "provider_get_count": 1,
            "requires_preflight": "ONE_GET_CONFIRMED",
            "endpoint": f"GET https://jules.googleapis.com/v1alpha/sessions/{session_id}",
            "status": "PREPARED_NOT_AUTHORIZED"}
