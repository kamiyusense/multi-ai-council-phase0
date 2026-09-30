"""Bootstrap for the first ChatGPT Semi-Auto durable identity.

This provides an explicit PREPARE-ONLY boundary that solves the first-adoption
cycle. It prepares the first bundle while the registry is still PLACEHOLDER,
without performing live writes or relaxing the normal DURABLE check.
"""
from __future__ import annotations

from typing import Any
from .jules_semiauto_owner_prepare import (
    JulesSemiAutoAcquireBundle,
    prepare_jules_semiauto_acquire,
)
from .control_tower import validate_registry
from .semiauto_runtime_identity import inject_semiauto_durable_identity


def prepare_bootstrap_semiauto_acquire(
    *, registry: dict[str, Any], request: dict[str, Any],
    durable_context: dict[str, Any], session_response: dict[str, Any],
    target_pr_readback: dict[str, Any], now: Any,
) -> JulesSemiAutoAcquireBundle:
    """Prepare the first Semi-Auto bundle from a PLACEHOLDER registry.

    This does NOT grant authority, write durable records, or promote the
    registry. It merely builds the prepare bundle using the canonical ID.
    If the lane is already DURABLE, this fails closed to require the normal
    adopted path.
    """
    if not isinstance(request, dict) or not isinstance(durable_context, dict):
        raise ValueError("request and durable context must be objects")

    entries = validate_registry(registry)
    lanes = [entry for entry in entries if (
        entry.controller_kind == "CHATGPT" and entry.mode == "SEMI_AUTO"
        and entry.worker_kind == "JULES" and entry.enabled
    )]
    if len(lanes) != 1:
        raise ValueError("exactly one enabled ChatGPT Semi-Auto Jules lane is required for bootstrap")

    lane = lanes[0]
    if lane.identity_state == "DURABLE":
        raise ValueError("ChatGPT Semi-Auto lane is already DURABLE, use adopted path")
    if lane.identity_state != "PLACEHOLDER":
        raise ValueError("Bootstrap requires a PLACEHOLDER registry lane")

    injected_context = inject_semiauto_durable_identity(durable_context=durable_context)

    return prepare_jules_semiauto_acquire(
        request=request, durable_context=injected_context,
        session_response=session_response, target_pr_readback=target_pr_readback,
        now=now,
    )
