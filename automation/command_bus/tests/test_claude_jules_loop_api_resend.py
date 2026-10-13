"""Jules API resend of an ignored corrective (docs/CLAUDE_JULES_API_ROUTE_V1.md).

The shapes are the ones the first LIVE cycle produced: PR #353, receipt round 1 on head 7f7def9, then Jules pushed
364f92c with the same tree and the loop waited forever.  No network: GETs come from a dict, the carrier is a fake.
"""
from __future__ import annotations

import json
import unittest

from automation.command_bus import claude_jules_loop as loop
from automation.command_bus import claude_jules_production_starter as st
from automation.command_bus import claude_jules_starter_gh as ghs
from automation.command_bus import claude_jules_starter_live as live

REPO = "kamiyusense/multi-ai-council-phase0"
OWNER = "kamiyusense"
H1, T1 = "7f7def942f7518d65c073c68bc32eafc09cdd677", "b32202c771772935062aa13dcf7c6ea240b7f9ad"
H2 = "364f92c0000000000000000000000000000000aa"
SESSION = "4724323400892625017"
URL = f"https://github.com/{REPO}/pull/353#issuecomment-6098813102"
CORRECTIVE = (f"@jules\nFinding 1: ...\n<!-- claude-closed-loop-corrective v1 "
              f'{{"correlation_id":"c","pr_head_sha":"{H1}","round":1}} -->')
RECEIPT = {"round": 1, "verdict": "NEEDS_CORRECTION", "decision": "CORRECTIVE_REQUESTED", "pr": 353,
           "pr_head_sha": H1, "pr_head_tree": T1, "corrective_comment": URL, "reviewed_at": "2026-10-10T14:58:31Z"}
PR_BODY = (f"Fixes #352\n\n*PR created automatically by Jules for task [{SESSION}]"
           f"(https://jules.google.com/task/{SESSION})*")
CAMPAIGN = {"campaign_id": "prod-c1", "repository": REPO, "control_issue": 346,
            "policy": {"trusted_writers": [OWNER], "jules_ack_timeout_minutes": 60}}
NOW = "2026-10-10T15:10:00Z"


def getter(responses, *, carrier_commits=()):
    calls = []

    def get(path):
        calls.append(path)
        tail = path.split(f"repos/{REPO}/", 1)[1]
        if tail.startswith("commits?"):
            return [c for c in carrier_commits if c["path"] in tail]
        if tail in responses:
            return responses[tail]
        raise AssertionError(path)
    get.calls = calls
    return get


GH = {f"git/commits/{H2}": {"tree": {"sha": T1}},
      "pulls/353": {"body": PR_BODY},
      "issues/comments/6098813102": {"user": {"login": OWNER}, "body": CORRECTIVE}}


class IgnoredCorrectiveTests(unittest.TestCase):
    def find(self, head, tree=T1, now=NOW, mine=(RECEIPT,)):
        return loop.ignored_corrective(list(mine), head=head, head_tree=lambda: tree, now=now, ack_minutes=60)

    def test_same_tree_commit_after_a_corrective_is_ignored_at_once(self):
        self.assertEqual(self.find(H2), RECEIPT)                    # the PR #353 stall

    def test_a_changed_tree_goes_to_the_normal_review(self):
        self.assertIsNone(self.find(H2, tree="0" * 40))

    def test_no_commit_waits_for_the_ack_timeout(self):
        self.assertIsNone(self.find(H1, now="2026-10-10T15:30:00Z"))
        self.assertEqual(self.find(H1, now="2026-10-10T15:58:31Z"), RECEIPT)

    def test_api_first_sends_at_once_without_waiting_for_a_commit(self):
        found = loop.ignored_corrective([RECEIPT], head=H1, head_tree=lambda: T1, now="2026-10-10T14:59:00Z",
                                        ack_minutes=60, api_first=True)
        self.assertEqual(found, RECEIPT)
        self.assertIsNone(self.find(H1, now="2026-10-10T14:59:00Z"))              # default still waits

    def test_a_later_review_means_the_corrective_was_answered(self):
        later = dict(RECEIPT, round=2, verdict="PASS", decision="ADOPT_RECORDED", corrective_comment=None)
        self.assertIsNone(self.find(H2, mine=(RECEIPT, later)))
        self.assertIsNone(self.find(H2, mine=(dict(RECEIPT, decision="CORRECTIVE_EXISTS"),)))


class FakePort:
    def __init__(self, sent_at=None, status="SENT", raises=None):
        self.sent_at, self.status, self.raises, self.calls = sent_at, status, raises, []

    def api_message_sent_at(self, rid):
        return self.sent_at

    def api_message(self, rid, **kw):
        self.calls.append(rid)
        if self.raises:
            raise self.raises
        return self.status


class ResendDecisionTests(unittest.TestCase):
    task = {"task_id": "prod-c1-6c755da2db", "issue": 352}

    def run_(self, port, now=NOW):
        return loop._resend_corrective(port, self.task, RECEIPT, head=H2, now=now, ack_minutes=60)

    def test_first_wake_sends_once_with_a_stable_request_id(self):
        port = FakePort()
        self.assertEqual(self.run_(port)[0], "JULES_IGNORED_CORRECTIVE")
        self.assertEqual(port.calls, ["prod-c1-6c755da2db-r1-msg"])

    def test_already_sent_is_never_resent_and_escalates_after_the_timeout(self):
        port = FakePort(sent_at="2026-10-10T15:05:00Z")
        self.assertEqual(self.run_(port)[:3:2], ("JULES_IGNORED_CORRECTIVE", False))
        self.assertEqual(self.run_(port, now="2026-10-10T16:05:00Z")[:3:2], ("JULES_UNRESPONSIVE", True))
        self.assertEqual(port.calls, [])

    def test_unknown_outcome_and_refusal_are_visible(self):
        self.assertEqual(self.run_(FakePort(raises=st.WriteOutcomeUnknown("timeout")))[0], "WRITE_UNCONFIRMED")
        code, reason, human = self.run_(FakePort(status="REFUSED: limit"))
        self.assertEqual(code, "JULES_RESEND_REFUSED")
        self.assertTrue(human)
        self.assertIn("REFUSED: limit", reason)


class RequestTests(unittest.TestCase):
    def port(self, gh=GH):
        return ghs.GhLoopPort(getter(gh), repo=REPO, campaign=CAMPAIGN, route_declaration={}, signals=[])

    def test_request_matches_the_message_workflow(self):
        path, req = self.port().api_message_request("prod-c1-6c755da2db-r1-msg", receipt=RECEIPT, head=H2)
        self.assertEqual(path, "automation/command_bus/jules_api_message_requests/prod-c1-6c755da2db-r1-msg.json")
        self.assertEqual((req["session_id"], req["expected_state"]), (SESSION, "COMPLETED"))
        self.assertEqual(set(req), {"session_id", "expected_state", "prompt"})
        self.assertIn(URL, req["prompt"])
        self.assertIn(CORRECTIVE, req["prompt"])
        long = dict(GH, **{"issues/comments/6098813102": {"user": {"login": OWNER}, "body": CORRECTIVE + "x" * 9000}})
        self.assertEqual(len(self.port(long).api_message_request("r", receipt=RECEIPT, head=H2)[1]["prompt"]),
                         ghs.MESSAGE_LIMIT)

    def test_unsafe_inputs_are_not_sent(self):
        cases = {"two sessions": dict(GH, **{"pulls/353": {"body": PR_BODY + " https://jules.google.com/task/9"}}),
                 "no session": dict(GH, **{"pulls/353": {"body": "Fixes #352"}}),
                 "untrusted author": dict(GH, **{"issues/comments/6098813102": {"user": {"login": "x"},
                                                                               "body": CORRECTIVE}}),
                 "not a corrective": dict(GH, **{"issues/comments/6098813102": {"user": {"login": OWNER},
                                                                                "body": "@jules hi"}})}
        for name, gh in cases.items():
            with self.subTest(name):
                self.assertTrue(self.port(gh).api_message("r", issue=352, receipt=RECEIPT,
                                                          head=H2).startswith("NOT_SENT"))
        with self.assertRaises(ValueError):
            self.port().api_message_request("../x", receipt=RECEIPT, head=H2)

    def test_read_only_port_only_prepares(self):
        port = self.port()
        with self.assertRaises(st.PreparedOnly):
            port.api_message("r1", issue=352, receipt=RECEIPT, head=H2)
        self.assertEqual(port.prepared[-1]["write"], "api_message")


class Carrier:
    def __init__(self, error=None):
        self.error, self.created = error, []

    def create(self, path, text, message, branch):
        if self.error:
            raise self.error
        self.created.append((path, json.loads(text), branch))


AUTH = {"profile": live.AUTH_PROFILE_V2, "campaign_id": "prod-c1", "repository": REPO, "budget_id": "b",
        "issues": "campaign", "writes": ["comment", "add_label", "create_issue", "api_message"], "max_labels": 1,
        "max_activations": 50, "max_writes": 12, "expires_at": "2026-10-24T07:00:00Z", "approved_by": OWNER,
        "approval_ref": "test", "route": st.ROUTE, "billing": "subscription", "usage_credits_confirmed_off": True}


class LivePortTests(unittest.TestCase):
    def port(self, *, auth=AUTH, carrier=None, recent=0):
        commits = [{"path": "path=automation/command_bus/jules_api_message_requests&"}] * recent
        p = live.GhLiveWritePort(getter(GH, carrier_commits=commits), repo=REPO, campaign=CAMPAIGN,
                                 route_declaration={}, signals=[], authorization=auth, now=lambda: NOW,
                                 carrier=carrier)
        p.stop_requested = lambda: None
        return p

    def send(self, port, rid="prod-c1-6c755da2db-r1-msg"):
        return port.api_message(rid, issue=352, receipt=RECEIPT, head=H2)

    def test_sends_one_request_file_to_the_carrier(self):
        carrier = Carrier()
        port = self.port(carrier=carrier)
        self.assertEqual(self.send(port), "SENT")
        path, req, branch = carrier.created[0]
        self.assertEqual((branch, req["session_id"]), (ghs.CARRIER_BRANCH, SESSION))
        self.assertTrue(self.send(port, "other-r1-msg").startswith("REFUSED"))     # one per wake
        self.assertEqual(len(carrier.created), 1)

    def test_limits_and_authorization(self):
        no_kind = dict(AUTH, writes=["comment", "add_label", "create_issue"])
        self.assertIn("not an authorized write", self.send(self.port(auth=no_kind, carrier=Carrier())))
        self.assertIn("last 24 hours", self.send(self.port(carrier=Carrier(), recent=50)))
        self.assertEqual(self.send(self.port(carrier=Carrier(), recent=49)), "SENT")
        self.assertIn("no carrier", self.send(self.port()))
        with self.assertRaises(st.PreparedOnly):
            self.send(self.port(auth=None, carrier=Carrier()))

    def test_push_outcomes(self):
        self.assertEqual(self.send(self.port(carrier=Carrier(RuntimeError("create-only conflict: path exists")))),
                         "SENT")
        self.assertTrue(self.send(self.port(carrier=Carrier(RuntimeError(
            f"branch {ghs.CARRIER_BRANCH} does not exist")))).startswith("NOT_SENT"))
        with self.assertRaises(st.WriteOutcomeUnknown):
            self.send(self.port(carrier=Carrier(RuntimeError("push failed"))))


if __name__ == "__main__":
    unittest.main()


class HelperAndKeyScopeTests(unittest.TestCase):
    """The port builds requests only through Jules' helpers; the key is read only inside the jules-api
    environment, whose deployment-branch rule the owner sets (docs/CLAUDE_JULES_API_ROUTE_V1.md)."""

    def test_helpers_accept_only_ascii_ids_without_trailing_newline(self):
        from automation.command_bus.claude_jules_api_message import message_request_path, validate_message_request
        from automation.command_bus.claude_jules_api_session_link import session_id_of_pr
        self.assertIsNone(session_id_of_pr("https://jules.google.com/task/²"))
        self.assertIsNone(session_id_of_pr("https://jules.google.com/task/١٢"))
        self.assertEqual(session_id_of_pr(PR_BODY), SESSION)
        with self.assertRaises(ValueError):
            message_request_path("abc\n")
        self.assertTrue(validate_message_request({"session_id": "12\n", "expected_state": "COMPLETED",
                                                  "prompt": "x"}))

    def test_every_job_that_reads_the_key_runs_in_the_jules_api_environment(self):
        import re
        from pathlib import Path
        found = 0
        for path in sorted((Path(__file__).resolve().parents[3] / ".github" / "workflows").glob("*.yml")):
            text = path.read_text(encoding="utf-8").replace("\r\n", "\n")
            if "jobs:\n" not in text:
                continue
            jobs = re.split(r"\n(?=  [A-Za-z0-9_-]+:\n)", text.split("jobs:\n", 1)[1])
            for job in jobs:
                if "JULES_API_KEY" in job and "secrets." in job:
                    found += 1
                    self.assertIn("\n    environment: jules-api\n", job, f"{path.name}: {job.split(chr(10))[0]}")
        self.assertGreaterEqual(found, 7)


class DeliveryReadbackTests(unittest.TestCase):
    """2026-10-13, task #392: the message workflow refused to send (Jules was IN_PROGRESS), yet the request file
    counted as sent and the task went to the takeover.  Now only a delivered message counts; a refused one is
    followed by a new request id (never a resend of an unknown outcome), at most three per round."""

    task = {"task_id": "prod-c1-389cd7ecac", "issue": 392}

    class Port:
        def __init__(self, attempts):
            self.attempts, self.sent = attempts, []

        def api_message_attempt(self, rid):
            return self.attempts.get(rid)

        def api_message(self, rid, **kw):
            self.sent.append(rid)
            return "SENT"

    def run_(self, attempts):
        port = self.Port(attempts)
        out = loop._resend_corrective(port, self.task, RECEIPT, head=H2, now=NOW, ack_minutes=60)
        return out, port.sent

    def test_a_refused_delivery_is_followed_by_a_new_request(self):
        base = "prod-c1-389cd7ecac-r1-msg"
        (code, _, human), sent = self.run_({base: {"at": "2026-10-10T15:00:00Z", "result": "FAILED"}})
        self.assertEqual((code, human, sent), ("JULES_IGNORED_CORRECTIVE", False, [base + "-a2"]))

    def test_pending_waits_and_delivered_counts(self):
        base = "prod-c1-389cd7ecac-r1-msg"
        (code, reason, _), sent = self.run_({base: {"at": "2026-10-10T15:00:00Z", "result": "PENDING"}})
        self.assertEqual((code, sent), ("JULES_IGNORED_CORRECTIVE", []))
        self.assertIn("still being delivered", reason)
        (code, _, _), sent = self.run_({base: {"at": "2026-10-10T15:05:00Z", "result": "SENT"}})
        self.assertEqual((code, sent), ("JULES_IGNORED_CORRECTIVE", []))

    def test_three_refused_deliveries_go_to_the_takeover_path(self):
        base = "prod-c1-389cd7ecac-r1-msg"
        failed = {"at": "2026-10-10T15:00:00Z", "result": "FAILED"}
        (code, _, human), sent = self.run_({base: failed, base + "-a2": failed, base + "-a3": failed})
        self.assertEqual((code, human, sent), ("JULES_RESEND_REFUSED", True, []))

    def test_port_reads_the_workflow_outcome_of_the_request_commit(self):
        sha = "e" * 40
        calls = []

        def get(path):
            calls.append(path)
            tail = path.split(f"repos/{REPO}/", 1)[1]
            if tail.startswith("commits?"):
                return [{"sha": sha, "commit": {"committer": {"date": NOW}}}] if "-r1-msg.json" in tail else []
            if tail.startswith("actions/runs?head_sha="):
                return {"workflow_runs": [{"name": ghs.MESSAGE_WORKFLOW, "status": "completed",
                                           "conclusion": "failure"}]}
            raise AssertionError(path)
        port = ghs.GhLoopPort(get, repo=REPO, campaign=CAMPAIGN, route_declaration={}, signals=[])
        self.assertEqual(port.api_message_attempt("x-r1-msg"), {"at": NOW, "result": "FAILED"})
        self.assertIsNone(port.api_message_attempt("x-r1-msg-a2"))
        self.assertIn(f"actions/runs?head_sha={sha}", calls[1])
