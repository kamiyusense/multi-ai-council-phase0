"""Pure CLI used by the trusted Loop Status workflow.

The module performs no network access and no GitHub writes. It first turns a
validated owner chain into an exact fetch plan, then renders Status only from
the independently fetched readbacks.
"""
from __future__ import annotations

import argparse
import json
import re
from pathlib import Path
from typing import Any

from .loop_owner import validate_owner_chain, validate_owner_event
from .loop_owner_observation import provider_observation_path
from .loop_status_issue import notification_for_state, render_issue_body
from .loop_status_transition import project_durable_transition
from .validator import validate_state

_EVENT_FILE = re.compile(r"^([0-9]{6,})\.json$")
_MAX_OWNER_GENERATIONS = 100


def _load_json(path: str | Path) -> Any:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _write_json(path: str | Path, value: Any) -> None:
    Path(path).write_text(
        json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def load_owner_event_directory(path: str | Path, *, loop_id: str) -> list[dict[str, Any]]:
    directory = Path(path)
    if not directory.is_dir():
        raise ValueError("owner event directory is missing")
    entries = sorted(directory.iterdir(), key=lambda item: item.name)
    if not entries or len(entries) > _MAX_OWNER_GENERATIONS:
        raise ValueError("owner generation count is empty or exceeds bounded maximum")

    events: list[tuple[int, dict[str, Any]]] = []
    for item in entries:
        if not item.is_file():
            raise ValueError("owner event directory contains non-file entry")
        match = _EVENT_FILE.fullmatch(item.name)
        if match is None:
            raise ValueError("owner event filename is not canonical")
        generation = int(match.group(1))
        event = _load_json(item)
        if not isinstance(event, dict):
            raise ValueError("owner event is not a JSON object")
        validate_owner_event(event)
        if event["loop_id"] != loop_id:
            raise ValueError("owner event loop/path mismatch")
        if event["generation"] != generation or item.name != f"{generation:06d}.json":
            raise ValueError("owner generation filename mismatch")
        events.append((generation, event))

    events.sort(key=lambda pair: pair[0])
    return validate_owner_chain(event for _, event in events)


def build_fetch_plan(
    state: dict[str, Any],
    owner_events: list[dict[str, Any]],
    *,
    expected_loop_id: str,
) -> dict[str, Any]:
    validate_state(state)
    if state["loop_id"] != expected_loop_id:
        raise ValueError("state loop_id does not match requested loop")
    chain = validate_owner_chain(owner_events)
    latest = chain[-1]
    if latest["loop_id"] != expected_loop_id:
        raise ValueError("latest owner generation belongs to another loop")
    if state.get("last_command_id") != latest["command_id"]:
        raise ValueError("state last_command_id does not match latest owner generation")
    if state.get("last_receipt_id") != latest["source_receipt_id"]:
        raise ValueError("state last_receipt_id does not match latest owner generation")

    close_event = latest["event_type"] in {"RELEASE", "TERMINAL"}
    observation_ref = None if close_event else provider_observation_path(
        latest["loop_id"], latest["generation"]
    )
    return {
        "schema_version": 1,
        "loop_id": latest["loop_id"],
        "generation": latest["generation"],
        "fencing_token": latest["fencing_token"],
        "event_type": latest["event_type"],
        "expected_repo": latest["expected_repo"],
        "expected_pr": latest["expected_pr"],
        "expected_target_head": latest["expected_target_head"],
        "command_id": latest["command_id"],
        "correlation_id": latest["correlation_id"],
        "receipt_ref": latest["source_receipt_ref"],
        "evidence_refs": list(latest["evidence_refs"]),
        "provider_observation_ref": observation_ref,
    }


def _result_document(result: Any) -> dict[str, Any]:
    projection = result.projection
    decision = result.owner_decision
    return {
        "status": result.status,
        "reason": result.reason,
        "event_id": result.event_id,
        "display_state": projection.display_state if projection else None,
        "source_state": projection.source_state if projection else None,
        "owner": projection.owner if projection else None,
        "generation": decision.generation if decision else None,
        "fencing_token": decision.fencing_token if decision else None,
    }


def _write_github_output(path: str | None, result: Any, notification: Any) -> None:
    if path is None:
        return
    projection = result.projection
    if projection is None:
        raise ValueError("cannot emit GitHub output without projection")
    lines = [
        f"transition_status={result.status}",
        f"display_state={projection.display_state}",
        f"owner={projection.owner}",
        f"notification_kind={notification.kind if notification else 'NONE'}",
        f"notification_event_id={notification.event_id if notification else ''}",
        f"notification_marker={notification.marker if notification else ''}",
    ]
    Path(path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def render_from_readbacks(args: argparse.Namespace) -> int:
    state = _load_json(args.state_file)
    owner_events = load_owner_event_directory(
        args.owner_events_dir, loop_id=args.expected_loop_id
    )
    receipt = _load_json(args.receipt_file)
    target = _load_json(args.target_file)
    evidence_readbacks = _load_json(args.evidence_bundle_file)
    observation = (
        _load_json(args.provider_observation_file)
        if args.provider_observation_file
        else None
    )
    result = project_durable_transition(
        state,
        owner_events,
        receipt_ref=args.receipt_ref,
        receipt=receipt,
        target=target,
        evidence_readbacks=evidence_readbacks,
        provider_observation_ref=args.provider_observation_ref,
        provider_observation=observation,
        now=args.now,
        expected_loop_id=args.expected_loop_id,
        last_durable_progress=args.last_durable_progress,
    )
    _write_json(args.result_out, _result_document(result))
    if result.status == "UNKNOWN" or result.projection is None:
        return 2

    existing_body = (
        Path(args.existing_body_file).read_text(encoding="utf-8")
        if args.existing_body_file
        else None
    )
    body = render_issue_body(result.projection, existing_body=existing_body)
    notification = notification_for_state(
        state,
        result.projection,
        event_id=result.event_id,
        mention=args.mention,
    )
    Path(args.body_out).write_text(body, encoding="utf-8")
    Path(args.notification_out).write_text(
        notification.body if notification else "", encoding="utf-8"
    )
    _write_github_output(args.github_output, result, notification)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    plan = sub.add_parser("plan")
    plan.add_argument("--state-file", required=True)
    plan.add_argument("--owner-events-dir", required=True)
    plan.add_argument("--expected-loop-id", required=True)
    plan.add_argument("--plan-out", required=True)

    render = sub.add_parser("render")
    render.add_argument("--state-file", required=True)
    render.add_argument("--owner-events-dir", required=True)
    render.add_argument("--expected-loop-id", required=True)
    render.add_argument("--receipt-ref", required=True)
    render.add_argument("--receipt-file", required=True)
    render.add_argument("--target-file", required=True)
    render.add_argument("--evidence-bundle-file", required=True)
    render.add_argument("--provider-observation-ref")
    render.add_argument("--provider-observation-file")
    render.add_argument("--now", required=True)
    render.add_argument("--last-durable-progress", default="UNKNOWN")
    render.add_argument("--existing-body-file")
    render.add_argument("--body-out", required=True)
    render.add_argument("--notification-out", required=True)
    render.add_argument("--result-out", required=True)
    render.add_argument("--github-output")
    render.add_argument("--mention", default="kamiyusense")

    args = parser.parse_args()
    if args.command == "plan":
        state = _load_json(args.state_file)
        events = load_owner_event_directory(
            args.owner_events_dir, loop_id=args.expected_loop_id
        )
        _write_json(
            args.plan_out,
            build_fetch_plan(
                state,
                events,
                expected_loop_id=args.expected_loop_id,
            ),
        )
        return 0
    return render_from_readbacks(args)


if __name__ == "__main__":
    raise SystemExit(main())
