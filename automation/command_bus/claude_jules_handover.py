"""SEMI_AUTO (ChatGPT) <-> AUTO (Claude) controller handover for one Jules stream.

One Jules development stream (a lane working on one target branch) has exactly
one controller at a time.  ChatGPT (SEMI_AUTO) is the normal controller;
Claude (AUTO) may take the same stream over when it has stalled, and hands it
back.  The authority record is the existing append-only ``loop_owner`` chain
(ACQUIRE / RENEW / HANDOFF / RELEASE / TERMINAL with generation fencing),
written through ``LoopOwnerGitHubBackend`` (create-only, read back).  The
Claude controller's existing fence then refuses to dispatch unless the latest
generation is a live AUTO lease held by Claude, so the two controllers can
never command the stream at the same time.

Takeover rule (time alone is never sufficient):
  * the latest owner is SEMI_AUTO (or no owner was ever recorded, which is how
    the current ChatGPT loop runs) and any SEMI_AUTO lease has expired;
  * the stream's last durable activity (claims, result PRs, owner events) is
    at least ``STALL`` old;
  * no Jules work is in flight: every stream command either has a result PR
    or is older than the result deadline, and no result PR changed within
    ``STALL``.
Handback rule: AUTO returns the stream to SEMI_AUTO only at a boundary (no
Claude dispatch outstanding), so ChatGPT resumes from settled records.  An
AUTO lease that expired without a handback may be reclaimed by SEMI_AUTO with
the same HANDOFF shape.

This module never dispatches Jules and never changes lanes, settings or
permissions; it only prepares and appends owner generations.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable

from .loop_owner import validate_owner_chain, validate_owner_event

STALL = timedelta(hours=2)
RESULT_DEADLINE = timedelta(hours=6)
SEMIAUTO_HOLDER = "chatgpt-semiauto-controller"


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include a timezone")
    return parsed


@dataclass(frozen=True)
class StreamActivity:
    last_activity_at: str | None
    in_flight: tuple[str, ...]
    commands: tuple[str, ...]


@dataclass(frozen=True)
class HandoverDecision:
    status: str  # ELIGIBLE / BLOCKED / UNKNOWN
    reason: str
    event: dict[str, Any] | None = None


def observe_stream(*, lane_id: str, target_branch: str, claims: Iterable[dict[str, Any]],
                   result_prs: dict[str, list[dict[str, Any]]], owner_chain: list[dict[str, Any]],
                   now: str) -> StreamActivity:
    """Derive stream activity from durable GitHub records only.

    ``claims`` are carrier Loop claims (schema v3); ``result_prs`` maps each
    command id to the PRs whose base is its ``jules-work/<command_id>`` branch
    (REST shape: state, merged_at, updated_at).
    """
    current = _time(now)
    times: list[datetime] = [_time(e["claimed_at"]) for e in owner_chain]
    commands, in_flight = [], []
    for claim in claims:
        if claim.get("lane_id") != lane_id or claim.get("target_branch") != target_branch:
            continue
        command_id = claim["command_id"]
        claimed = _time(claim["claimed_at"])
        commands.append(command_id)
        times.append(claimed)
        prs = result_prs.get(command_id, [])
        for pr in prs:
            times.append(_time(pr["updated_at"]))
            if pr.get("state") == "open" and current - _time(pr["updated_at"]) < STALL:
                in_flight.append(command_id)  # result still moving (Jules follow-ups / review)
        if not prs and current - claimed < RESULT_DEADLINE:
            in_flight.append(command_id)  # Jules may still be running
    if any(t > current for t in times):
        raise ValueError("stream record from the future")
    last = max(times).isoformat() if times else None
    return StreamActivity(last, tuple(sorted(set(in_flight))), tuple(commands))


def _base_event(*, loop_id: str, event_type: str, role: str, holder: str, generation: int, now: str,
                lease: timedelta, expected_repo: str, expected_pr: int, target_head: str,
                reason_tag: str) -> dict[str, Any]:
    claimed = _time(now)
    ident = f"{loop_id}-g{generation:06d}"
    return {
        "schema_version": 1, "event_id": f"owner-{ident}", "event_type": event_type, "loop_id": loop_id,
        "owner_role": role, "holder_id": holder, "generation": generation, "fencing_token": generation,
        "previous_generation": generation - 1 if generation > 1 else None,
        "claimed_at": claimed.isoformat(), "expires_at": (claimed + lease).isoformat(),
        "expected_repo": expected_repo, "expected_pr": expected_pr, "expected_target_head": target_head,
        "command_id": f"owner-{reason_tag}-{ident}", "correlation_id": f"handover-{ident}",
        "source_receipt_id": f"owner-receipt-{ident}",
        "source_receipt_ref": f"automation/command_bus/receipts/{loop_id}/owner-{generation:06d}.json",
        "evidence_refs": [f"automation/command_bus/evidence/{loop_id}/handover-{generation:06d}.json"],
    }


def decide_takeover(*, owner_chain: list[dict[str, Any]], activity: StreamActivity, auto_holder: str,
                    loop_id: str, expected_repo: str, expected_pr: int, target_head: str, now: str,
                    lease: timedelta = timedelta(hours=3)) -> HandoverDecision:
    """SEMI_AUTO -> AUTO.  Returns the exact owner event to append when ELIGIBLE."""
    current = _time(now)
    try:
        chain = validate_owner_chain(owner_chain) if owner_chain else []
    except ValueError as exc:
        return HandoverDecision("UNKNOWN", f"owner chain invalid: {exc}")
    if activity.in_flight:
        return HandoverDecision("BLOCKED", f"Jules work in flight on the stream: {', '.join(activity.in_flight)}")
    if activity.last_activity_at is None:
        return HandoverDecision("UNKNOWN", "no durable stream activity to prove a stall")
    idle = current - _time(activity.last_activity_at)
    if idle < STALL:
        return HandoverDecision("BLOCKED", f"stream active {idle} ago; takeover needs a {STALL} stall")
    if not chain:
        event = _base_event(loop_id=loop_id, event_type="ACQUIRE", role="AUTO", holder=auto_holder, generation=1,
                            now=now, lease=lease, expected_repo=expected_repo, expected_pr=expected_pr,
                            target_head=target_head, reason_tag="takeover")
        return HandoverDecision("ELIGIBLE", "no owner recorded and the stream is stalled with nothing in flight", event)
    latest = chain[-1]
    if latest["event_type"] in {"RELEASE", "TERMINAL"}:
        return HandoverDecision("BLOCKED", "owner chain is closed")
    if latest["owner_role"] == "AUTO":
        return HandoverDecision("BLOCKED", "stream is already owned by AUTO; never two AUTO controllers")
    if current < _time(latest["expires_at"]):
        return HandoverDecision("BLOCKED", "SEMI_AUTO lease is still valid; stall alone never takes ownership")
    if (latest["expected_repo"], latest["expected_pr"]) != (expected_repo, expected_pr):
        return HandoverDecision("BLOCKED", "owner chain is bound to another repository/PR")
    event = _base_event(loop_id=loop_id, event_type="HANDOFF", role="AUTO", holder=auto_holder,
                        generation=latest["generation"] + 1, now=now, lease=lease, expected_repo=expected_repo,
                        expected_pr=expected_pr, target_head=target_head, reason_tag="takeover")
    event["previous_owner_role"], event["previous_holder_id"] = latest["owner_role"], latest["holder_id"]
    validate_owner_chain([*chain, event])
    return HandoverDecision("ELIGIBLE", "SEMI_AUTO lease expired, stream stalled, nothing in flight", event)


def decide_handback(*, owner_chain: list[dict[str, Any]], auto_holder: str, outstanding_dispatches: int,
                    target_head: str, now: str, to_holder: str = SEMIAUTO_HOLDER,
                    lease: timedelta = timedelta(hours=12)) -> HandoverDecision:
    """AUTO -> SEMI_AUTO at a boundary, written by the AUTO holder."""
    try:
        chain = validate_owner_chain(owner_chain)
    except ValueError as exc:
        return HandoverDecision("UNKNOWN", f"owner chain invalid: {exc}")
    latest = chain[-1]
    if latest["event_type"] in {"RELEASE", "TERMINAL"} or latest["owner_role"] != "AUTO":
        return HandoverDecision("BLOCKED", "stream is not owned by AUTO")
    if latest["holder_id"] != auto_holder:
        return HandoverDecision("BLOCKED", "another AUTO holder owns the stream")
    if outstanding_dispatches:
        return HandoverDecision("BLOCKED", "a Claude dispatch is still outstanding; hand back at the next boundary")
    event = _base_event(loop_id=latest["loop_id"], event_type="HANDOFF", role="SEMI_AUTO", holder=to_holder,
                        generation=latest["generation"] + 1, now=now, lease=lease,
                        expected_repo=latest["expected_repo"], expected_pr=latest["expected_pr"],
                        target_head=target_head, reason_tag="handback")
    event["previous_owner_role"], event["previous_holder_id"] = "AUTO", auto_holder
    validate_owner_chain([*chain, event])
    return HandoverDecision("ELIGIBLE", "AUTO at a boundary hands the stream back to SEMI_AUTO", event)


def decide_reclaim(*, owner_chain: list[dict[str, Any]], semiauto_holder: str, target_head: str, now: str,
                   lease: timedelta = timedelta(hours=12)) -> HandoverDecision:
    """SEMI_AUTO takes back a stream whose AUTO lease expired without a handback."""
    try:
        chain = validate_owner_chain(owner_chain)
    except ValueError as exc:
        return HandoverDecision("UNKNOWN", f"owner chain invalid: {exc}")
    latest = chain[-1]
    if latest["event_type"] in {"RELEASE", "TERMINAL"} or latest["owner_role"] != "AUTO":
        return HandoverDecision("BLOCKED", "stream is not owned by AUTO")
    if _time(now) < _time(latest["expires_at"]):
        return HandoverDecision("BLOCKED", "AUTO lease is still valid; ask Claude to hand back")
    event = _base_event(loop_id=latest["loop_id"], event_type="HANDOFF", role="SEMI_AUTO", holder=semiauto_holder,
                        generation=latest["generation"] + 1, now=now, lease=lease,
                        expected_repo=latest["expected_repo"], expected_pr=latest["expected_pr"],
                        target_head=target_head, reason_tag="reclaim")
    event["previous_owner_role"], event["previous_holder_id"] = latest["owner_role"], latest["holder_id"]
    validate_owner_chain([*chain, event])
    return HandoverDecision("ELIGIBLE", "expired AUTO lease reclaimed by SEMI_AUTO", event)


def append_decision(backend: Any, decision: HandoverDecision) -> HandoverDecision:
    """Append an ELIGIBLE owner event create-only; a concurrent writer makes it BLOCKED."""
    if decision.status != "ELIGIBLE" or decision.event is None:
        return decision
    validate_owner_event(decision.event)
    written = backend.append(decision.event)
    if written.status == "ACCEPTED":
        return HandoverDecision("APPENDED", written.reason, written.record)
    return HandoverDecision("BLOCKED" if written.status == "BLOCKED" else "UNKNOWN", written.reason, written.record)
