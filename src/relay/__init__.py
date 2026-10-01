"""Static Relay primitives for Multi-AI Council Phase 0.

No live provider process is started by this package.
"""

from .core_adapter import RelayCoreAdapter
from .duplicate_guard import DuplicateGuard, DuplicateDecision
from .envelope import DispatchEnvelope, DispatchSlot
from .result import RelayResult, RelayState

__all__ = [
    "DispatchEnvelope",
    "DispatchSlot",
    "DuplicateDecision",
    "DuplicateGuard",
    "RelayCoreAdapter",
    "RelayResult",
    "RelayState",
]
