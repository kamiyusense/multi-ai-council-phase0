"""Pure multi-loop Control Tower presentation for Phase 0 CT-1.

This module is display-only. It does not derive owner/liveness truth, read GitHub,
start providers, write Issue #33, or validate durable transition evidence.

Callers must supply already verified per-loop StatusProjection objects produced
by the existing durable transition path. A malformed or missing lane input is
isolated to UNKNOWN and never erases unrelated healthy lanes.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from .loop_status_issue import (
    DEVELOPMENT_END,
    DEVELOPMENT_START,
    DISPLAY_STATES,
    RUNTIME_END,
    RUNTIME_START,
    StatusProjection,
    extract_managed_block,
    managed_block,
)

_MAX_LOOPS = 8
_REGISTRY_KEYS = {"schema_version", "loops"}
_ENTRY_KEYS = {
    "loop_id", "display_name", "mode", "controller_kind", "worker_kind",
    "display_order", "enabled", "safe_detail_ref",
}
_MODES = {"SEMI_AUTO", "AUTO"}
_CONTROLLERS = {"CHATGPT", "CLAUDE", "WORK", "OTHER"}
_WORKERS = {"JULES", "GEMINI", "CLAUDE", "OTHER"}

_LOOP_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
_LABEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._+()/>-]{0,63}$")
_SAFE_DETAIL = re.compile(r"^(issue|pr):[1-9][0-9]{0,9}$")
_EVENT_KIND = re.compile(r"^[A-Z][A-Z0-9_]{0,31}$")
_EVENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_TARGET_REF = re.compile(r"^(issue|pr):[1-9][0-9]{0,9}$")

_ICONS = {
    "SEMI_AUTO": "🟢", "AUTO": "🟣", "IDLE": "🟡",
    "BLOCKED": "🔴", "STOPPED": "⚫", "UNKNOWN": "⚪",
}
_CONTROLLER_LABELS = {
    "CHATGPT": "ChatGPT", "CLAUDE": "Claude", "WORK": "Work", "OTHER": "Other",
}
_WORKER_LABELS = {
    "JULES": "Jules", "GEMINI": "Gemini", "CLAUDE": "Claude", "OTHER": "Other",
}

SNAPSHOT_START = "<!-- phase0-control-tower-json:v1"
SNAPSHOT_END = "-->"


@dataclass(frozen=True)
class RegistryEntry:
    loop_id: str
    display_name: str
    mode: str
    controller_kind: str
    worker_kind: str
    display_order: int
    enabled: bool
    safe_detail_ref: str


@dataclass(frozen=True)
class PerLoopProjectionInput:
    """Presentation metadata attached to an already verified StatusProjection."""

    projection: StatusProjection
    generation: int | None
    target_ref: str | None
    last_event_kind: str | None
    last_event_id: str | None


@dataclass(frozen=True)
class ControlTowerLane:
    loop_id: str
    display_name: str
    mode: str
    controller_kind: str
    worker_kind: str
    display_order: int
    safe_detail_ref: str
    display_state: str
    generation: int | None
    target_ref: str | None
    last_event_kind: str | None
    last_event_id: str | None
    human_action: str
    reason: str


@dataclass(frozen=True)
class ControlTowerModel:
    generated_at: str
    lanes: tuple[ControlTowerLane, ...]


@dataclass(frozen=True)
class ControlTowerRender:
    title: str
    body: str
    snapshot_json: str


def load_registry(path: str | Path) -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Control Tower registry must be a JSON object")
    return value


def validate_registry(registry: dict[str, Any]) -> tuple[RegistryEntry, ...]:
    if not isinstance(registry, dict) or set(registry) != _REGISTRY_KEYS:
        raise ValueError("Control Tower registry shape is invalid")
    if registry.get("schema_version") != 1:
        raise ValueError("unsupported Control Tower registry schema")
    raw_loops = registry.get("loops")
    if not isinstance(raw_loops, list) or len(raw_loops) > _MAX_LOOPS:
        raise ValueError("Control Tower registry loops are invalid or exceed bounded maximum")

    entries = []
    seen_loop_ids = set()
    seen_orders = set()
    for raw in raw_loops:
        if not isinstance(raw, dict) or set(raw) != _ENTRY_KEYS:
            raise ValueError("Control Tower registry entry shape is invalid")
        loop_id = raw["loop_id"]
        display_name = raw["display_name"]
        mode = raw["mode"]
        controller = raw["controller_kind"]
        worker = raw["worker_kind"]
        order = raw["display_order"]
        enabled = raw["enabled"]
        detail = raw["safe_detail_ref"]

        if not isinstance(loop_id, str) or not _LOOP_ID.fullmatch(loop_id):
            raise ValueError("invalid Control Tower loop_id")
        if loop_id in seen_loop_ids:
            raise ValueError("duplicate Control Tower loop_id")
        if not isinstance(display_name, str) or not _LABEL.fullmatch(display_name):
            raise ValueError("invalid Control Tower display_name")
        if mode not in _MODES:
            raise ValueError("invalid Control Tower mode")
        if controller not in _CONTROLLERS:
            raise ValueError("invalid Control Tower controller_kind")
        if worker not in _WORKERS:
            raise ValueError("invalid Control Tower worker_kind")
        if isinstance(order, bool) or not isinstance(order, int) or not 0 <= order <= 999:
            raise ValueError("invalid Control Tower display_order")
        if order in seen_orders:
            raise ValueError("duplicate Control Tower display_order")
        if not isinstance(enabled, bool):
            raise ValueError("invalid Control Tower enabled flag")
        if not isinstance(detail, str) or not _SAFE_DETAIL.fullmatch(detail) or "://" in detail:
            raise ValueError("invalid Control Tower safe_detail_ref")

        seen_loop_ids.add(loop_id)
        seen_orders.add(order)
        entries.append(RegistryEntry(
            loop_id, display_name, mode, controller, worker, order, enabled, detail
        ))

    return tuple(sorted(entries, key=lambda item: (item.display_order, item.loop_id)))


def build_control_tower(
    registry: dict[str, Any],
    lane_inputs: Mapping[str, PerLoopProjectionInput | Any],
    *,
    generated_at: str,
) -> ControlTowerModel:
    entries = validate_registry(registry)
    _parse_time(generated_at)
    if not isinstance(lane_inputs, Mapping):
        raise ValueError("lane_inputs must be a mapping")

    lanes = []
    for entry in entries:
        if not entry.enabled:
            continue
        raw = lane_inputs.get(entry.loop_id)
        try:
            lane = _verified_lane(entry, raw)
        except (ValueError, TypeError, KeyError, AssertionError) as exc:
            lane = _unknown_lane(entry, str(exc))
        lanes.append(lane)
    return ControlTowerModel(generated_at=generated_at, lanes=tuple(lanes))


def render_title(model: ControlTowerModel) -> str:
    semi = sum(lane.display_state == "SEMI_AUTO" for lane in model.lanes)
    auto = sum(lane.display_state == "AUTO" for lane in model.lanes)
    needs_you = sum(lane.human_action != "NONE" for lane in model.lanes)
    return f"🚦 Phase 0 — 🟢{semi} SEMI / 🟣{auto} AUTO / 🔴{needs_you} NEEDS YOU"


def render_snapshot(model: ControlTowerModel) -> str:
    payload = {
        "schema_version": 1,
        "project": "phase0",
        "generated_at": model.generated_at,
        "loops": [
            {
                "loop_id": lane.loop_id,
                "display_name": lane.display_name,
                "mode": lane.mode,
                "display_state": lane.display_state,
                "controller_kind": lane.controller_kind,
                "worker_kind": lane.worker_kind,
                "generation": lane.generation,
                "target_ref": lane.target_ref,
                "last_event_kind": lane.last_event_kind,
                "last_event_id": lane.last_event_id,
                "human_action": lane.human_action,
                "safe_detail_ref": lane.safe_detail_ref,
            }
            for lane in model.lanes
        ],
    }
    return json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def render_control_tower(
    model: ControlTowerModel,
    *,
    existing_body: str | None = None,
) -> ControlTowerRender:
    title = render_title(model)
    snapshot = render_snapshot(model)
    runtime_content = _render_runtime_content(model, snapshot)
    runtime_block = managed_block(RUNTIME_START, RUNTIME_END, runtime_content)

    if existing_body is None or not existing_body.strip():
        body = runtime_block + "\n"
    else:
        existing_runtime = extract_managed_block(existing_body, RUNTIME_START, RUNTIME_END)
        if existing_runtime is not None:
            body = existing_body.replace(existing_runtime, runtime_block, 1).rstrip() + "\n"
        else:
            development = extract_managed_block(existing_body, DEVELOPMENT_START, DEVELOPMENT_END)
            if development is not None:
                body = runtime_block + "\n\n" + development + "\n"
            else:
                body = runtime_block + "\n"
    return ControlTowerRender(title=title, body=body, snapshot_json=snapshot)


def notification_marker(lane: ControlTowerLane, kind: str) -> str:
    if kind not in {"TURN_COMPLETE", "HUMAN_NEEDED"}:
        raise ValueError("Control Tower notifications are limited to terminal/user-action events")
    if not lane.last_event_id or not _EVENT_ID.fullmatch(lane.last_event_id):
        raise ValueError("durable lane event id is required for notification dedupe")
    return f"control-tower-receipt:{kind}:{lane.loop_id}:{lane.last_event_id}"


def _verified_lane(entry: RegistryEntry, raw: Any) -> ControlTowerLane:
    if not isinstance(raw, PerLoopProjectionInput):
        raise ValueError("verified per-loop projection is unavailable")
    projection = raw.projection
    if not isinstance(projection, StatusProjection):
        raise ValueError("lane projection is not a StatusProjection")
    if projection.loop_id != entry.loop_id:
        raise ValueError("registry loop_id does not match verified projection")
    if projection.display_state not in DISPLAY_STATES:
        raise ValueError("unsupported verified display state")

    generation = raw.generation
    if generation is not None and (
        isinstance(generation, bool) or not isinstance(generation, int) or generation < 1
    ):
        raise ValueError("invalid verified generation")

    target_ref = raw.target_ref
    if target_ref is not None and (
        not isinstance(target_ref, str)
        or not _TARGET_REF.fullmatch(target_ref)
        or "://" in target_ref
    ):
        raise ValueError("invalid safe target_ref")

    event_kind = raw.last_event_kind
    if event_kind is not None and (
        not isinstance(event_kind, str) or not _EVENT_KIND.fullmatch(event_kind)
    ):
        raise ValueError("invalid durable event kind")

    event_id = raw.last_event_id
    if event_id is not None and (
        not isinstance(event_id, str) or not _EVENT_ID.fullmatch(event_id)
    ):
        raise ValueError("invalid durable event id")

    human_action = _single_line(projection.human_action, max_len=64)
    if projection.display_state == "BLOCKED" and human_action == "NONE":
        human_action = "REVIEW REQUIRED"

    return ControlTowerLane(
        loop_id=entry.loop_id,
        display_name=entry.display_name,
        mode=entry.mode,
        controller_kind=entry.controller_kind,
        worker_kind=entry.worker_kind,
        display_order=entry.display_order,
        safe_detail_ref=entry.safe_detail_ref,
        display_state=projection.display_state,
        generation=generation,
        target_ref=target_ref,
        last_event_kind=event_kind,
        last_event_id=event_id,
        human_action=human_action,
        reason=_single_line(projection.reason),
    )


def _unknown_lane(entry: RegistryEntry, reason: str) -> ControlTowerLane:
    return ControlTowerLane(
        loop_id=entry.loop_id,
        display_name=entry.display_name,
        mode=entry.mode,
        controller_kind=entry.controller_kind,
        worker_kind=entry.worker_kind,
        display_order=entry.display_order,
        safe_detail_ref=entry.safe_detail_ref,
        display_state="UNKNOWN",
        generation=None,
        target_ref=None,
        last_event_kind="UNKNOWN",
        last_event_id=None,
        human_action="REVIEW REQUIRED",
        reason=_single_line(reason),
    )


def _render_runtime_content(model: ControlTowerModel, snapshot: str) -> str:
    lines = [
        "# Runtime Loops",
        "",
        "この一覧は **display surface only** です。durable correctnessの正本は",
        "state / owner chain / receipt / evidence / provider observation / fresh target / authority/fencing です。",
        "",
    ]
    needs = [lane for lane in model.lanes if lane.human_action != "NONE"]
    if needs:
        lines += ["## 🔴 HUMAN NEEDED", ""]
        for lane in needs:
            lines.append(
                f"- **{_cell(lane.display_name)}** — {_cell(lane.human_action)} "
                f"({_cell(lane.display_state)}): {_cell(lane.reason)}"
            )
        lines.append("")

    lines += [
        "| Signal | Loop | Mode | Controller → Worker | Target | Gen | Last durable event | Human |",
        "| --- | --- | --- | --- | --- | ---: | --- | --- |",
    ]
    for lane in model.lanes:
        signal = f"{_ICONS[lane.display_state]} {lane.display_state}"
        controller_worker = (
            f"{_CONTROLLER_LABELS[lane.controller_kind]} → {_WORKER_LABELS[lane.worker_kind]}"
        )
        last = lane.last_event_kind or "-"
        if lane.last_event_id:
            last = f"{last} / {lane.last_event_id}"
        lines.append(
            "| " + " | ".join([
                _cell(signal),
                _cell(lane.display_name),
                _cell(lane.mode),
                _cell(controller_worker),
                _cell(lane.target_ref or "-"),
                _cell(str(lane.generation) if lane.generation is not None else "-"),
                _cell(last),
                _cell(lane.human_action),
            ]) + " |"
        )

    lines += [
        "",
        "## Notification policy",
        "",
        "- RUNNING / heartbeat / status refresh: body/title refresh only; no notification comment.",
        "- Notification classes are limited to **TURN COMPLETE** and **HUMAN NEEDED**.",
        "- Dedupe identity is loop_id + durable event_id; replay is a NO-OP.",
        "",
        SNAPSHOT_START,
        snapshot,
        SNAPSHOT_END,
    ]
    return "\n".join(lines) + "\n"


def _cell(value: Any) -> str:
    return _single_line(value).replace("|", "\\|").replace(chr(96), "'")


def _single_line(value: Any, *, fallback: str = "UNKNOWN", max_len: int = 200) -> str:
    if value is None:
        return fallback
    text = " ".join(str(value).split())
    if not text:
        return fallback
    return text[:max_len]


def _parse_time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("generated_at must be an ISO-8601 string")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError("generated_at must include timezone")
    return parsed
