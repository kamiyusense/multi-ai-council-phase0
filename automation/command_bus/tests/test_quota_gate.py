"""STATIC checks of the per-AI quota gate (step S7)."""
from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from automation.command_bus import quota_gate as qg

POLICY = qg.load_policy()
NOW = datetime(2026, 10, 24, 10, 0, tzinfo=timezone.utc)
LATER = int((NOW + timedelta(hours=2)).timestamp())
PAST = int((NOW - timedelta(hours=1)).timestamp())


def statusline(five=None, seven=None, five_reset=LATER, seven_reset=LATER, spend=None):
    limits = {}
    if five is not None:
        limits["five_hour"] = {"used_percentage": five, "resets_at": five_reset}
    if seven is not None:
        limits["seven_day"] = {"used_percentage": seven, "resets_at": seven_reset}
    if spend is not None:
        limits["spend_limit"] = spend
    return {"session_id": "x", "rate_limits": limits}


def codex(primary=None, secondary=None, auth="CHATGPT_ACCOUNT", allowed=True):
    def window(p):
        return "UNKNOWN" if p is None else {"used_percent": p, "window_minutes": 300, "resets_at_epoch": LATER}
    return {"auth_state": auth, "plan_type": "plus", "ordinary_usage_allowed": allowed,
            "primary_window": window(primary), "secondary_window": window(secondary)}


class PolicyTests(unittest.TestCase):
    def test_committed_policy(self):
        self.assertEqual((POLICY.pause_at_used_percent, POLICY.credits_allowed), (95.0, False))
        self.assertIsInstance(POLICY.grok_weekly_run_cap, int)

    def test_bad_policies_fail_closed(self):
        raw = json.loads(qg.DEFAULT_POLICY_PATH.read_text(encoding="utf-8"))
        for change in ({"credits_allowed": "yes"}, {"pause_at_used_percent": 0}, {"grok_weekly_run_cap": -1},
                       {"extra": 1}, {"pause_at_used_percent": True}):
            with tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "p.json"
                path.write_text(json.dumps({**raw, **change}), encoding="utf-8")
                with self.assertRaises(qg.QuotaError):
                    qg.load_policy(path)


class ClaudeTests(unittest.TestCase):
    def test_worst_live_window_decides(self):
        reading = qg.read_claude_statusline(statusline(five=20, seven=60), POLICY, NOW)
        self.assertEqual((reading.state, reading.used_percent), ("OK", 60.0))
        self.assertEqual(qg.read_claude_statusline(statusline(five=96, seven=10), POLICY, NOW).state, "LOW")
        self.assertEqual(qg.read_claude_statusline(statusline(five=100), POLICY, NOW).state, "EXHAUSTED")

    def test_absent_or_expired_or_malformed_is_unknown(self):
        for payload in ({}, {"rate_limits": {}}, statusline(five=50, five_reset=PAST), statusline(five="50"),
                        statusline(five=True), None):
            self.assertEqual(qg.read_claude_statusline(payload, POLICY, NOW).state, "UNKNOWN")

    def test_spend_limit_dollars_are_ignored(self):
        reading = qg.read_claude_statusline(statusline(five=10, spend={"used_percentage": 99, "used_usd": 314.0}),
                                            POLICY, NOW)
        self.assertEqual((reading.state, reading.used_percent), ("OK", 10.0))
        self.assertNotIn("314", repr(reading))


class CodexAndGrokTests(unittest.TestCase):
    def test_codex_windows_and_route(self):
        self.assertEqual(qg.read_codex_summary(codex(30, 70), POLICY, NOW).state, "OK")
        self.assertEqual(qg.read_codex_summary(codex(30, 70, allowed=False), POLICY, NOW).state, "EXHAUSTED")
        for summary in (codex(30, auth="API_KEY_ROUTE_VIOLATION"), codex(), {}, None):
            self.assertEqual(qg.read_codex_summary(summary, POLICY, NOW).state, "UNKNOWN")

    def test_grok_weekly_cap(self):
        self.assertEqual(qg.read_grok_runs(0, POLICY).state, "OK")
        self.assertEqual(qg.read_grok_runs(POLICY.grok_weekly_run_cap, POLICY).state, "EXHAUSTED")
        self.assertEqual(qg.read_grok_runs(None, POLICY).state, "UNKNOWN")


class DecideTests(unittest.TestCase):
    def test_unknown_pauses_until_a_later_owner_resume(self):
        unknown = qg.QuotaReading("claude", "UNKNOWN", None, None, "x")
        paused = NOW - timedelta(hours=1)
        self.assertEqual(qg.decide(unknown, paused_since=paused, resume=None, policy=POLICY), (False, "UNKNOWN_PAUSED"))
        old = {"comment_id": 1, "at": (paused - timedelta(minutes=5)).isoformat()}
        self.assertEqual(qg.decide(unknown, paused_since=paused, resume=old, policy=POLICY)[0], False)
        new = {"comment_id": 2, "at": (paused + timedelta(minutes=5)).isoformat()}
        self.assertEqual(qg.decide(unknown, paused_since=paused, resume=new, policy=POLICY),
                         (True, "UNKNOWN_RESUMED_BY_OWNER"))

    def test_reached_limits_are_never_overridden_by_a_comment(self):
        resume = {"comment_id": 2, "at": NOW.isoformat()}
        for state, reason in (("LOW", "LOW"), ("EXHAUSTED", "EXHAUSTED")):
            reading = qg.QuotaReading("codex", state, 99.0, None, "x")
            self.assertEqual(qg.decide(reading, paused_since=NOW - timedelta(hours=1), resume=resume, policy=POLICY),
                             (False, reason))

    def test_credits_only_when_the_policy_allows_and_never_for_grok(self):
        allowing = qg.QuotaPolicy(95.0, 20, True)
        exhausted = qg.QuotaReading("claude", "EXHAUSTED", 100.0, None, "x")
        self.assertEqual(qg.decide(exhausted, paused_since=None, resume=None, policy=allowing), (True, "CREDITS_ALLOWED"))
        grok = qg.QuotaReading("grok", "EXHAUSTED", 100.0, None, "x")
        self.assertEqual(qg.decide(grok, paused_since=None, resume=None, policy=allowing), (False, "EXHAUSTED"))

    def test_board_line(self):
        unknown = qg.QuotaReading("grok", "UNKNOWN", None, None, "x")
        self.assertEqual(qg.status_ja(unknown, "UNKNOWN_PAUSED"), "grok：枠が不明なので休止中（使用 UNKNOWN）")


if __name__ == "__main__":
    unittest.main()
