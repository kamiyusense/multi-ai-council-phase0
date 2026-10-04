"""Prepare-only durable polling fallback for Blue Work result commands.

This module does not schedule Work, change task settings, post reviews/comments,
or execute target work. It only selects the oldest unprocessed durable Blue
Jules-result command review from complete GitHub readback.

The fallback exists for a deployment where event-triggered Work may fail to wake
for a bot-authored PR review. Review author identity is evidence only and is not
an authority gate here. Correctness remains bound to the durable command,
generation, target identity, and terminal receipt contract.

Historical BWJ transport proofs and ordinary Chat commands are deliberately out
of scope. In particular, consumed BWJ-4 proof commands must never be revived by
a later polling worker.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from .blue_work_reconcile_prepare import _body, _command, _positive, _records, _time
from .cloud_work_lanes import lane_identity


@dataclass(frozen=True)
class PollSelection:
    status: str
    reason: str
    review_id: int | None = None
    command_id: str | None = None
    submitted_at: str | None = None
    author_login: str | None = None
    author_type: str | None = None
    pending_count: int = 0
    execution_mode: str = "PREPARE_ONLY"
    retry: int = 0
    fallback: str = "disabled"


def select_pending_blue_review(
    *,
    reviews: Any,
    comments: Any,
    records_complete: Any,
    active_generation: Any,
    fixed_generation: Any,
    lane: str = "blue",
) -> PollSelection:
    """Select at most one durable pending Jules-result command for polling.

    Selection is deterministic: oldest submitted review, then lowest review id.
    The caller must still run the existing worker/target/expiry/replay gates
    before any action. A stale worker silently NO_OPs before parsing commands.

    Only the reserved blue-jules-result-pr<PR>-<HEAD> command class is
    eligible. Historical BWJ proof IDs and ordinary Chat commands are ignored,
    so a polling fallback cannot retroactively process consumed proof history.

    Review author identity is returned only for evidence/diagnostics and never
    decides eligibility.
    """
    try:
        if lane != "blue":
            return PollSelection("NO_OP", "Blue-only polling fallback")
        if type(active_generation) is not int or active_generation <= 0:
            raise ValueError("active generation missing")
        if type(fixed_generation) is not int or fixed_generation <= 0:
            raise ValueError("fixed generation missing")
        if fixed_generation != active_generation:
            return PollSelection("NO_OP", "stale worker generation")
        if records_complete is not True or not isinstance(reviews, list) or not isinstance(comments, list):
            raise ValueError("complete durable records required")

        # Validate the durable receipt set first. This preserves the existing
        # terminal/duplicate/malformed fail-closed behavior.
        _, terminal_ids = _records(reviews, comments, True, lane=lane)
        prefix = lane_identity(lane)["command_prefix"]
        eligible_identity_prefix = f"{lane}-jules-result-"

        seen: set[str] = set()
        pending: list[tuple[datetime, int, dict[str, Any], dict[str, Any]]] = []
        for row in reviews:
            if not isinstance(row, dict):
                raise ValueError("malformed review")
            command = _body(row.get("body"), prefix)
            if command is None:
                continue
            command_id = command.get("command_id") if isinstance(command, dict) else None
            if not isinstance(command_id, str) or not command_id:
                raise ValueError("Blue command identity missing")
            if not command_id.startswith(eligible_identity_prefix):
                # Includes consumed blue-bwj4-* transport proofs and ordinary
                # blue-chat-* commands. They are outside the poller authority.
                continue
            if row.get("state") != "COMMENTED" or not _positive(row.get("id")):
                raise ValueError("Blue result command is not a submitted COMMENT review")
            submitted = _time(row.get("submitted_at"))
            _command(command, lane)
            if command_id in seen:
                raise ValueError("duplicate Blue result command identity")
            seen.add(command_id)
            if command_id in terminal_ids:
                continue
            pending.append((submitted, row["id"], command, row))

        if not pending:
            return PollSelection("NO_OP", "no unprocessed durable Blue Jules-result command")

        pending.sort(key=lambda item: (item[0], item[1]))
        _, review_id, command, row = pending[0]
        user = row.get("user") if isinstance(row.get("user"), dict) else {}
        login = user.get("login") if isinstance(user.get("login"), str) else None
        actor_type = user.get("type") if isinstance(user.get("type"), str) else None
        return PollSelection(
            "SELECTED",
            "oldest unprocessed durable Blue Jules-result command selected; downstream gates still required",
            review_id=review_id,
            command_id=command["command_id"],
            submitted_at=row["submitted_at"],
            author_login=login,
            author_type=actor_type,
            pending_count=len(pending),
        )
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError):
        return PollSelection(
            "UNKNOWN",
            "durable Blue result-command records missing/malformed/conflicting; no action",
        )
