"""Read-only Claude quota evidence mappers (prepare-only; nothing is queried, nothing calls these yet).

Two official surfaces exist in claude-agent-acp 0.84.0/0.85.1 and both need a live Claude CLI/account, so they are
a LIVE boundary and stay unused here:

* ``rate_limit_event`` -> ``usage_update`` with ``_meta["_claude/rateLimit"]`` (SDK ``SDKRateLimitInfo``), pushed during a turn;
* the ``/usage`` command (structured response, rate-limit windows with utilization / resets_at).

These pure functions turn an already-received object into a small evidence dict. They keep only the status,
limit window, used percent and reset time. Cost, token counts, subscription type, credits / currency / spend limits,
e-mail and organization are never copied. Missing or malformed fields are UNKNOWN; nothing is inferred.
"""

from __future__ import annotations

import math
from datetime import datetime
from typing import Any

__all__ = ["summarize_claude_rate_limit_info", "summarize_claude_usage_response"]

UNKNOWN = "UNKNOWN"
_STATUS = {"allowed", "allowed_warning", "rejected"}
_LIMIT_TYPES = {"five_hour", "seven_day", "seven_day_opus", "seven_day_sonnet", "seven_day_overage_included", "overage"}


_MAX_EPOCH = 32503680000  # year 3000: anything later is treated as malformed


def _percent(value: Any) -> float | str:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
        return UNKNOWN
    return value


def _epoch(value: Any) -> int | str:
    if isinstance(value, bool):
        return UNKNOWN
    if isinstance(value, (int, float)):
        return int(value) if math.isfinite(value) and 0 <= value <= _MAX_EPOCH else UNKNOWN
    if isinstance(value, str):
        try:
            epoch = int(datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp())
        except (ValueError, OverflowError, OSError):
            return UNKNOWN
        return epoch if 0 <= epoch <= _MAX_EPOCH else UNKNOWN
    return UNKNOWN


def _stale(resets_at_epoch: Any, now_epoch: float | None) -> bool | str:
    """A window whose reset time has already passed describes an earlier period: stale, not current."""
    if now_epoch is None or not isinstance(resets_at_epoch, int):
        return UNKNOWN
    return resets_at_epoch <= now_epoch


def summarize_claude_rate_limit_info(info: Any, now_epoch: float | None = None) -> dict[str, Any]:
    """Map one SDK ``rate_limit_info`` (the ``_claude/rateLimit`` metadata).

    ``conflict`` is True when status and utilization contradict each other (``rejected`` below 100 %, or
    ``allowed`` at/above 100 %); ``stale`` needs ``now_epoch`` (else UNKNOWN).
    """
    evidence: dict[str, Any] = {"status": UNKNOWN, "limit_type": UNKNOWN, "used_percent": UNKNOWN,
                                "resets_at_epoch": UNKNOWN, "conflict": UNKNOWN, "stale": UNKNOWN, "side_effects": 0}
    if not isinstance(info, dict):
        return evidence
    if info.get("status") in _STATUS:
        evidence["status"] = info["status"]
    if info.get("rateLimitType") in _LIMIT_TYPES:
        evidence["limit_type"] = info["rateLimitType"]
    evidence["used_percent"] = _percent(info.get("utilization"))
    evidence["resets_at_epoch"] = _epoch(info.get("resetsAt"))
    evidence["stale"] = _stale(evidence["resets_at_epoch"], now_epoch)
    if evidence["status"] != UNKNOWN and evidence["used_percent"] != UNKNOWN:
        used = evidence["used_percent"]
        evidence["conflict"] = (evidence["status"] == "rejected" and used < 100) or (evidence["status"] == "allowed" and used >= 100)
    return evidence


def summarize_claude_usage_response(usage: Any, now_epoch: float | None = None) -> dict[str, Any]:
    """Map the structured ``/usage`` response: only the five-hour and seven-day windows (``stale`` needs ``now_epoch``)."""
    evidence: dict[str, Any] = {"rate_limits_available": UNKNOWN, "five_hour": UNKNOWN, "seven_day": UNKNOWN, "side_effects": 0}
    if not isinstance(usage, dict):
        return evidence
    if isinstance(usage.get("rate_limits_available"), bool):
        evidence["rate_limits_available"] = usage["rate_limits_available"]
    limits = usage.get("rate_limits")
    if isinstance(limits, dict):
        for key in ("five_hour", "seven_day"):
            window = limits.get(key)
            if isinstance(window, dict) and _percent(window.get("utilization")) != UNKNOWN:
                resets = _epoch(window.get("resets_at"))
                evidence[key] = {"used_percent": window["utilization"], "resets_at_epoch": resets, "stale": _stale(resets, now_epoch)}
    return evidence
