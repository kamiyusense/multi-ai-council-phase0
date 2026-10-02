"""Verification of already-recorded LIVE evidence (pure; no network, no writes).

Recorded evidence is "what was observed at that time". It is never "now":
- Owner authority: a completed workflow run is immutable, so a sanitized run
  readback bound by digest can feed the existing OIDC-bound authority path.
- Provider state: a past IN_PROGRESS observation can never satisfy the
  production authenticator, which needs a fresh session read and a durable
  owner context. assess_recorded_provider_evidence() verifies the lineage and
  then lists, computed from the evidence itself, why live authentication is
  BLOCKED. It never returns a passing live status.
"""
from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Any

_DIGEST = re.compile(r"^[0-9a-f]{64}$")
_ACTIVE = frozenset({"QUEUED", "PLANNING", "IN_PROGRESS", "RUNNING"})
# Fields a durable provider source needs from the owner event at observation time.
_DURABLE_OWNER_FIELDS = ("owner_generation", "fencing_token", "source_receipt_ref", "evidence_ref")
_SANITIZED_SOURCE_FIELDS = ("provider_source", "starting_branch", "update_time")


def payload_digest(document: dict[str, Any], digest_key: str) -> str:
    body = {k: v for k, v in document.items() if k != digest_key}
    canonical = json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def digest_ok(document: Any, digest_key: str) -> bool:
    if not isinstance(document, dict):
        return False
    claimed = document.get(digest_key)
    return isinstance(claimed, str) and bool(_DIGEST.fullmatch(claimed)) and claimed == payload_digest(document, digest_key)


def has_reusable_workflow_call(workflow_text: str) -> bool:
    """True when any job calls a reusable workflow (a job-level `uses:` key)."""
    return any(re.match(r"^ {4}uses:\s*\S", line) for line in workflow_text.splitlines())


class RecordedRunReader:
    """RunReader backed by a digest-bound sanitized run readback of a finished run.

    A finished workflow_dispatch run in the same repository cannot change, and its
    head repository is necessarily the repository itself. referenced_workflows is
    derived from the exact workflow file text of the run's commit.
    """

    def __init__(self, readback: dict[str, Any], workflow_text: str):
        self.readback = copy.deepcopy(readback)
        self.workflow_text = workflow_text
        self.calls: list[str] = []

    def read_run(self, run_id: str) -> dict[str, Any] | None:
        self.calls.append(run_id)
        rb = self.readback
        try:
            if not digest_ok(rb, "readback_payload_sha256"):
                return None
            if rb["proof_kind"] != "GITHUB_WORKFLOW_DISPATCH_AUTHORITY_RUN_READBACK" or rb["status"] != "PASS":
                return None
            if str(rb["run_id"]) != str(run_id) or rb["actor_matches_triggering_actor"] is not True:
                return None
            if rb["event"] != "workflow_dispatch" or rb["job_conclusion"] != "success":
                return None
            referenced = [{"path": "reusable-workflow-call"}] if has_reusable_workflow_call(self.workflow_text) else []
            return {
                "id": int(rb["run_id"]), "path": rb["workflow_path"], "head_sha": rb["head_sha"],
                "head_branch": rb["head_branch"], "event": rb["event"], "run_attempt": rb["run_attempt"],
                "status": "completed", "conclusion": rb["conclusion"],
                "repository": {"full_name": rb["repository"]},
                "head_repository": {"full_name": rb["repository"]},
                "actor": {"id": int(rb["actor_id"])}, "triggering_actor": {"id": int(rb["triggering_actor_id"])},
                "created_at": rb["created_at"], "referenced_workflows": referenced,
            }
        except (KeyError, TypeError, ValueError):
            return None


@dataclass(frozen=True)
class RecordedProviderAssessment:
    recorded_lineage: str  # VERIFIED | INVALID
    live_authentication: str  # BLOCKED only; a recorded observation is never "now"
    lineage_failures: tuple[str, ...]
    blockers: tuple[str, ...]


def _time(value: Any) -> datetime:
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))


def assess_recorded_provider_evidence(
    *, evidence: dict[str, Any], output_readback: dict[str, Any], terminal_receipt: dict[str, Any],
    now: str, max_age_seconds: int, allowed_path: str, allowed_content: str,
) -> RecordedProviderAssessment:
    bad: list[str] = []
    try:
        for name, doc, key in (
            ("provider evidence", evidence, "evidence_payload_sha256"),
            ("output readback", output_readback, "readback_payload_sha256"),
            ("terminal receipt", terminal_receipt, "receipt_payload_sha256"),
        ):
            if not digest_ok(doc, key):
                bad.append(f"{name}: digest mismatch")
        sid = evidence.get("session_id")
        if not (sid and sid == output_readback.get("session_id") == terminal_receipt.get("session_id")):
            bad.append("session id differs across evidence documents")
        if evidence.get("status") != "PASS" or evidence.get("scope") != "LIVE":
            bad.append("provider evidence is not a LIVE PASS")
        if evidence.get("session_state") not in _ACTIVE:
            bad.append("recorded state is not an active state")
        if evidence.get("session_create_post_count") != 1:
            bad.append("session was not created exactly once")
        breakdown = evidence.get("jules_get_breakdown")
        if not isinstance(breakdown, dict) or sum(breakdown.values()) != evidence.get("jules_get_count_total"):
            bad.append("GET breakdown does not add up to the total")
        if evidence.get("retry") != 0 or evidence.get("fallback") != "disabled":
            bad.append("retry/fallback not 0/disabled")
        if not _time(evidence["session_create_time"]) <= _time(evidence["observed_at"]):
            bad.append("observed before created")
        head = evidence.get("expected_target_head")
        if not (head and head == evidence.get("target_head_after_readback") == evidence.get("work_head_after_readback")):
            bad.append("target/work head changed during the observation")
        if terminal_receipt.get("additional_jules_get_allowed") is not False:
            bad.append("terminal receipt allows more GETs")
        if output_readback.get("changed_files") != [allowed_path]:
            bad.append("output changed unexpected paths")
        if output_readback.get("changed_file_content") != allowed_content:
            bad.append("output content is not the exact allowed content")
        if output_readback.get("merged") is not False:
            bad.append("output PR was merged")
        if output_readback.get("base_branch") != evidence.get("work_branch"):
            bad.append("output PR base is not the isolated work branch")
        if output_readback.get("base_sha") != head:
            bad.append("output PR base is not the expected target head")
        if output_readback.get("head_branch") != f"{evidence.get('work_branch')}-{sid}":
            bad.append("output PR branch is not the Jules branch of this session")
        if output_readback.get("head_sha") == head:
            bad.append("output PR head equals base")
    except (KeyError, TypeError, ValueError, AttributeError):
        bad.append("evidence documents are malformed")
        return RecordedProviderAssessment("INVALID", "BLOCKED", tuple(bad), ())

    blockers: list[str] = []
    if evidence.get("pull_request_at_active_readback") in (None, "NONE"):
        blockers.append("NO_TARGET_PR_AT_OBSERVATION")
    if any(f not in evidence for f in _DURABLE_OWNER_FIELDS):
        blockers.append("NO_DURABLE_OWNER_EVENT_AT_OBSERVATION")
    if any(f not in evidence for f in _SANITIZED_SOURCE_FIELDS):
        blockers.append("NO_SANITIZED_PROVIDER_SOURCE_CONTEXT")
    blockers.append("FRESH_SESSION_READ_REQUIRED_BY_AUTHENTICATOR")
    try:
        if (_time(now) - _time(evidence["observed_at"])).total_seconds() > max_age_seconds:
            blockers.append("OBSERVATION_STALE")
    except (KeyError, ValueError):
        blockers.append("OBSERVATION_AGE_UNKNOWN")
    return RecordedProviderAssessment("INVALID" if bad else "VERIFIED", "BLOCKED", tuple(bad), tuple(blockers))


def authority_run_is_fresh(created_at: str, *, now: str, max_age_seconds: int) -> bool:
    """Stale-age rule for reusing a recorded authority run as a grant root."""
    try:
        age = (_time(now) - _time(created_at)).total_seconds()
    except (ValueError, TypeError):
        return False
    return 0 <= age <= max_age_seconds


def output_matches_recorded(recorded: dict[str, Any], live: dict[str, Any]) -> bool:
    """A later GitHub readback of the Jules output PR must equal the recorded one."""
    keys = ("pull_request", "base_sha", "head_branch", "head_sha", "changed_files", "changed_file_blob_sha", "merged")
    try:
        return all(recorded[k] == live[k] for k in keys)
    except (KeyError, TypeError):
        return False
