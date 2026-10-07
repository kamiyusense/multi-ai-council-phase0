"""Mock transport/fault tests for GitHub event -> wake -> poll -> durable restore.

Everything is a local fake: no network, no Jules, no Routine, no LIVE. The real
``poll_results`` and ``wake_resume`` run against the e2e World so the webhook
path and the poll path meet in the same create-only inbox.
"""
from __future__ import annotations

import copy
import unittest

from automation.command_bus.claude_jules_live import outstanding_dispatches, poll_results, wake_resume
from automation.command_bus.claude_jules_result_event import ResultEventInbox
from automation.command_bus.tests.test_claude_jules_autoloop_e2e import World
from automation.command_bus.tests.claude_jules_autoloop_fakes import DATA, LOOP, NOW, TARGET, REPO, roadmap, task_spec

EVENTS = "automation/command_bus/evidence/claude-auto-result-events/"


class FakeRest:
    """REST view of FakeJules' PRs, as GitHubRestReader.pulls_for_base returns them."""

    def __init__(self, jules, *, fail_after: int | None = None):
        self.jules, self.fail_after, self.calls = jules, fail_after, 0

    def pulls_for_base(self, base):
        self.calls += 1
        if self.fail_after is not None and self.calls > self.fail_after:
            raise OSError("GitHub read failed mid-poll")
        repo = {"full_name": REPO}
        return [{"number": pr["number"], "state": pr["state"], "merged": pr["merged"], "body": pr["body"],
                 "base": {"ref": pr["base_ref"], "repo": repo},
                 "head": {"ref": pr["head_ref"], "sha": pr["head_sha"], "repo": repo}}
                for pr in self.jules.prs.values() if pr["base_ref"] == base and pr["state"] == "open"]


def events(w):
    return [c.path for c in w.github.list(EVENTS, DATA)]


def wake(w, rest=None, **kw):
    return wake_resume(loop=w.controller(), git=w.github, rest=rest or FakeRest(w.jules), policy=w.policy,
                       origin_loop_id=LOOP, now=NOW, **kw)


class WakeTransportTests(unittest.TestCase):
    def test_webhook_then_poll_of_same_head_is_one_durable_result(self):
        w = World(plan=roadmap(task_spec()))
        command = w.step().details["command_id"]
        payload = w.jules.run(command)
        self.assertEqual(w.deliver(payload, delivery="webhook-1").status, "RECORDED")
        before = list(w.github.writes)
        polled = poll_results(git=w.github, rest=FakeRest(w.jules), policy=w.policy, origin_loop_id=LOOP)
        self.assertEqual([p["inbox"] for p in polled], ["DUPLICATE"])
        self.assertEqual(w.github.writes, before)  # duplicate poll writes nothing
        self.assertEqual(len(events(w)), 1)

    def test_poll_only_wake_restores_and_finishes_without_any_webhook(self):
        w = World(plan=roadmap(task_spec()))
        w.jules.run(w.step().details["command_id"])  # PR exists, webhook lost
        result = wake(w)
        self.assertIsNone(result["poll_error"])
        self.assertEqual([s["status"] for s in result["steps"]], ["PASS", "ADOPTED", "COMPLETE"])
        again = wake(w)
        self.assertEqual([s["status"] for s in again["steps"]], ["COMPLETE"])
        self.assertEqual(again["poll"], [])  # adopted dispatch is no longer outstanding

    def test_late_event_for_an_older_head_never_wins_over_the_newer_head(self):
        w = World(plan=roadmap(task_spec()))
        command = w.step().details["command_id"]
        opened = w.jules.run(command)
        old_head = opened["pull_request"]["head"]["sha"]
        newer = w.jules.push_followup(300, {"automation/command_bus/alpha.py": "def helper(x):\n    return x + 1  # follow-up\n"})
        new_head = newer["pull_request"]["head"]["sha"]
        self.assertEqual(w.deliver(newer, delivery="sync-first").status, "RECORDED")
        self.assertEqual(w.deliver(opened, delivery="opened-late").status, "RECORDED")  # inverted order
        result = wake(w)
        statuses = [s["status"] for s in result["steps"]]
        self.assertIn("ADOPTED", statuses)
        self.assertEqual(w.github.branches[TARGET], new_head)
        self.assertNotEqual(w.github.branches[TARGET], old_head)

    def test_interleaved_controllers_never_double_write_or_double_dispatch(self):
        w = World()
        first = w.step()
        w.deliver(w.jules.run(first.details["command_id"]))
        a, b = w.controller(), w.controller()  # two wakes alive at once
        self.assertEqual(a.step(now=NOW).status, "PASS")
        self.assertEqual(b.step(now=NOW).status, "ADOPTED")
        self.assertEqual(a.step(now=NOW).status, "DISPATCHED")  # next distinct task, once
        self.assertEqual(b.step(now=NOW).status, "WAITING_FOR_RESULT")
        self.assertEqual(len(w.commands()), 2)
        self.assertEqual(len({p.rsplit("/", 1)[-1] for p in w.commands()}), 2)

    def test_duplicate_wakes_while_waiting_write_nothing(self):
        w = World(plan=roadmap(task_spec()))
        w.step()
        writes = list(w.github.writes)
        for _ in range(3):
            result = wake(w)
            self.assertEqual([s["status"] for s in result["steps"]], ["WAITING_FOR_RESULT"])
        self.assertEqual(w.github.writes, writes)

    def test_poll_failing_mid_way_keeps_what_was_recorded_and_does_not_resend(self):
        w = World()
        command = w.step().details["command_id"]
        w.jules.run(command)
        rest = FakeRest(w.jules, fail_after=0)
        result = wake(w, rest=rest)
        self.assertIn("UNKNOWN", result["poll_error"])
        self.assertEqual(events(w), [])
        self.assertEqual([s["status"] for s in result["steps"]], ["WAITING_FOR_RESULT"])
        healed = wake(w)  # next wake: poll works, same durable path
        self.assertIsNone(healed["poll_error"])
        self.assertIn("ADOPTED", [s["status"] for s in healed["steps"]])
        self.assertEqual(len(events(w)), 1)

    def test_ambiguous_inbox_create_is_resolved_by_readback_not_resent(self):
        w = World(plan=roadmap(task_spec()))
        w.jules.run(w.step().details["command_id"])
        real_create = w.github.create
        attempts = []

        def lossy(path, text, message, branch):
            attempts.append(path)
            real_create(path, text, message, branch)
            raise TimeoutError("response lost after write")

        w.github.create = lossy
        try:
            polled = poll_results(git=w.github, rest=FakeRest(w.jules), policy=w.policy, origin_loop_id=LOOP)
        finally:
            w.github.create = real_create
        self.assertEqual([p["inbox"] for p in polled], ["RECORDED"])
        self.assertEqual(len(attempts), 1)

    def test_lost_inbox_write_is_unknown_and_next_wake_records_it_once(self):
        w = World(plan=roadmap(task_spec()))
        w.jules.run(w.step().details["command_id"])
        real_create = w.github.create

        def dropped(path, text, message, branch):
            if path.startswith(EVENTS):
                raise TimeoutError("write never landed")
            return real_create(path, text, message, branch)

        w.github.create = dropped
        try:
            polled = poll_results(git=w.github, rest=FakeRest(w.jules), policy=w.policy, origin_loop_id=LOOP)
        finally:
            w.github.create = real_create
        self.assertEqual([p["inbox"] for p in polled], ["UNKNOWN"])
        self.assertEqual(events(w), [])
        result = wake(w)  # a later independent wake reads GitHub afresh
        self.assertEqual([s["status"] for s in result["steps"]], ["PASS", "ADOPTED", "COMPLETE"])
        self.assertEqual(len(events(w)), 1)

    def test_pr_on_a_foreign_branch_or_closed_pr_is_not_ingested(self):
        w = World(plan=roadmap(task_spec()))
        command = w.step().details["command_id"]
        w.jules.run(command)
        stray = copy.deepcopy(w.jules.prs[300])
        stray.update(number=999, base_ref="jules-work/someone-else")
        w.jules.prs[999] = stray
        w.jules.prs[300]["state"] = "closed"
        polled = poll_results(git=w.github, rest=FakeRest(w.jules), policy=w.policy, origin_loop_id=LOOP)
        self.assertEqual(polled, [])
        self.assertEqual(events(w), [])
        self.assertEqual(len(outstanding_dispatches(w.github, w.policy, LOOP)), 1)

    def test_conflicting_record_for_the_same_result_id_blocks(self):
        w = World(plan=roadmap(task_spec()))
        w.jules.run(w.step().details["command_id"])
        poll_results(git=w.github, rest=FakeRest(w.jules), policy=w.policy, origin_loop_id=LOOP)
        [path] = events(w)
        stored = w.github.json(DATA, path)
        inbox = ResultEventInbox(w.github, data_branch=DATA)
        tampered = dict(stored, head_ref="jules-work/forged")
        self.assertEqual(inbox.record(tampered).status, "BLOCKED")


if __name__ == "__main__":
    unittest.main()
