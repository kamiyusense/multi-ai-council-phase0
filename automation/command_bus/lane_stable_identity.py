"""Static identity contract for the Chat -> Work, Claude -> Jules and Symphony -> Codex lanes.

Same rules as ``semiauto_stable_identity.validate_semiauto_stable_identity`` (Chat -> Jules), selected by
(controller, mode, worker). It never issues an identity, never edits the registry and grants no live
authority: a lane passes only when the registry lists exactly one enabled lane of that shape whose
``identity_state`` is already DURABLE and the explicit durable context names that same loop_id. A reserved
name (for example ``claude-jules-auto``) in a PLACEHOLDER row never passes.
"""
from __future__ import annotations

from typing import Any

from .control_tower import validate_registry
from .runtime_state_initializer import runtime_state_path

LANE_SHAPES = {
    "chat-work": ("CHATGPT", "SEMI_AUTO", "WORK"),
    "claude-jules": ("CLAUDE", "AUTO", "JULES"),
    "symphony-codex": ("OTHER", "AUTO", "OTHER"),
}


def validate_lane_stable_identity(
    lane: str, *, registry: dict[str, Any], request: dict[str, Any], durable_context: dict[str, Any]
) -> str:
    """Return the registry-adopted loop_id of ``lane`` iff every identity rule holds, else raise ValueError."""
    if lane not in LANE_SHAPES:
        raise ValueError("unknown lane")
    if not isinstance(request, dict) or not isinstance(durable_context, dict):
        raise ValueError("request and durable context must be objects")
    controller, mode, worker = LANE_SHAPES[lane]
    lanes = [e for e in validate_registry(registry) if (
        e.controller_kind == controller and e.mode == mode and e.worker_kind == worker and e.enabled)]
    if len(lanes) != 1:
        raise ValueError(f"exactly one enabled {lane} lane is required")
    entry = lanes[0]
    if entry.identity_state != "DURABLE":
        raise ValueError(f"{lane} lane identity is not DURABLE")
    loop_id = durable_context.get("loop_id")
    runtime_state_path(loop_id)
    if loop_id != entry.loop_id:
        raise ValueError("durable context loop_id does not match adopted registry lane")
    if loop_id == request.get("origin_loop_id"):
        raise ValueError("origin_loop_id cannot be promoted to durable identity")
    if loop_id == request.get("command_id") or loop_id == durable_context.get("correlation_id"):
        raise ValueError("request or correlation identity cannot be durable loop_id")
    if loop_id.isdecimal() or loop_id in {
        request.get("target_branch"), request.get("target_repo"), str(durable_context.get("target_pr")),
    }:
        raise ValueError("session, PR, or branch identity cannot be durable loop_id")
    return loop_id
