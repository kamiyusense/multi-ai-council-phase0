"""Static binding for an externally adopted ChatGPT Semi-Auto lane identity.

This does not issue an identity or promote a registry entry. The caller must
provide a separately managed registry snapshot; the current production
PLACEHOLDER registry intentionally fails this gate.
"""
from __future__ import annotations

from typing import Any
from .jules_semiauto_owner_prepare import (
    JulesSemiAutoAcquireBundle,
    prepare_jules_semiauto_acquire,
)

from .control_tower import validate_registry
from .runtime_state_initializer import runtime_state_path
from .semiauto_runtime_identity import inject_semiauto_durable_identity


def validate_semiauto_stable_identity(
    *, registry: dict[str, Any], request: dict[str, Any], durable_context: dict[str, Any]
) -> str:
    """Return only a registry-adopted lane ID matching the explicit context.

    Request metadata (origin loop, command, correlation, PR, branch) never
    creates the lane identity. A fixture may use a hypothetical DURABLE entry;
    this function never mutates the real registry or grants live authority.
    """
    if not isinstance(request, dict) or not isinstance(durable_context, dict):
        raise ValueError("request and durable context must be objects")
    entries = validate_registry(registry)
    lanes = [entry for entry in entries if (
        entry.controller_kind == "CHATGPT" and entry.mode == "SEMI_AUTO"
        and entry.worker_kind == "JULES" and entry.enabled
    )]
    if len(lanes) != 1:
        raise ValueError("exactly one enabled ChatGPT Semi-Auto Jules lane is required")
    lane = lanes[0]
    if lane.identity_state != "DURABLE":
        raise ValueError("ChatGPT Semi-Auto lane identity is not DURABLE")
    loop_id = durable_context.get("loop_id")
    runtime_state_path(loop_id)
    from .semiauto_runtime_identity import get_canonical_semiauto_loop_id
    canonical_id = get_canonical_semiauto_loop_id()
    if loop_id != canonical_id:
        raise ValueError("durable context loop_id does not match canonical identity source")
    if loop_id != lane.loop_id:
        raise ValueError("durable context loop_id does not match adopted registry lane")
    if loop_id == request.get("origin_loop_id"):
        raise ValueError("origin_loop_id cannot be promoted to durable identity")
    if loop_id == request.get("command_id") or loop_id == durable_context.get("correlation_id"):
        raise ValueError("request or correlation identity cannot be durable loop_id")
    if loop_id.isdecimal() or loop_id in {
        request.get("target_branch"), request.get("target_repo"),
        str(durable_context.get("target_pr")),
    }:
        raise ValueError("session, PR, or branch identity cannot be durable loop_id")
    return loop_id


def prepare_adopted_semiauto_acquire(
    *, registry: dict[str, Any], request: dict[str, Any],
    durable_context: dict[str, Any], session_response: dict[str, Any],
    target_pr_readback: dict[str, Any], now: Any,
) -> JulesSemiAutoAcquireBundle:
    """Compose identity validation with existing prepare-only ACQUIRE logic.

    This adapter does not create a durable identity, grant owner authority,
    read a live provider, or publish runtime state.
    Caller-supplied durable_context must NOT include loop_id.
    """
    injected_context = inject_semiauto_durable_identity(durable_context=durable_context)
    validate_semiauto_stable_identity(
        registry=registry, request=request, durable_context=injected_context,
    )
    return prepare_jules_semiauto_acquire(
        request=request, durable_context=injected_context,
        session_response=session_response, target_pr_readback=target_pr_readback,
        now=now,
    )
