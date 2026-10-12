"""Claude takeover (owner rule 2026-10-12): Jules gets two attempts, then the Claude takeover routine gets one.

Rules: (1) Jules ignoring the corrective AND its Jules API resend goes to the takeover at once; (2) BLOCKED reasons
never go to the takeover; (3) the reviewer judges the takeover PR more strictly and never asks it for another round.
The reviewer prompt v1.8 and the takeover routine prompt are pinned here; the tick and the ports are tested with
fakes (no network).
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path
from types import SimpleNamespace

from automation.command_bus import claude_jules_loop as loop
from automation.command_bus import claude_jules_production_starter as st
from automation.command_bus import claude_jules_starter_gh as ghs
from automation.command_bus import claude_jules_starter_live as live

ROOT = Path(__file__).resolve().parents[3]
EV = ROOT / "docs" / "evidence" / "claude-jules-production-starter-20261009"
REPO = "kamiyusense/multi-ai-council-phase0"
JH = "2981c2324a98495ec23879a4359c2dbebae4a681"
R1 = {"round": 1, "verdict": "NEEDS_CORRECTION", "decision": "CORRECTIVE_REQUESTED", "pr": 366, "pr_head_sha": "a" * 40,
      "pr_head_tree": "b" * 40, "corrective_comment": "u#issuecomment-1", "reviewed_at": "2026-10-12T00:00:00Z"}
R2 = dict(R1, round=2, decision="TAKEOVER_REQUESTED", pr_head_sha=JH, corrective_comment=None)
TASK = {"task_id": "prod-c1-80a71d29ef", "issue": 365}
NOW = "2026-10-12T01:00:00Z"


class FakePort:
    def __init__(self, state=None, status="SENT"):
        self.state, self.status, self.opened = state, status, []

    def takeover_state(self, task_id):
        return self.state

    def open_takeover(self, task_id, **kw):
        self.opened.append((task_id, kw["receipt"]["round"]))
        return self.status


class TickRuleTests(unittest.TestCase):
    def run_(self, port, mine=(R1, R2), now=NOW):
        return loop._takeover(port, TASK, R2, mine=list(mine), now=now, why="two failures")

    def test_only_a_latest_takeover_receipt_asks_for_it(self):
        self.assertEqual(loop.takeover_wanted([R1, R2]), R2)
        self.assertIsNone(loop.takeover_wanted([R1]))
        self.assertIsNone(loop.takeover_wanted([R1, R2, dict(R2, round=3, decision="TASK_BLOCKED")]))

    def test_opens_once_then_reports_where_it_stands(self):
        port = FakePort()
        self.assertEqual(self.run_(port)[:3:2], ("TAKEOVER_REQUESTED", False))
        self.assertEqual(port.opened, [("prod-c1-80a71d29ef", 2)])
        state = {"pr": 372, "head": JH, "start": JH, "opened_at": "2026-10-12T00:30:00Z"}
        self.assertEqual(self.run_(FakePort(state))[0], "TAKEOVER_PENDING")
        self.assertEqual(self.run_(FakePort(state), now="2026-10-12T02:31:00Z")[:3:2], ("TAKEOVER_STALLED", True))
        moved = dict(state, head="c" * 40)
        self.assertEqual(self.run_(FakePort(moved))[0], "REVIEW_PENDING")          # the recovery wake reviews it
        self.assertEqual(self.run_(FakePort(moved), mine=(R1, R2, dict(R2, round=3, pr_head_sha="c" * 40)))[0],
                         "TAKEOVER_PENDING")

    def test_a_refused_or_unknown_open_is_visible_and_never_resent(self):
        self.assertTrue(self.run_(FakePort(status="REFUSED: takeover is not an authorized write"))[2])
        port = FakePort()
        port.open_takeover = lambda *a, **k: (_ for _ in ()).throw(st.WriteOutcomeUnknown("timeout"))
        self.assertEqual(self.run_(port)[0], "WRITE_UNCONFIRMED")

    def test_rule1_a_same_content_commit_after_the_resend_is_unresponsive_at_once(self):
        port = SimpleNamespace(api_message_sent_at=lambda rid: "2026-10-12T00:10:00Z",
                               commit_date=lambda sha: "2026-10-12T00:20:00Z")
        code = loop._resend_corrective(port, TASK, R1, head="d" * 40, now="2026-10-12T00:25:00Z", ack_minutes=60)[0]
        self.assertEqual(code, "JULES_UNRESPONSIVE")
        port.commit_date = lambda sha: "2026-10-12T00:05:00Z"                     # the commit came before it
        self.assertEqual(loop._resend_corrective(port, TASK, R1, head="d" * 40, now="2026-10-12T00:25:00Z",
                                                 ack_minutes=60)[0], "JULES_IGNORED_CORRECTIVE")


TASK_BODY = ('intro\n<!-- claude-closed-loop-task v1\n{"correlation_id":"prod-c1-80a71d29ef-c903927",'
             '"task_id":"prod-c1-80a71d29ef"}\n-->\n')
CAMPAIGN = {"campaign_id": "prod-c1", "repository": REPO, "control_issue": 346,
            "policy": {"trusted_writers": ["kamiyusense"], "base_branch": "main", "route": st.ROUTE}}


def port_with(pulls=(), cls=ghs.GhLoopPort, **kw):
    def get(path):
        tail = path.split(f"repos/{REPO}/", 1)[1]
        if tail.startswith("pulls?state=all&head=kamiyusense:claude/takeover-"):
            return list(pulls)
        raise AssertionError(path)
    p = cls(get, repo=REPO, campaign=CAMPAIGN, route_declaration={}, signals=[], **kw)
    p.read_issue = lambda n: {"number": n, "title": "[o2] session link", "body": TASK_BODY}
    return p


class PortTests(unittest.TestCase):
    def test_request_links_the_task_and_round_trips_through_the_pr_body(self):
        branch, start, payload = port_with().takeover_request("prod-c1-80a71d29ef", issue=365, receipt=R2)
        self.assertEqual((branch, start, payload["head"], payload["base"]),
                         ("claude/takeover-prod-c1-80a71d29ef", JH, branch, "main"))
        self.assertIn("Fixes #365", payload["body"])
        self.assertFalse(payload["draft"])
        pr = {"number": 372, "head": {"sha": JH}, "body": payload["body"], "created_at": NOW}
        self.assertEqual(port_with([pr]).takeover_state("prod-c1-80a71d29ef"),
                         {"pr": 372, "head": JH, "start": JH, "opened_at": NOW})
        self.assertIsNone(port_with().takeover_state("prod-c1-80a71d29ef"))
        with self.assertRaises(st.PreparedOnly):
            port_with().open_takeover("prod-c1-80a71d29ef", issue=365, receipt=R2)
        self.assertTrue(port_with().open_takeover("other-task", issue=365, receipt=R2).startswith("NOT_SENT"))


class Git:
    def __init__(self, head=None):
        self.head, self.created = head, []

    def remote_head(self, branch):
        return self.head

    def create_branch(self, branch, sha):
        self.created.append((branch, sha))


AUTH = {"profile": live.AUTH_PROFILE_V2, "campaign_id": "prod-c1", "repository": REPO, "budget_id": "b",
        "issues": "campaign", "writes": ["comment", "add_label", "create_issue", "api_message", "takeover"],
        "max_labels": 1, "max_activations": 9999, "max_writes": 12, "expires_at": "2099-01-01T00:00:00Z",
        "approved_by": "kamiyusense", "approval_ref": "test", "route": st.ROUTE, "billing": "subscription",
        "usage_credits_confirmed_off": True}


class LivePortTests(unittest.TestCase):
    def port(self, auth=AUTH, git=None):
        self.calls = []

        def runner(cmd, payload):
            self.calls.append((cmd[4], payload))
            return SimpleNamespace(returncode=0, stdout="{}", stderr="")
        p = port_with(cls=live.GhLiveWritePort, authorization=auth, runner=runner, now=lambda: NOW, carrier=git)
        p.stop_requested = lambda: None
        return p

    def test_creates_the_branch_at_the_reviewed_head_then_one_pr(self):
        git = Git()
        self.assertEqual(self.port(git=git).open_takeover("prod-c1-80a71d29ef", issue=365, receipt=R2), "SENT")
        self.assertEqual(git.created, [("claude/takeover-prod-c1-80a71d29ef", JH)])
        self.assertEqual([c[0] for c in self.calls], [f"repos/{REPO}/pulls"])
        git2 = Git(head=JH)                                                           # branch already there
        self.assertEqual(self.port(git=git2).open_takeover("prod-c1-80a71d29ef", issue=365, receipt=R2), "SENT")
        self.assertEqual(git2.created, [])

    def test_needs_the_takeover_write_and_a_git_client(self):
        no_kind = dict(AUTH, writes=["comment", "add_label", "create_issue"])
        self.assertIn("not an authorized write", self.port(auth=no_kind, git=Git()).open_takeover(
            "prod-c1-80a71d29ef", issue=365, receipt=R2))
        self.assertIn("no git client", self.port().open_takeover("prod-c1-80a71d29ef", issue=365, receipt=R2))
        self.assertEqual(self.calls, [])


class PromptTests(unittest.TestCase):
    def test_reviewer_v1_8_changes_only_the_takeover_lines(self):
        old = (EV / "routine-prompt-v1.7.CANDIDATE.txt").read_text(encoding="utf-8").splitlines()
        new = (EV / "routine-prompt-v1.8.CANDIDATE.txt").read_text(encoding="utf-8").splitlines()
        self.assertEqual(len(old), len(new))
        diffs = [i for i, (a, b) in enumerate(zip(old, new)) if a != b]
        self.assertEqual(len(diffs), 3)
        self.assertIn("CLAUDE_CLOSED_LOOP_REVIEWER_V1.8", new[0])
        rule = next(l for l in new if l.startswith("- NEEDS_CORRECTION with round > max_corrective_rounds"))
        for phrase in ("starts with `claude/takeover-`", "review it more strictly", "decision TASK_BLOCKED, no PR comment",
                       "round >= 2 (Jules' second failed attempt) -> decision TAKEOVER_REQUESTED",
                       "BLOCKED (the reasons above) is always TASK_BLOCKED, never a takeover"):
            self.assertIn(phrase, rule)

    def test_takeover_worker_prompt_keeps_its_hard_rules(self):
        raw = (EV / "takeover-routine-prompt-v1.CANDIDATE.txt").read_bytes().replace(b"\r\n", b"\n")
        raw.decode("ascii")
        text = raw.decode()
        for phrase in ("Work only on the PR branch that woke you", "never force push",
                       "Never merge, close or approve a PR", "Never use any API key", "Never start Jules",
                       "Never delete, skip or weaken an existing test", "at most one PR comment",
                       "The PR head must equal start_head", "Do not mention or address @jules"):
            self.assertIn(phrase, text)

    def test_active_authorization_allows_the_takeover(self):
        auth = json.loads((ROOT / "docs/claude-jules-loop/active/authorization.json").read_text(encoding="utf-8"))
        self.assertIn("takeover", auth["writes"])


if __name__ == "__main__":
    unittest.main()
