from __future__ import annotations

import unittest

from automation.command_bus.loop_status_development import (
    render_development_body,
    render_development_section,
)
from automation.command_bus.loop_status_issue import (
    DEVELOPMENT_END,
    DEVELOPMENT_START,
    RUNTIME_END,
    RUNTIME_START,
    managed_block,
)


def snapshot(**changes):
    value = {
        "main_sha": "a" * 40,
        "lanes": [
            {
                "pr": 4,
                "state": "open",
                "merged": False,
                "mergeable": True,
                "draft": False,
                "head_sha": "b" * 40,
                "commits": 40,
                "updated_at": "2026-09-27T13:02:22Z",
            },
            {
                "pr": 25,
                "state": "open",
                "merged": False,
                "mergeable": True,
                "draft": False,
                "head_sha": "c" * 40,
                "commits": 32,
                "updated_at": "2026-09-27T13:03:46Z",
            },
        ],
    }
    value.update(changes)
    return value


class LoopStatusDevelopmentTests(unittest.TestCase):
    def test_render_reports_github_evidence_without_live_inference(self):
        text = render_development_section(snapshot())
        self.assertIn("Relay", text)
        self.assertIn("Claude Loop", text)
        self.assertIn("#4", text)
        self.assertIn("#25", text)
        self.assertIn("今この瞬間に実行中だという証明には使いません", text)
        self.assertIn("PR更新だけを理由に SEMI_AUTO / AUTO を推測しません", text)
        self.assertIn("🟢 OPEN", text)
        self.assertIn("auto-refresh: **ENABLED on deployed main**", text)

    def test_lane_signal_is_caution_when_open_but_not_mergeable(self):
        changed = snapshot()
        changed["lanes"][0]["mergeable"] = False
        text = render_development_section(changed)
        self.assertIn("🟡 CHECK", text)

    def test_lane_signal_is_unknown_when_mergeability_unknown(self):
        changed = snapshot()
        changed["lanes"][0]["mergeable"] = None
        text = render_development_section(changed)
        self.assertIn("⚪ UNKNOWN", text)

    def test_append_development_block_preserves_runtime(self):
        runtime = managed_block(RUNTIME_START, RUNTIME_END, "# 🟢 SEMI_AUTO")
        body = render_development_body(runtime + "\n", snapshot())
        self.assertIn(runtime, body)
        self.assertEqual(body.count(DEVELOPMENT_START), 1)
        self.assertEqual(body.count(DEVELOPMENT_END), 1)
        self.assertIn("40", body)
        self.assertIn("32", body)

    def test_refresh_replaces_development_block_without_duplication(self):
        body = render_development_body("", snapshot())
        changed = snapshot()
        changed["lanes"][0]["commits"] = 41
        body2 = render_development_body(body, changed)
        self.assertEqual(body2.count(DEVELOPMENT_START), 1)
        self.assertEqual(body2.count(DEVELOPMENT_END), 1)
        self.assertIn("| 41 |", body2)
        self.assertNotIn("| 40 |", body2)

    def test_partial_marker_fails_closed(self):
        with self.assertRaisesRegex(ValueError, "markers"):
            render_development_body(
                f"legacy\n{DEVELOPMENT_START}\npartial",
                snapshot(),
            )

    def test_rejects_unexpected_pr_lane(self):
        bad = snapshot()
        bad["lanes"][0]["pr"] = 99
        with self.assertRaisesRegex(ValueError, "unexpected development PR"):
            render_development_section(bad)

    def test_rejects_invalid_head_sha(self):
        bad = snapshot()
        bad["lanes"][0]["head_sha"] = "not-a-sha"
        with self.assertRaisesRegex(ValueError, "head SHA"):
            render_development_section(bad)


if __name__ == "__main__":
    unittest.main()
