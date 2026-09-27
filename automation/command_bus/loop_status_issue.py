"""Project durable command-bus state onto the human-facing Loop Status Issue.

The GitHub Issue is a display/notification surface only. Correctness remains in
command-bus state/receipts. This module performs no network calls and never
starts a provider or model.
"""

from __future__ import annotations

import argparse
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .validator import validate_state

DISPLAY_STATES = {"SEMI_AUTO", "AUTO", "IDLE", "BLOCKED", "STOPPED"}
OWNERS = {"SEMI_AUTO", "AUTO", "NONE"}

_ACTIVE_SOURCE_STATES = {"RUNNING", "WAITING_FOR_EVIDENCE", "VERIFYING_POST_AUTH"}
_IDLE_SOURCE_STATES = {"PREPARED", "COMPLETE", "RECONCILED_LATE_RESULT"}
_BLOCKED_SOURCE_STATES = {
    "BLOCKED",
    "FAILED",
    "UNKNOWN",
    "WAITING_FOR_HUMAN_AUTH",
    "HUMAN_COMPLETED_UNVERIFIED",
}
_STOPPED_SOURCE_STATES = {"HALTED", "EXPIRED"}

_LOOP_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_MENTION = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$")

RUNTIME_START = "<!-- phase0-loop-runtime:start -->"
RUNTIME_END = "<!-- phase0-loop-runtime:end -->"
DEVELOPMENT_START = "<!-- phase0-development:start -->"
DEVELOPMENT_END = "<!-- phase0-development:end -->"


def managed_block(start: str, end: str, content: str) -> str:
    return f"{start}\n{content.rstrip()}\n{end}"


def extract_managed_block(body: str, start: str, end: str) -> str | None:
    start_count = body.count(start)
    end_count = body.count(end)
    if start_count == 0 and end_count == 0:
        return None
    if start_count != 1 or end_count != 1:
        raise ValueError("managed status markers are missing or duplicated")
    begin = body.index(start)
    finish = body.index(end, begin) + len(end)
    return body[begin:finish]


def replace_managed_block(body: str, start: str, end: str, content: str) -> str:
    block = managed_block(start, end, content)
    existing = extract_managed_block(body, start, end)
    if existing is None:
        if not body.strip():
            return block + "\n"
        return body.rstrip() + "\n\n" + block + "\n"
    return body.replace(existing, block, 1).rstrip() + "\n"


@dataclass(frozen=True)
class StatusProjection:
    display_state: str
    source_state: str
    owner: str
    loop_id: str
    round: int
    max_rounds: int
    provider_state: str
    last_durable_progress: str
    expires_at: str
    human_action: str
    reason: str


@dataclass(frozen=True)
class Notification:
    kind: str
    event_id: str
    marker: str
    body: str


def _single_line(value: Any, *, fallback: str = "UNKNOWN", max_len: int = 200) -> str:
    if value is None:
        return fallback
    text = " ".join(str(value).split()).replace(chr(96), "'")
    if not text:
        return fallback
    return text[:max_len]


def project_state(
    state: dict[str, Any],
    *,
    owner: str,
    provider_state: str = "UNKNOWN",
    last_durable_progress: str = "UNKNOWN",
    expected_loop_id: str | None = None,
) -> StatusProjection:
    validate_state(state)
    loop_id = state.get("loop_id")
    if not isinstance(loop_id, str) or not _LOOP_ID.fullmatch(loop_id):
        raise ValueError("invalid durable loop_id")
    if expected_loop_id is not None and loop_id != expected_loop_id:
        raise ValueError("durable loop_id does not match requested loop_id")
    if owner not in OWNERS:
        raise ValueError("owner must be SEMI_AUTO, AUTO, or NONE")

    source = state["state"]
    reason = ""

    if state["stop_requested"] or source in _STOPPED_SOURCE_STATES:
        display = "STOPPED"
        reason = "loop is stopped, halted, or expired"
    elif source in _BLOCKED_SOURCE_STATES:
        display = "BLOCKED"
        reason = f"command-bus source state is {source}"
    elif source in _IDLE_SOURCE_STATES:
        display = "IDLE"
        reason = f"command-bus source state is {source}"
    elif source in _ACTIVE_SOURCE_STATES:
        if owner == "SEMI_AUTO":
            display = "SEMI_AUTO"
            reason = "active durable state owned by SEMI_AUTO"
        elif owner == "AUTO":
            display = "AUTO"
            reason = "active durable state owned by AUTO"
        else:
            display = "BLOCKED"
            reason = "active durable state has no declared owner"
    else:
        raise ValueError(f"unmapped command-bus state: {source}")

    return StatusProjection(
        display_state=display,
        source_state=source,
        owner=owner,
        loop_id=loop_id,
        round=state["round"],
        max_rounds=state["max_rounds"],
        provider_state=_single_line(provider_state),
        last_durable_progress=_single_line(last_durable_progress),
        expires_at=_single_line(state["expires_at"]),
        human_action="REVIEW REQUIRED" if display == "BLOCKED" else "NONE",
        reason=reason,
    )


def _render_runtime_content(projection: StatusProjection) -> str:
    icon = {
        "SEMI_AUTO": "🟢",
        "AUTO": "🟣",
        "IDLE": "🟡",
        "BLOCKED": "🔴",
        "STOPPED": "⚫",
    }[projection.display_state]
    return (
        f"# {icon} Runtime: {projection.display_state}\n\n"
        "この色は **Runtime Loop の状態**です。下の開発進捗とは別です。\n"
        "This Issue is a **display surface only**. The durable command-bus "
        "state/receipts remain the source of truth.\n\n"
        f"- Loop: `{projection.loop_id}`\n"
        f"- Round: `{projection.round}/{projection.max_rounds}`\n"
        f"- Owner: `{projection.owner}`\n"
        f"- Command-bus state: `{projection.source_state}`\n"
        f"- Provider: `{projection.provider_state}`\n"
        f"- Last durable progress: `{projection.last_durable_progress}`\n"
        f"- Expires: `{projection.expires_at}`\n"
        f"- Human action: **{projection.human_action}**\n"
        f"- Projection reason: {projection.reason}\n\n"
        "## Notification policy\n\n"
        "- RUNNING/heartbeat/status refreshes update this body only.\n"
        "- New comments are reserved for **TURN COMPLETE** and **HUMAN NEEDED**.\n"
        "- Every notification comment carries a durable event marker so replay is a NO-OP.\n"
        "- This Issue never starts AUTO, Claude, Jules, Work, or any provider.\n"
    )


def render_issue_body(projection: StatusProjection, *, existing_body: str | None = None) -> str:
    runtime_content = _render_runtime_content(projection)
    runtime_block = managed_block(RUNTIME_START, RUNTIME_END, runtime_content)
    if existing_body is None or not existing_body.strip():
        return runtime_block + "\n"

    existing_runtime = extract_managed_block(existing_body, RUNTIME_START, RUNTIME_END)
    if existing_runtime is not None:
        return existing_body.replace(existing_runtime, runtime_block, 1).rstrip() + "\n"

    development_block = extract_managed_block(existing_body, DEVELOPMENT_START, DEVELOPMENT_END)
    if development_block is not None:
        return runtime_block + "\n\n" + development_block + "\n"

    # One-time migration from the legacy unmarked runtime-only body.
    return runtime_block + "\n"


def _event_identity(state: dict[str, Any], override: str | None) -> str | None:
    candidate = override or state.get("last_receipt_id") or state.get("last_command_id")
    if candidate in (None, ""):
        return None
    if not isinstance(candidate, str) or not _ID.fullmatch(candidate):
        raise ValueError("invalid notification event identity")
    return candidate


def notification_for_state(
    state: dict[str, Any],
    projection: StatusProjection,
    *,
    event_id: str | None = None,
    mention: str = "kamiyusense",
) -> Notification | None:
    validate_state(state)
    if not _MENTION.fullmatch(mention):
        raise ValueError("invalid GitHub mention")

    resolved = _event_identity(state, event_id)
    if resolved is None:
        return None

    if state["state"] == "COMPLETE":
        kind = "TURN_COMPLETE"
        title = "✅ TURN COMPLETE"
        message = "今回のLoopは安全なcheckpointで完了しました。現在、次の入力を受け付けられます。"
    elif projection.display_state == "BLOCKED":
        kind = "HUMAN_NEEDED"
        title = "🔴 HUMAN NEEDED"
        message = f"自動継続できない状態です。理由: {projection.reason}"
    else:
        return None

    marker = f"loop-status-receipt:{kind}:{resolved}"
    details = (
        f"- Loop: \`{projection.loop_id}\`\n"
        f"- Round: \`{projection.round}/{projection.max_rounds}\`\n"
        f"- Owner: \`{projection.owner}\`\n"
        f"- Runtime state: \`{projection.display_state}\`\n"
        f"- Command-bus state: \`{projection.source_state}\`\n"
        f"- Provider: \`{projection.provider_state}\`\n"
    )
    body = (
        f"{title}\n\n{message}\n\n{details}\n"
        f"@{mention}\n\n<!-- {marker} -->\n"
    )
    return Notification(kind=kind, event_id=resolved, marker=marker, body=body)


def _write(path: str | None, text: str) -> None:
    if path:
        Path(path).write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("state_file")
    parser.add_argument("--owner", required=True, choices=sorted(OWNERS))
    parser.add_argument("--expected-loop-id")
    parser.add_argument("--provider-state", default="UNKNOWN")
    parser.add_argument("--last-durable-progress", default="UNKNOWN")
    parser.add_argument("--event-id")
    parser.add_argument("--mention", default="kamiyusense")
    parser.add_argument("--body-out")
    parser.add_argument("--notification-out")
    parser.add_argument("--github-output")
    parser.add_argument("--existing-body-file")
    args = parser.parse_args()

    state = json.loads(Path(args.state_file).read_text(encoding="utf-8"))
    projection = project_state(
        state,
        owner=args.owner,
        provider_state=args.provider_state,
        last_durable_progress=args.last_durable_progress,
        expected_loop_id=args.expected_loop_id,
    )
    existing_body = None
    if args.existing_body_file:
        existing_body = Path(args.existing_body_file).read_text(encoding="utf-8")
    body = render_issue_body(projection, existing_body=existing_body)
    notification = notification_for_state(
        state,
        projection,
        event_id=args.event_id,
        mention=args.mention,
    )

    _write(args.body_out, body)
    _write(args.notification_out, notification.body if notification else "")

    if args.github_output:
        lines = [
            f"display_state={projection.display_state}",
            f"notification_kind={notification.kind if notification else 'NONE'}",
            f"notification_event_id={notification.event_id if notification else ''}",
            f"notification_marker={notification.marker if notification else ''}",
        ]
        Path(args.github_output).write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(body, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
