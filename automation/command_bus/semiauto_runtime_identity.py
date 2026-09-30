"""Runtime source for the canonical ChatGPT Semi-Auto durable identity."""
from __future__ import annotations

from typing import Any
from .runtime_state_initializer import runtime_state_path

_CANONICAL_ID = "chatgpt-semi-auto-v1"


def get_canonical_semiauto_loop_id() -> str:
    """Return the explicit production-facing stable durable loop ID."""
    runtime_state_path(_CANONICAL_ID)
    return _CANONICAL_ID


def inject_semiauto_durable_identity(
    *, durable_context: dict[str, Any]
) -> dict[str, Any]:
    """Build/inject the durable context loop_id from the canonical source.

    Caller-supplied loop_id must be rejected rather than overriding the source.
    Input objects are not mutated.
    """
    if not isinstance(durable_context, dict):
        raise ValueError("durable_context must be a dictionary")
    if "loop_id" in durable_context:
        raise ValueError("caller cannot supply loop_id; it is strictly injected by the source")

    injected = dict(durable_context)
    injected["loop_id"] = get_canonical_semiauto_loop_id()
    return injected
