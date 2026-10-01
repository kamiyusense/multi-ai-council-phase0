"""Stage 6/7 production adapters against a real git remote (a local bare repo).

No network, Jules or GitHub call: the remote is a temporary bare repository and
the repository-scoped REST reads (PRs, workflow runs, job logs) are stubbed.
Everything else (fetch, single-file commits, non-force pushes, ref readback,
compare, worktree test runs) is the real production code path.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
import unittest
from datetime import datetime

from automation.command_bus.claude_jules_autoloop import ClaudeJulesAutoLoop
from automation.command_bus.claude_jules_dispatch import command_path, dispatch_receipt_path
from automation.command_bus.claude_jules_live import (
    LiveResultFacts, build_review, poll_results, review_path,
)
from automation.command_bus.claude_jules_live_adapter import GitLiveClient, PushRejected
from automation.command_bus.claude_jules_live_budget import LOOP_A_LIVE_BUDGET, LiveBudgetLedger, slot_path
from automation.command_bus.claude_jules_dispatch import canonical_json, sha256_of
from automation.command_bus.jules_carrier_current import jules_api_request as carrier_request
from automation.command_bus.jules_carrier_current import loop_id_claim as carrier_claim
from automation.command_bus.loop_owner_backend import LoopOwnerGitHubBackend, owner_event_path
from automation.command_bus.tests.claude_jules_autoloop_fakes import (
    CARRIER, DATA, LOOP, NOW, REPO, TARGET, owner_event, policy, roadmap, task_spec,
)

GOOD = "import unittest\nfrom automation.command_bus.alpha import helper\n\n\nclass T(unittest.TestCase):\n    def test_x(self):\n        self.assertEqual(helper(1), 2)\n"
FAKE_TESTS = ["python3", "-c", "import sys; sys.stderr.write('...\\nRan 7 tests in 0.01s\\n\\nOK\\n')"]


def git(cwd, *args, env=None):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env=env).stdout.strip()


class Remote:
    """A bare 'origin' plus a working clone used by the adapter."""

    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="claude-live-adapter-")
        self.bare = os.path.join(self.root, "origin.git")
        self.clone = os.path.join(self.root, "clone")
        git(self.root, "init", "--bare", "-q", "-b", "main", self.bare)
        seed = os.path.join(self.root, "seed")
        git(self.root, "init", "-q", "-b", "main", seed)
        with open(os.path.join(seed, "README.md"), "w") as handle:
            handle.write("root\n")
        env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@e", GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@e")
        git(seed, "add", "README.md")
        git(seed, "commit", "-q", "-m", "root", env=env)
        git(seed, "remote", "add", "origin", self.bare)
        for branch in ("main", TARGET, CARRIER, DATA):
            git(seed, "push", "-q", "origin", f"HEAD:refs/heads/{branch}")
        git(self.root, "clone", "-q", self.bare, self.clone)
        self.seed, self.env = seed, env
        self.client = GitLiveClient(self.clone, tip_ttl_seconds=0)

    def head(self, branch):
        out = git(self.root, "--git-dir", self.bare, "rev-parse", f"refs/heads/{branch}")
        return out

    def outside_commit(self, branch, path, text, message="outside"):
        """Another controller pushing to the same branch (separate clone)."""
        other = os.path.join(self.root, f"other-{message.replace(' ', '-')}")
        if not os.path.isdir(other):
            git(self.root, "clone", "-q", self.bare, other)
        git(other, "fetch", "-q", "origin")
        git(other, "checkout", "-q", "-B", "w", f"origin/{branch}")
        os.makedirs(os.path.dirname(os.path.join(other, path)) or other, exist_ok=True)
        with open(os.path.join(other, path), "w") as handle:
            handle.write(text)
        git(other, "add", path)
        git(other, "commit", "-q", "-m", message, env=self.env)
        git(other, "push", "-q", "origin", f"w:refs/heads/{branch}")
        return git(other, "rev-parse", "HEAD")

    def close(self):
        shutil.rmtree(self.root, ignore_errors=True)


class StubRest:
    """Repository-scoped REST reads with the real response shapes."""

    def __init__(self):
        self.prs: dict[int, dict] = {}
        self.runs: dict[str, dict] = {}
        self.logs: dict[int, str] = {}

    def pulls_for_base(self, base):
        return [p for p in self.prs.values() if p["base"]["ref"] == base]

    def pull(self, number):
        return self.prs.get(number)

    def workflow_runs_for_commit(self, workflow, sha):
        return [self.runs[sha]] if sha in self.runs else []

    def run_jobs(self, run_id):
        return [{"id": run_id * 10}]

    def job_log(self, job_id):
        return self.logs.get(job_id)


class GitLiveClientTests(unittest.TestCase):
    def setUp(self):
        self.remote = Remote()
        self.c = self.remote.client

    def tearDown(self):
        self.remote.close()

    def test_create_is_single_file_create_only_and_read_back(self):
        before = self.remote.head(DATA)
        created = self.c.create("automation/command_bus/evidence/x/a.json", '{"a":1}', "add a", DATA)
        after = self.remote.head(DATA)
        self.assertEqual(git(self.remote.root, "--git-dir", self.remote.bare, "rev-parse", f"{after}^"), before)
        changed = git(self.remote.root, "--git-dir", self.remote.bare, "diff-tree", "--no-commit-id", "--name-status", "-r", after)
        self.assertEqual(changed.split(), ["A", "automation/command_bus/evidence/x/a.json"])
        self.assertEqual(self.c.get(created.path, DATA).text, '{"a":1}')
        self.assertEqual([x.path for x in self.c.list("automation/command_bus/evidence/", DATA)], [created.path])
        with self.assertRaisesRegex(RuntimeError, "create-only"):
            self.c.create(created.path, '{"a":2}', "again", DATA)
        self.assertEqual(self.c.get(created.path, DATA).text, '{"a":1}')
        self.assertIsNone(self.c.get("missing.json", DATA))
        self.assertIsNone(self.c.get("x.json", "no-such-branch"))

    def test_remote_moved_push_is_rebuilt_on_new_tip_without_losing_their_commit(self):
        self.c.get("README.md", DATA)  # warm the tip cache
        self.c.tip_ttl = 3600
        theirs = self.remote.outside_commit(DATA, "theirs.txt", "x")
        self.c.create("mine.json", "{}", "mine", DATA)
        head = self.remote.head(DATA)
        self.assertEqual(git(self.remote.root, "--git-dir", self.remote.bare, "rev-parse", f"{head}^"), theirs)

    def test_rejected_push_never_forces(self):
        old = self.remote.head(TARGET)
        moved = self.remote.outside_commit(TARGET, "t.txt", "1", "target moved")
        with self.assertRaises(RuntimeError):
            self.c.fast_forward_branch(TARGET, old, old)
        sibling = self.remote.outside_commit("main", "s.txt", "2", "sibling")
        with self.assertRaises(RuntimeError):
            self.c.fast_forward_branch(TARGET, moved, sibling)  # not a descendant -> refused before push
        with self.assertRaises(PushRejected):
            self.c._push(sibling, TARGET)  # even a raw push is rejected by git (non-fast-forward)
        self.assertEqual(self.remote.head(TARGET), moved)

    def test_refs_compare_and_branch_creation(self):
        base = self.remote.head(TARGET)
        self.assertEqual(self.c.get_branch_head(TARGET), base)
        self.assertIsNone(self.c.get_branch_head("jules-work/none"))
        self.c.create_branch("jules-work/relay-dev-loop-001-x", base)
        self.assertEqual(self.remote.head("jules-work/relay-dev-loop-001-x"), base)
        with self.assertRaisesRegex(RuntimeError, "ref exists"):
            self.c.create_branch("jules-work/relay-dev-loop-001-x", base)
        child = self.remote.outside_commit("jules-work/relay-dev-loop-001-x", "automation/command_bus/alpha.py", "x")
        compare = self.c.compare(base, child)
        self.assertEqual((compare["merge_base"], compare["ahead_by"], compare["behind_by"]), (base, 1, 0))
        self.assertEqual(compare["files"], [{"path": "automation/command_bus/alpha.py", "status": "added"}])
        self.assertEqual(self.c.get_commit_tree(child), git(self.remote.clone, "rev-parse", f"{child}^{{tree}}"))
        self.assertIsNone(self.c.get_commit_tree("0" * 40))
        self.c.fast_forward_branch(TARGET, base, child)
        self.assertEqual(self.remote.head(TARGET), child)

    def test_unsafe_names_are_refused(self):
        for bad in ("../x", "a/../b", "-rf"):
            with self.assertRaises(ValueError):
                self.c.get(bad, DATA)
        with self.assertRaises(ValueError):
            self.c.get_branch_head("refs/../x")


class BudgetLedgerTests(unittest.TestCase):
    def setUp(self):
        self.remote = Remote()
        self.ledger = LiveBudgetLedger(self.remote.client, data_branch=DATA)

    def tearDown(self):
        self.remote.close()

    def acquire(self, n, intent="i" * 64):
        return self.ledger.acquire(command_id=f"relay-dev-loop-{n:03d}-x", intent_sha256=intent,
                                   origin_loop_id=LOOP, acquired_at=NOW)

    def test_cap_is_fixed_slots_are_sequential_and_never_released(self):
        with self.assertRaises(ValueError):
            LiveBudgetLedger(self.remote.client, data_branch=DATA, cap=11)
        for n in range(1, LOOP_A_LIVE_BUDGET + 1):
            self.assertEqual(self.acquire(n).status, "ACQUIRED")
        self.assertEqual(self.acquire(3).status, "RECOVERED")
        self.assertEqual(self.acquire(3, intent="j" * 64).status, "COLLISION")
        exhausted = self.acquire(11)
        self.assertEqual(exhausted.status, "EXHAUSTED")
        self.assertEqual(self.ledger.used(), LOOP_A_LIVE_BUDGET)

    def test_slot_race_loser_takes_next_slot_and_tampering_is_unknown(self):
        winner = {"schema_version": 1, "profile": "CLAUDE_AUTO_LIVE_BUDGET_SLOT_V1", "slot": 1, "cap": 10,
                  "command_id": "relay-dev-loop-900-other", "intent_sha256": "k" * 64, "origin_loop_id": "other",
                  "acquired_at": NOW, "counts_as_used": True, "retry_count": 0}
        winner["slot_sha256"] = sha256_of(winner)
        real_get, raced = self.remote.client.get, []

        def racing_get(path, ref):
            if path == slot_path(1) and not raced:
                raced.append(True)  # another controller creates slot 1 between our read and our create
                self.remote.outside_commit(DATA, slot_path(1), canonical_json(winner), "race winner")
                return None
            return real_get(path, ref)
        self.remote.client.get = racing_get
        result = self.acquire(1)
        self.assertEqual((result.status, result.record["slot"]), ("ACQUIRED", 2))
        self.remote.client.get = real_get
        self.remote.outside_commit(DATA, slot_path(3), json.dumps(dict(winner, slot=3)), "tampered")
        self.assertEqual(self.acquire(5).status, "UNKNOWN")


class LiveControllerIntegrationTests(unittest.TestCase):
    """The unchanged controller, end to end, on real git + stubbed REST reads."""

    def setUp(self):
        self.remote = Remote()
        self.c = self.remote.client
        self.rest = StubRest()
        self.scratch = tempfile.mkdtemp(prefix="claude-live-scratch-")
        self.policy = policy()
        self.c.create(owner_event_path(LOOP, 1), json.dumps(owner_event()), "owner", DATA)
        self.facts = LiveResultFacts(git=self.c, rest=self.rest, policy=self.policy, scratch_dir=self.scratch,
                                     test_command=FAKE_TESTS)

    def tearDown(self):
        self.remote.close()
        shutil.rmtree(self.scratch, ignore_errors=True)

    def loop(self):
        return ClaudeJulesAutoLoop(client=self.c, refs=self.c, policy=self.policy,
                                   owner_reader=LoopOwnerGitHubBackend(self.c, branch=DATA),
                                   roadmap=roadmap(task_spec("alpha-helper")), facts=self.facts,
                                   origin_loop_id=LOOP, lane_id="J-BLUE")

    def simulate_carrier_and_jules(self, command_id, session="777001", text="def helper(x):\n    return x + 1\n"):
        """What the real workflow + Jules do: a run on the command commit, a session branch and a PR."""
        [commit] = self.c.added_by(CARRIER, command_path(command_id))
        self.rest.runs[commit] = {"id": 41, "event": "push", "status": "completed", "conclusion": "success"}
        self.rest.logs[410] = f"... Jules session accepted: sessions/{session}\n"
        work = f"jules-work/{command_id}"
        self.remote.outside_commit(f"{work}-{session}" if False else work, "automation/command_bus/alpha.py", text, "jules")
        head = self.remote.head(work)
        # Jules publishes from its own session branch; the work branch itself stays at the snapshot.
        git(self.remote.root, "--git-dir", self.remote.bare, "update-ref", f"refs/heads/{work}-{session}", head)
        git(self.remote.root, "--git-dir", self.remote.bare, "update-ref", f"refs/heads/{work}", f"{head}^")
        self.c.invalidate()
        repo = {"full_name": REPO}
        self.rest.prs[501] = {"number": 501, "state": "open", "merged": False, "merged_at": None,
                              "body": f"x\n*PR created automatically by Jules for task [{session}](https://jules.google.com/task/{session}) started*",
                              "base": {"ref": work, "repo": repo}, "head": {"ref": f"{work}-{session}", "sha": head, "repo": repo}}
        return head

    def test_dispatch_poll_review_inspect_adopt_on_real_git(self):
        first = self.loop().step(now=NOW)
        self.assertEqual((first.action, first.status), ("DISPATCH", "DISPATCHED"), first.reason)
        command_id = first.details["command_id"]
        # Carrier: claim and command each arrived as their own single-file commit.
        request = json.loads(self.c.get(command_path(command_id), CARRIER).text)
        carrier_request.validate_request(request, now=datetime.fromisoformat(NOW))
        claim = json.loads(self.c.get(f"automation/command_bus/loop_id_claims/{command_id.split('-')[3]}.json", CARRIER).text)
        carrier_claim.verify_command_claim(request, claim)
        log = git(self.remote.root, "--git-dir", self.remote.bare, "log", "--format=%H", f"refs/heads/{CARRIER}")
        for sha in log.split()[:-1]:
            names = git(self.remote.root, "--git-dir", self.remote.bare, "diff-tree", "--no-commit-id", "--name-status", "-r", sha).split()
            self.assertEqual(len(names), 2, names)  # exactly one added file per carrier commit
            self.assertEqual(names[0], "A")
        self.assertEqual(self.remote.head(request["work_branch"]), request["expected_target_head"])
        self.assertEqual(LiveBudgetLedger(self.c, data_branch=DATA).used(), 1)
        self.assertEqual(self.loop().step(now=NOW).status, "WAITING_FOR_RESULT")

        head = self.simulate_carrier_and_jules(command_id)
        polled = poll_results(git=self.c, rest=self.rest, policy=self.policy, origin_loop_id=LOOP)
        self.assertEqual([p["inbox"] for p in polled], ["RECORDED"])
        self.assertEqual([p["inbox"] for p in poll_results(git=self.c, rest=self.rest, policy=self.policy,
                                                           origin_loop_id=LOOP)], ["DUPLICATE"])
        waiting = self.loop().step(now=NOW)
        self.assertEqual(waiting.status, "AWAITING_CLAUDE_REVIEW", waiting.reason)

        tree = self.c.get_commit_tree(head)
        obs = {n: {"result": "PASS", "evidence": "read in diff"} for n in
               task_spec()["acceptance_checks"] + ["negative_cases_exercised", "regression_suite_reviewed"]}
        # Claude's review found that the required test file is missing: its finding decides, not Jules' PR.
        gap = [{"category": "semantic_gap", "detail": "test_alpha.py was not added"}]
        review = build_review(command_id=command_id, head=head, tree=tree, observations=obs, findings=gap,
                              summary="missing test", reviewed_at=NOW)
        self.c.create(review_path(command_id, head), canonical_json(review), "review", DATA)
        inspected = self.loop().step(now=NOW)
        self.assertEqual((inspected.action, inspected.status, inspected.details["decision"]),
                         ("INSPECT", "FAIL_MAJOR", "JULES_CORRECTIVE"), inspected.reason)
        # A tampered review (digest no longer matches) stops instead of being trusted.
        bad = dict(review, findings=[])
        with self.assertRaises(ValueError):
            from automation.command_bus.claude_jules_live import validate_review
            validate_review(bad)

    def test_full_pass_and_adoption_with_real_fast_forward(self):
        first = self.loop().step(now=NOW)
        command_id = first.details["command_id"]
        [commit] = self.c.added_by(CARRIER, command_path(command_id))
        self.rest.runs[commit] = {"id": 41, "event": "push", "status": "completed", "conclusion": "success"}
        self.rest.logs[410] = "Jules session accepted: sessions/777001\n"
        work = f"jules-work/{command_id}"
        other = os.path.join(self.remote.root, "jules")
        git(self.remote.root, "clone", "-q", self.remote.bare, other)
        git(other, "checkout", "-q", "-B", "s", f"origin/{work}")
        os.makedirs(os.path.join(other, "automation/command_bus/tests"), exist_ok=True)
        with open(os.path.join(other, "automation/command_bus/alpha.py"), "w") as h:
            h.write("def helper(x):\n    return x + 1\n")
        with open(os.path.join(other, "automation/command_bus/tests/test_alpha.py"), "w") as h:
            h.write(GOOD)
        git(other, "add", "-A")
        git(other, "commit", "-q", "-m", "jules", env=self.remote.env)
        git(other, "push", "-q", "origin", f"s:refs/heads/{work}-777001")
        head = git(other, "rev-parse", "HEAD")
        repo = {"full_name": REPO}
        self.rest.prs[502] = {"number": 502, "state": "open", "merged": False, "merged_at": None,
                              "body": "*PR created automatically by Jules for task [777001](https://jules.google.com/task/777001) started*",
                              "base": {"ref": work, "repo": repo}, "head": {"ref": f"{work}-777001", "sha": head, "repo": repo}}
        poll_results(git=self.c, rest=self.rest, policy=self.policy, origin_loop_id=LOOP)
        obs = {n: {"result": "PASS", "evidence": "asserted in test_alpha"} for n in
               task_spec()["acceptance_checks"] + ["negative_cases_exercised", "regression_suite_reviewed"]}
        review = build_review(command_id=command_id, head=head, tree=self.c.get_commit_tree(head),
                              observations=obs, findings=[], summary="ok", reviewed_at=NOW)
        self.c.create(review_path(command_id, head), canonical_json(review), "review", DATA)
        inspected = self.loop().step(now=NOW)
        self.assertEqual((inspected.action, inspected.status), ("INSPECT", "PASS"), inspected.reason)
        adopted = self.loop().step(now=NOW)
        self.assertEqual((adopted.action, adopted.status), ("ADOPT", "ADOPTED"), adopted.reason)
        self.assertEqual(self.remote.head(TARGET), head)
        done = self.loop().step(now=NOW)
        self.assertEqual((done.action, done.status), ("COMPLETE", "COMPLETE"))

    def test_budget_exhaustion_blocks_before_any_carrier_write(self):
        ledger = LiveBudgetLedger(self.c, data_branch=DATA)
        for n in range(1, LOOP_A_LIVE_BUDGET + 1):
            ledger.acquire(command_id=f"relay-dev-loop-{900 + n}-x", intent_sha256="i" * 64,
                           origin_loop_id="earlier-origin", acquired_at=NOW)
        carrier_before = self.remote.head(CARRIER)
        result = self.loop().step(now=NOW)
        self.assertEqual((result.action, result.status), ("STOP", "PREPARED_NOT_AUTHORIZED"), result.reason)
        self.assertIn("LIVE budget exhausted", result.reason)
        self.assertEqual(self.remote.head(CARRIER), carrier_before)

    def test_unreachable_job_log_uses_only_a_bound_recorded_observation(self):
        from automation.command_bus.claude_jules_live import build_observation, observation_path
        first = self.loop().step(now=NOW)
        command_id = first.details["command_id"]
        [commit] = self.c.added_by(CARRIER, command_path(command_id))
        self.rest.runs[commit] = {"id": 41, "event": "push", "status": "completed", "conclusion": "success"}

        def blocked(job_id):
            raise RuntimeError("Tunnel connection failed: 403")
        self.rest.job_log = blocked
        self.assertIsNone(self.facts.dispatch_observation(command_id)["session_id"])
        wrong = build_observation(command_id=command_id, workflow_run_id="99", job_id="410",
                                  log_line="Jules session accepted: sessions/777001", observed_at=NOW)
        self.c.create(observation_path(command_id), canonical_json(wrong), "obs", DATA)
        with self.assertRaisesRegex(ValueError, "does not bind"):
            self.facts.dispatch_observation(command_id)
        with self.assertRaises(ValueError):
            build_observation(command_id=command_id, workflow_run_id="41", job_id="410",
                              log_line="no session here", observed_at=NOW)

    def test_bound_recorded_observation_supplies_session(self):
        from automation.command_bus.claude_jules_live import build_observation, observation_path
        command_id = self.loop().step(now=NOW).details["command_id"]
        [commit] = self.c.added_by(CARRIER, command_path(command_id))
        self.rest.runs[commit] = {"id": 41, "event": "push", "status": "completed", "conclusion": "success"}
        self.rest.job_log = lambda job_id: (_ for _ in ()).throw(RuntimeError("blocked"))
        good = build_observation(command_id=command_id, workflow_run_id="41", job_id="410",
                                 log_line="2026 Jules session accepted: sessions/777001", observed_at=NOW)
        self.c.create(observation_path(command_id), canonical_json(good), "obs", DATA)
        self.assertEqual(self.facts.dispatch_observation(command_id)["session_id"], "777001")

    def test_tests_run_on_exact_head_in_isolated_worktree(self):
        head = self.remote.head(TARGET)
        evidence = self.facts.run_tests(head)
        self.assertEqual((evidence["head_sha"], evidence["tests_run"], evidence["exit_code"]), (head, 7, 0))
        crash = LiveResultFacts(git=self.c, rest=self.rest, policy=self.policy, scratch_dir=self.scratch,
                                test_command=["python3", "-c", "raise SystemExit(3)"]).run_tests(head)
        self.assertEqual((crash["exit_code"], crash["errors"]), (3, 1))
        self.assertIsNone(self.facts.run_tests("0" * 40))
        self.assertEqual(git(self.remote.clone, "worktree", "list").count("\n"), 0)

    def test_no_result_pr_times_out_fail_closed(self):
        first = self.loop().step(now=NOW)
        self.assertEqual(first.status, "DISPATCHED")
        late = self.loop().step(now="2026-10-01T19:30:00+00:00")
        self.assertEqual((late.action, late.status), ("STOP", "NO_RESULT_TIMEOUT"))
        self.assertIsNotNone(self.c.get(dispatch_receipt_path(first.details["command_id"]), DATA))


if __name__ == "__main__":
    unittest.main()
