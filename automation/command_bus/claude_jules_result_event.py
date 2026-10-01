"""Jules result -> GitHub event -> durable event record -> Claude controller.

This is the event *ingress* only.  It never inspects semantics, adopts code or
dispatches the next Jules task.  It borrows three small, well-known pieces:

* GitHub webhook HMAC-SHA256 ``X-Hub-Signature-256`` validation (GitHub docs,
  "Validating webhook deliveries"), compared in constant time;
* CloudEvents-style ``source`` + ``id`` identity, where the logical id is the
  deterministic Jules result identity ``jules-result-pr<PR>-<HEAD>`` already
  used by the Blue Work webhook roadmap, and ``X-GitHub-Delivery`` is kept only
  as transport metadata (a redelivery maps to the same logical event);
* Trigger.dev / Standard Webhooks style idempotency: the first create-only
  durable record wins, every later delivery of the same result is a NO-OP.

Any existing ingress may feed ``normalize_pull_request_event``: a GitHub
Actions ``pull_request`` trigger, a webhook receiver, or a Claude Code session
PR-activity wake that re-reads the PR.  No new webhook server is introduced.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from typing import Any

from .claude_jules_dispatch import EVIDENCE_ROOT, canonical_json, sha256_of
from .github_backend import GitHubContentsClient
from .jules_carrier_current import jules_api_request as carrier_request_validator

EVENT_PROFILE = "CLAUDE_AUTO_JULES_RESULT_EVENT_V1"
ACCEPTED_ACTIONS = {"opened", "synchronize", "reopened"}
_WORK_PREFIX = "jules-work/"
_SHA40 = re.compile(r"^[0-9a-f]{40}$")
_DELIVERY = re.compile(r"^[A-Za-z0-9-]{1,64}$")
_BODY_SESSION = re.compile(r"https://jules\.google\.com/task/([0-9]{1,32})\)")


@dataclass(frozen=True)
class EventResult:
    status: str
    reason: str
    record: dict[str, Any] | None = None


def verify_github_signature(secret: bytes, body: bytes, signature_header: str | None) -> bool:
    """Validate ``X-Hub-Signature-256`` exactly as GitHub documents it."""
    if not isinstance(secret, bytes) or not secret or not isinstance(body, bytes):
        return False
    if not isinstance(signature_header, str) or not signature_header.startswith("sha256="):
        return False
    expected = "sha256=" + hmac.new(secret, body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature_header)


def result_id(pr_number: int, head_sha: str) -> str:
    if isinstance(pr_number, bool) or not isinstance(pr_number, int) or pr_number < 1:
        raise ValueError("invalid PR number")
    if not isinstance(head_sha, str) or not _SHA40.fullmatch(head_sha):
        raise ValueError("invalid head sha")
    return f"jules-result-pr{pr_number}-{head_sha}"


def event_path(identifier: str) -> str:
    if not isinstance(identifier, str) or not re.fullmatch(r"jules-result-pr[0-9]+-[0-9a-f]{40}", identifier):
        raise ValueError("unsafe result event id")
    return f"{EVIDENCE_ROOT}/claude-auto-result-events/{identifier}.json"


def normalize_pull_request_event(
    *, event_name: str, delivery_id: str, payload: dict[str, Any], expected_repo: str,
) -> EventResult:
    """Classify one GitHub delivery; only Jules result PR heads are accepted."""
    try:
        if event_name != "pull_request":
            return EventResult("IGNORED", "not a pull_request event")
        if not isinstance(delivery_id, str) or not _DELIVERY.fullmatch(delivery_id):
            return EventResult("REJECTED", "missing or malformed delivery id")
        if not isinstance(payload, dict):
            return EventResult("REJECTED", "payload is not an object")
        action = payload.get("action")
        if action not in ACCEPTED_ACTIONS:
            return EventResult("IGNORED", f"pull_request action {action!r} carries no new result head")
        repo = (payload.get("repository") or {}).get("full_name")
        if repo != expected_repo:
            return EventResult("REJECTED", "repository mismatch")
        pr = payload.get("pull_request") or {}
        number = pr.get("number")
        base, head = pr.get("base") or {}, pr.get("head") or {}
        base_ref, head_ref, head_sha = base.get("ref"), head.get("ref"), head.get("sha")
        if (base.get("repo") or {}).get("full_name") != expected_repo or (head.get("repo") or {}).get("full_name") != expected_repo:
            return EventResult("REJECTED", "fork or cross-repository result")
        if not isinstance(base_ref, str) or not base_ref.startswith(_WORK_PREFIX):
            return EventResult("IGNORED", "PR base is not an isolated Jules work branch")
        command_id = base_ref[len(_WORK_PREFIX):]
        if not carrier_request_validator.COMMAND_ID_RE.fullmatch(command_id):
            return EventResult("REJECTED", "work branch does not carry a valid command id")
        match = re.fullmatch(re.escape(base_ref) + r"-([0-9]{1,32})", head_ref or "")
        if match is None:
            return EventResult("REJECTED", "head ref is not a Jules session branch of the work branch")
        if pr.get("state") != "open" or pr.get("merged") is True:
            return EventResult("IGNORED", "PR is not an open unmerged result")
        body_match = _BODY_SESSION.findall(pr.get("body") or "")
        record = {
            "schema_version": 1,
            "profile": EVENT_PROFILE,
            "source": f"github.com/{expected_repo}",
            "id": result_id(number, head_sha),
            "first_delivery_id": delivery_id,
            "event": f"pull_request.{action}",
            "repository": expected_repo,
            "pr_number": number,
            "base_ref": base_ref,
            "head_ref": head_ref,
            "head_sha": head_sha,
            "command_id": command_id,
            "head_ref_session_id": match.group(1),
            "body_session_ids": sorted(set(body_match)),
        }
        record["event_sha256"] = sha256_of(record)
        return EventResult("ACCEPTED", "Jules result head event normalized", record)
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        return EventResult("REJECTED", f"malformed event: {exc}")


_EVENT_KEYS = {
    "schema_version", "profile", "source", "id", "first_delivery_id", "event", "repository",
    "pr_number", "base_ref", "head_ref", "head_sha", "command_id", "head_ref_session_id",
    "body_session_ids", "event_sha256",
}


def validate_event_record(record: Any) -> dict[str, Any]:
    """Re-validate a stored event: schema, digest and every derived identity."""
    if not isinstance(record, dict) or set(record) != _EVENT_KEYS:
        raise ValueError("event record keys mismatch")
    if record["schema_version"] != 1 or record["profile"] != EVENT_PROFILE:
        raise ValueError("unsupported event record")
    if record["event_sha256"] != sha256_of({k: v for k, v in record.items() if k != "event_sha256"}):
        raise ValueError("event record digest mismatch")
    if record["id"] != result_id(record["pr_number"], record["head_sha"]):
        raise ValueError("event id does not match PR/head")
    if record["source"] != f"github.com/{record['repository']}":
        raise ValueError("event source mismatch")
    if not carrier_request_validator.COMMAND_ID_RE.fullmatch(record["command_id"] or ""):
        raise ValueError("event command id invalid")
    if record["base_ref"] != _WORK_PREFIX + record["command_id"]:
        raise ValueError("event base ref does not bind the command")
    session = record["head_ref_session_id"]
    if not isinstance(session, str) or not session.isdigit() or record["head_ref"] != f"{record['base_ref']}-{session}":
        raise ValueError("event head ref does not bind the session")
    if record["event"] not in {f"pull_request.{a}" for a in ACCEPTED_ACTIONS}:
        raise ValueError("event kind invalid")
    ids = record["body_session_ids"]
    if not isinstance(ids, list) or ids != sorted(set(ids)) or any(not isinstance(i, str) or not i.isdigit() for i in ids):
        raise ValueError("event body session ids invalid")
    return record


def _identity(record: dict[str, Any]) -> dict[str, Any]:
    ignored = {"first_delivery_id", "event", "event_sha256"}
    return {k: v for k, v in record.items() if k not in ignored}


class ResultEventInbox:
    """Create-only durable inbox keyed by logical result identity."""

    def __init__(self, client: GitHubContentsClient, *, data_branch: str):
        self.client, self.branch = client, data_branch

    def record(self, event: dict[str, Any]) -> EventResult:
        try:
            path = event_path(event["id"])
            existing = self.client.get(path, self.branch)
            if existing is not None:
                stored = validate_event_record(json.loads(existing.text))
                if _identity(stored) == _identity(event):
                    return EventResult("DUPLICATE", "result already recorded; NO-OP", stored)
                return EventResult("BLOCKED", "conflicting record for the same result id", stored)
            try:
                self.client.create(path, canonical_json(event), f"record Jules result event {event['id']}", self.branch)
            except Exception:
                pass  # ambiguous create resolved by readback; a concurrent winner is also fine
            readback = self.client.get(path, self.branch)
            if readback is None:
                return EventResult("UNKNOWN", "event write not proven by readback; do not resend")
            stored = json.loads(readback.text)
            if stored == event:
                return EventResult("RECORDED", "durable result event recorded", stored)
            if _identity(stored) == _identity(event):
                return EventResult("DUPLICATE", "concurrent delivery recorded the same result first", stored)
            return EventResult("UNKNOWN", "event readback differs")
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            return EventResult("UNKNOWN", f"event inbox failure: {exc}")

    def list_events(self) -> list[dict[str, Any]]:
        prefix = f"{EVIDENCE_ROOT}/claude-auto-result-events/"
        events = []
        for content in self.client.list(prefix, self.branch):
            record = validate_event_record(json.loads(content.text))
            if content.path != event_path(record.get("id")):
                raise ValueError("event record path mismatch")
            events.append(record)
        return sorted(events, key=lambda item: (item["command_id"], item["pr_number"], item["id"]))


def verify_result_lineage(
    event: dict[str, Any], *, intent: dict[str, Any], dispatch_receipt: dict[str, Any] | None,
    dispatch_observation: dict[str, Any] | None, fresh_pr: dict[str, Any] | None,
) -> EventResult:
    """Bind a recorded result event to exactly one Claude-origin dispatch.

    ``dispatch_observation`` is the independently read workflow evidence for
    the command commit (run id, conclusion, accepted Jules session id).
    ``fresh_pr`` is a fresh readback of the result PR.  Branch names alone are
    never enough: the session id must agree across head ref, PR body footer
    and the workflow's accepted session.
    """
    request = intent["carrier_request"]
    try:
        validate_event_record(event)
    except (KeyError, TypeError, ValueError) as exc:
        return EventResult("BLOCKED", f"stored event record invalid: {exc}")
    if event.get("repository") != request["target_repo"]:
        return EventResult("BLOCKED", "result repository mismatch")
    if event.get("command_id") != request["command_id"] or event.get("base_ref") != request["work_branch"]:
        return EventResult("BLOCKED", "result does not belong to this command/work branch")
    if not isinstance(dispatch_receipt, dict) or dispatch_receipt.get("state") != "DISPATCHED":
        return EventResult("UNKNOWN", "no DISPATCHED receipt for this command")
    if dispatch_receipt.get("intent_sha256") != intent["intent_sha256"] or dispatch_receipt.get("command_id") != request["command_id"]:
        return EventResult("BLOCKED", "dispatch receipt does not bind this intent")
    if not isinstance(dispatch_observation, dict):
        return EventResult("UNKNOWN", "workflow/session observation unavailable")
    if dispatch_observation.get("command_id") != request["command_id"]:
        return EventResult("BLOCKED", "workflow observation belongs to another command")
    if dispatch_observation.get("conclusion") != "success" or not dispatch_observation.get("workflow_run_id"):
        return EventResult("UNKNOWN", "dispatch workflow success not proven")
    session = dispatch_observation.get("session_id")
    if not isinstance(session, str) or not session.isdigit():
        return EventResult("UNKNOWN", "accepted Jules session id unavailable")
    if event.get("head_ref_session_id") != session:
        return EventResult("BLOCKED", "result session differs from the accepted session")
    if event.get("body_session_ids") not in ([session], []):
        return EventResult("BLOCKED", "PR body names another Jules session")
    if not event.get("body_session_ids"):
        return EventResult("UNKNOWN", "PR body session footer missing")
    if not isinstance(fresh_pr, dict) or fresh_pr.get("number") != event.get("pr_number"):
        return EventResult("UNKNOWN", "fresh PR readback unavailable")
    if fresh_pr.get("merged") is True:
        return EventResult("BLOCKED", "result PR was merged outside the Claude adoption route")
    if fresh_pr.get("state") != "open":
        return EventResult("STALE", "result PR closed; it is no longer a candidate")
    if fresh_pr.get("base_ref") != request["work_branch"]:
        return EventResult("BLOCKED", "result PR base changed")
    if fresh_pr.get("head_sha") != event.get("head_sha"):
        return EventResult("STALE", "a newer result head exists; process the newer event instead")
    if fresh_pr.get("head_ref") != event.get("head_ref"):
        return EventResult("BLOCKED", "fresh PR head ref differs from the recorded session branch")
    if sorted(set(_BODY_SESSION.findall(fresh_pr.get("body") or ""))) != [session]:
        return EventResult("BLOCKED", "fresh PR body footer does not name exactly the accepted session")
    return EventResult("PASS", "result lineage verified", {
        "command_id": request["command_id"], "session_id": session,
        "workflow_run_id": dispatch_observation["workflow_run_id"],
        "pr_number": event["pr_number"], "candidate_head": event["head_sha"],
    })
