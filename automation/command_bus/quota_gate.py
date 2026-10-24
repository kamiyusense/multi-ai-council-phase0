"""Quota gate per AI (docs/RELAY_TOWER_DIRECTION_V4.md section 6, step S7).

Each run reads the remaining quota through official means only and decides, per AI, whether that AI may run:

* Claude: the Claude Code statusLine JSON ``rate_limits.five_hour`` / ``seven_day`` (``used_percentage`` 0-100,
  ``resets_at`` epoch seconds; https://code.claude.com/docs/en/statusline).  The statusLine is fed by Claude Code
  itself, so reading it spends no quota.  ``spend_limit`` dollar fields are never copied.
* Codex: the summary of the app-server ``account/rateLimits/read`` answer made by
  ``src/relay/codex_account_readonly.summarize_account_evidence`` (no model turn).
* Grok: no official programmatic reading is known (UNKNOWN), so a weekly run cap (one number in the config) is used.

Rules: no fixed usage numbers other than the Grok cap (a plan change is seen on the next read); quota is never read
by asking a model; an unreadable quota pauses only that AI, and the owner's ``続けて OK <ai>`` comment on the board
(step S5 record) written after the pause started lets it run again; a limit that is reached is never overridden by
that comment; extra credits are used only when the config says so after an explicit owner approval.

Pure functions only: nothing here reads a CLI, GitHub or a provider.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

__all__ = ["QuotaPolicy", "QuotaReading", "load_policy", "read_claude_statusline", "read_codex_summary",
           "read_grok_runs", "decide", "status_ja"]

DEFAULT_POLICY_PATH = Path(__file__).resolve().parent / "config" / "quota_policy.json"
OK, LOW, EXHAUSTED, UNKNOWN = "OK", "LOW", "EXHAUSTED", "UNKNOWN"
_KEYS = {"schema_version", "pause_at_used_percent", "grok_weekly_run_cap", "credits_allowed"}


class QuotaError(ValueError):
    """Malformed policy (fail closed)."""


@dataclass(frozen=True)
class QuotaPolicy:
    pause_at_used_percent: float
    grok_weekly_run_cap: int
    credits_allowed: bool


@dataclass(frozen=True)
class QuotaReading:
    ai: str
    state: str                       # OK, LOW, EXHAUSTED or UNKNOWN
    used_percent: float | None
    resets_at: datetime | None
    source: str


def load_policy(path: Path | str = DEFAULT_POLICY_PATH) -> QuotaPolicy:
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or set(raw) != _KEYS or raw["schema_version"] != 1:
        raise QuotaError("POLICY_SHAPE")
    pause, cap, credits = raw["pause_at_used_percent"], raw["grok_weekly_run_cap"], raw["credits_allowed"]
    if isinstance(pause, bool) or not isinstance(pause, (int, float)) or not 0 < pause <= 100:
        raise QuotaError("PAUSE_PERCENT")
    if isinstance(cap, bool) or not isinstance(cap, int) or not 0 <= cap <= 1000:
        raise QuotaError("GROK_CAP")
    if not isinstance(credits, bool):
        raise QuotaError("CREDITS")
    return QuotaPolicy(float(pause), cap, credits)


def _percent(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    return float(value)


def _epoch(value: Any) -> datetime | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) \
            or not 0 < value < 32503680000:
        return None
    return datetime.fromtimestamp(value, tz=timezone.utc)


def _from_windows(ai: str, windows: list[tuple[float | None, datetime | None]], policy: QuotaPolicy,
                  source: str, now: datetime) -> QuotaReading:
    live = [(p, r) for p, r in windows if p is not None and (r is None or r > now)]
    if not live:
        return QuotaReading(ai, UNKNOWN, None, None, source)
    used, resets = max(live, key=lambda w: w[0])
    state = EXHAUSTED if used >= 100 else LOW if used >= policy.pause_at_used_percent else OK
    return QuotaReading(ai, state, used, resets, source)


def read_claude_statusline(payload: Any, policy: QuotaPolicy, now: datetime) -> QuotaReading:
    """From the statusLine JSON.  Absent ``rate_limits`` (not a subscriber, or before the first answer) is UNKNOWN."""
    limits = payload.get("rate_limits") if isinstance(payload, Mapping) else None
    windows = []
    if isinstance(limits, Mapping):
        for key in ("five_hour", "seven_day"):
            window = limits.get(key)
            if isinstance(window, Mapping):
                windows.append((_percent(window.get("used_percentage")), _epoch(window.get("resets_at"))))
    return _from_windows("claude", windows, policy, "statusline.rate_limits", now)


def read_codex_summary(summary: Any, policy: QuotaPolicy, now: datetime) -> QuotaReading:
    """From ``summarize_account_evidence`` output.  A non-ChatGPT route (API key) is never OK."""
    if not isinstance(summary, Mapping) or summary.get("auth_state") != "CHATGPT_ACCOUNT":
        return QuotaReading("codex", UNKNOWN, None, None, "app-server.account/rateLimits/read")
    windows = []
    for key in ("primary_window", "secondary_window"):
        window = summary.get(key)
        if isinstance(window, Mapping):
            windows.append((_percent(window.get("used_percent")), _epoch(window.get("resets_at_epoch"))))
    reading = _from_windows("codex", windows, policy, "app-server.account/rateLimits/read", now)
    if summary.get("ordinary_usage_allowed") is False and reading.state != UNKNOWN:
        return QuotaReading("codex", EXHAUSTED, reading.used_percent, reading.resets_at, reading.source)
    return reading


def read_grok_runs(runs_this_week: Any, policy: QuotaPolicy) -> QuotaReading:
    """Grok has no official reading: the weekly run cap from the config stands in for it."""
    if isinstance(runs_this_week, bool) or not isinstance(runs_this_week, int) or runs_this_week < 0:
        return QuotaReading("grok", UNKNOWN, None, None, "weekly_run_cap")
    used = 100.0 if policy.grok_weekly_run_cap == 0 else 100.0 * runs_this_week / policy.grok_weekly_run_cap
    state = EXHAUSTED if runs_this_week >= policy.grok_weekly_run_cap else OK
    return QuotaReading("grok", state, min(used, 100.0), None, "weekly_run_cap")


def decide(reading: QuotaReading, *, paused_since: datetime | None, resume: Mapping[str, Any] | None,
           policy: QuotaPolicy) -> tuple[bool, str]:
    """May this AI start new work now?  Returns (run, reason).

    ``resume`` is the board record entry for this AI (``{"comment_id", "at"}``), if any.  It lifts only an UNKNOWN
    pause that started before it; LOW and EXHAUSTED are never overridden by a comment.
    """
    if reading.state == OK:
        return True, "QUOTA_OK"
    if reading.state == EXHAUSTED:
        return (True, "CREDITS_ALLOWED") if policy.credits_allowed and reading.ai != "grok" else (False, "EXHAUSTED")
    if reading.state == LOW:
        return False, "LOW"
    if paused_since is not None and isinstance(resume, Mapping) and isinstance(resume.get("at"), str):
        try:
            at = datetime.fromisoformat(resume["at"].replace("Z", "+00:00"))
        except ValueError:
            return False, "UNKNOWN_PAUSED"
        if at.tzinfo is not None and at > paused_since:
            return True, "UNKNOWN_RESUMED_BY_OWNER"
    return False, "UNKNOWN_PAUSED"


_REASON_JA = {
    "QUOTA_OK": "動ける",
    "CREDITS_ALLOWED": "枠は使い切ったが、相棒の許可でクレジットを使う",
    "EXHAUSTED": "枠を使い切ったので休止中（リセット待ち）",
    "LOW": "枠が残り少ないので休止中",
    "UNKNOWN_PAUSED": "枠が不明なので休止中",
    "UNKNOWN_RESUMED_BY_OWNER": "枠は不明だが、相棒の「続けて OK」で再開",
}


def status_ja(reading: QuotaReading, reason: str) -> str:
    """One Japanese board line for this AI."""
    used = "UNKNOWN" if reading.used_percent is None else f"{reading.used_percent:.0f}%"
    return f"{reading.ai}：{_REASON_JA.get(reason, 'UNKNOWN')}（使用 {used}）"
