"""STATIC checks of the Council parts (step S8): Grok launch description, fan-out, answers, summary."""
from __future__ import annotations

import json
import unittest

from relay import council as c
from relay import council_grok as g

CID = "council-20261024-ab12"
PARENT = {"PATH": "/usr/bin", "HOME": "/home/u", "XAI_API_KEY": "xai-secret", "OPENAI_API_KEY": "sk-x",
          "GITHUB_TOKEN": "ghp_x", "XAI_BASE_URL": "https://example.invalid", "ANTHROPIC_API_KEY": "a"}


def answer(member, text="結論：A", signed=True, cid=CID, cid_id=1, at="2026-10-24T01:00:00Z"):
    marker = json.dumps({"council_id": cid, "from": member})
    sig = {"claude": "AI-Agent: claude"}.get(member, f"AI-Agent: {member}")
    body = f"{c.ANSWER_MARKER} {marker} -->\n{text}\n" + (sig if signed else "")
    return {"id": cid_id, "created_at": at, "body": body}


class GrokLaunchTests(unittest.TestCase):
    def test_keys_never_reach_the_child(self):
        for launch in (g.acp_launch(PARENT), g.headless_launch("質問", PARENT)):
            self.assertEqual(dict(launch.env), {"PATH": "/usr/bin", "HOME": "/home/u"})
            self.assertFalse(launch.live)
            self.assertNotIn("xai-secret", repr(launch))

    def test_official_modes_only(self):
        self.assertEqual(g.acp_launch(PARENT).argv, ("grok", "--no-auto-update", "agent", "stdio"))
        self.assertEqual(g.headless_launch("q", PARENT).argv, ("grok", "--no-auto-update", "-p", "q"))
        self.assertEqual(g.acp_launch(PARENT, r"C:\tools\grok.exe").argv[0], r"C:\tools\grok.exe")

    def test_other_binaries_and_bad_prompts_are_refused(self):
        for binary in ("bash", "/usr/bin/curl", "grok-wrapper", "antigravity"):
            with self.assertRaises(g.GrokLaunchError):
                g.acp_launch(PARENT, binary)
        for prompt in ("", "  ", "x" * 20_001, "a\x00b", None):
            with self.assertRaises(g.GrokLaunchError):
                g.headless_launch(prompt, PARENT)


class PlanTests(unittest.TestCase):
    def test_fan_out_never_includes_antigravity_and_follows_quota(self):
        plan = c.plan_council(CID, " どっち？ ", {"grok": (True, "QUOTA_OK"), "claude": (False, "LOW"),
                                                  "antigravity": (True, "QUOTA_OK")})
        self.assertEqual(plan.ask, ("grok",))
        self.assertEqual(plan.skipped, {"claude": "LOW", "codex": "QUOTA_UNKNOWN"})
        self.assertTrue(plan.antigravity_manual)
        self.assertEqual(plan.question, "どっち？")

    def test_bad_input_fails_closed(self):
        for cid, q in (("council-1-x", "q"), (CID, ""), (CID, "x" * 4_001), (None, "q")):
            with self.assertRaises(c.CouncilError):
                c.plan_council(cid, q, {})
        self.assertEqual(c.plan_council(CID, "q", {"grok": ("yes", "x")}).ask, ())


class TemplateTests(unittest.TestCase):
    def test_template_has_marker_signature_and_issue(self):
        plan = c.plan_council(CID, "どっち？", {})
        text = c.antigravity_template(plan, 470)
        self.assertIn(f'{c.ANSWER_MARKER} {{"council_id": "{CID}", "from": "antigravity"}} -->', text)
        self.assertIn("AI-Agent: antigravity", text)
        self.assertIn("Issue #470", text)
        for bad in (0, -1, True, "470"):
            with self.assertRaises(c.CouncilError):
                c.antigravity_template(plan, bad)


class CollectTests(unittest.TestCase):
    def test_signature_required_first_answer_counts(self):
        comments = [answer("grok", "一つ目", cid_id=1), answer("grok", "二つ目", cid_id=2, at="2026-10-24T02:00:00Z"),
                    answer("codex", signed=False, cid_id=3), answer("claude", cid_id=4),
                    answer("cursor", cid_id=5), answer("grok", cid="council-20261024-zz99", cid_id=6),
                    {"id": 7, "body": "ふつうのコメント"}]
        answers, notes = c.collect_answers(comments, CID)
        self.assertEqual(set(answers), {"grok", "claude"})
        self.assertTrue(answers["grok"].startswith("一つ目"))
        self.assertEqual(len(notes), 3)

    def test_wrong_member_signature_is_refused(self):
        body = answer("antigravity", signed=False)["body"] + "AI-Agent: grok"
        answers, notes = c.collect_answers([{"id": 1, "body": body}], CID)
        self.assertEqual(answers, {})
        self.assertIn("antigravity", notes[0])

    def test_long_answers_are_cut(self):
        answers, notes = c.collect_answers([answer("codex", "x" * 25_000)], CID)
        self.assertLess(len(answers["codex"]), 20_100)
        self.assertIn("cut", notes[0])


class SummaryTests(unittest.TestCase):
    def test_side_by_side_without_consensus(self):
        plan = c.plan_council(CID, "どっち？", {"grok": (True, "QUOTA_OK"), "claude": (False, "LOW")})
        text = c.summary_markdown(plan, {"grok": "A がいい"}, ["memo"])
        for member in c.MEMBERS:
            self.assertIn(f"### {member}", text)
        self.assertIn("（聞いていない：LOW）", text)
        self.assertIn("（回答なし）", text)
        self.assertIn("多数決や取捨選択はしない", text)
        self.assertTrue(text.endswith("AI-Agent: claude"))
        with self.assertRaises(c.CouncilError):
            c.summary_markdown(plan, {}, [], signer="antigravity")


if __name__ == "__main__":
    unittest.main()
