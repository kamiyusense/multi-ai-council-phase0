"""Static Relay primitives for Multi-AI Council Phase 0.

No live provider process is started by this package.
"""

from .duplicate_guard import DuplicateGuard, DuplicateDecision
from .core_adapter import RelayCoreAdapter
from .envelope import DispatchEnvelope, DispatchSlot
from .result import RelayResult, RelayState

__all__ = [
    "DispatchEnvelope",
    "RelayCoreAdapter",
    "DispatchSlot",
    "DuplicateDecision",
    "DuplicateGuard",
    "RelayResult",
    "RelayState",
]
