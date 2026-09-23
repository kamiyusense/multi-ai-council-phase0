"""Static browser session identity and capability gate.

Protocol identity does not imply runtime availability. UNKNOWN stays UNKNOWN.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class BrowserSessionId(StrEnum):
    WORK_CLOUD_BROWSER_JULES_UI = "WORK_CLOUD_BROWSER_JULES_UI"
    WORK_COMPUTER_USE_JULES_UI = "WORK_COMPUTER_USE_JULES_UI"
    DESKTOP_BUILTIN_BROWSER_JULES_UI = "DESKTOP_BUILTIN_BROWSER_JULES_UI"
    CHROME_EXISTING_SESSION_JULES_UI = "CHROME_EXISTING_SESSION_JULES_UI"


class RuntimeCapability(StrEnum):
    AVAILABLE = "AVAILABLE"
    AUTH_REQUIRED = "AUTH_REQUIRED"
    UNAVAILABLE = "UNAVAILABLE"
    BLOCKED = "BLOCKED"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class BrowserCapability:
    session_id: BrowserSessionId
    state: RuntimeCapability
    evidence_ref: str | None = None


def require_runtime_available(capability: BrowserCapability) -> None:
    if not isinstance(capability, BrowserCapability):
        raise ValueError("browser capability record required")
    if capability.state is RuntimeCapability.AVAILABLE:
        if not capability.evidence_ref:
            raise ValueError("AVAILABLE requires durable capability evidence")
        return
    if capability.state is RuntimeCapability.UNKNOWN:
        raise ValueError("browser runtime capability UNKNOWN")
    raise ValueError(f"browser runtime capability is {capability.state.value}")


def static_default_capabilities() -> tuple[BrowserCapability, ...]:
    return (
        BrowserCapability(BrowserSessionId.WORK_CLOUD_BROWSER_JULES_UI, RuntimeCapability.UNKNOWN),
        BrowserCapability(BrowserSessionId.WORK_COMPUTER_USE_JULES_UI, RuntimeCapability.UNKNOWN),
        BrowserCapability(BrowserSessionId.DESKTOP_BUILTIN_BROWSER_JULES_UI, RuntimeCapability.UNKNOWN),
        BrowserCapability(BrowserSessionId.CHROME_EXISTING_SESSION_JULES_UI, RuntimeCapability.UNKNOWN),
    )
