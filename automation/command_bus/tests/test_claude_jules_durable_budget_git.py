"""Slot reservation through REAL git: a local bare remote, two independent clones, ``GitLiveClient``.

This is the create-only contract the budget relies on (non-force push of a single-file commit on the tip each
controller read; the loser is rejected and its readback shows the winner).  It runs entirely on the local disk:
no GitHub, no network, no model.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
import threading
import unittest
import unittest.mock as m
from pathlib import Path

from automation.command_bus import claude_jules_durable_budget as db
from automation.command_bus.claude_jules_live_adapter import GitLiveClient
from automation.command_bus.tests import budget_fixtures as bf

REPO = "kamiyusense/multi-ai-council-phase0"
ORIGIN = "auth:prod-test:test"


def git(cwd, *args):
    return subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True, text=True,
                          env=dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t", GIT_COMMITTER_NAME="t",
                                   GIT_COMMITTER_EMAIL="t@t", GIT_TERMINAL_PROMPT="0")).stdout.strip()


def act(i):
    return {"repository": REPO, "campaign_id": "prod-test", "issue": 500 + i, "task_id": f"t{i}",
            "correlation_id": f"t{i}-abc", "generation": 1, "task_sha256": "0" * 64,
            "expected_target_head": "a" * 40, "route": "jules-github-app-issue-label"}


class BareRemote:
    def __init__(self, *, proof_slots: int = 9):
        self.tmp = tempfile.TemporaryDirectory()
        root = Path(self.tmp.name)
        self.bare = root / "remote.git"
        git(root, "init", "--bare", "-q", str(self.bare))
        seed = root / "seed"
        git(root, "clone", "-q", str(self.bare), str(seed))
        for i in range(1, proof_slots + 1):           # the real 9/10 proof ledger, untouched by the prod budget
            dst = seed / bf.PREFIX / f"slot-{i:02d}.json"
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text((bf.FIXTURES / f"slot-{i:02d}.json").read_text(encoding="utf-8"), encoding="utf-8")
        (seed / "README").write_text("data branch\n", encoding="utf-8")
        git(seed, "add", "-A")
        git(seed, "commit", "-q", "-m", "seed")
        git(seed, "push", "-q", "origin", f"HEAD:refs/heads/{bf.DATA_BRANCH}")
        self.root = root

    def clone(self, name):
        path = self.root / name
        git(self.root, "clone", "-q", str(self.bare), str(path))
        return GitLiveClient(str(path), tip_ttl_seconds=60.0)    # a long cache: freshness must not depend on it

    def files(self, prefix):
        out = git(self.root, "--git-dir", str(self.bare), "ls-tree", "-r", "--name-only", bf.DATA_BRANCH)
        return sorted(p for p in out.splitlines() if p.startswith(prefix))

    def close(self):
        self.tmp.cleanup()


class GitSlotTests(unittest.TestCase):
    def setUp(self):
        self.remote = BareRemote()
        self.addCleanup(self.remote.close)

    def budget(self, client, **over):
        return db.DurableBudget(client, bf.declaration_v2(**over), repository=REPO)

    def test_sequential_reservations_are_contiguous_and_leave_the_proof_ledger_alone(self):
        b = self.budget(self.remote.clone("a"))
        got = [b.reserve(act(i), origin=ORIGIN, max_for_origin=50, now="t").record["slot"] for i in range(3)]
        self.assertEqual(got, [1, 2, 3])
        self.assertEqual(len(self.remote.files(bf.PREFIX)), 9)          # 9/10 proof ledger unchanged
        self.assertEqual(len(self.remote.files(bf.PROD_PREFIX)), 3)
        again = b.reserve(act(1), origin=ORIGIN, max_for_origin=50, now="later")
        self.assertEqual((again.status, again.record["slot"]), (db.RECOVERED, 2))

    def test_two_clones_race_for_the_same_slot(self):
        a_client, b_client = self.remote.clone("a"), self.remote.clone("b")
        a, b = self.budget(a_client, cap=2), self.budget(b_client, cap=2)
        self.assertEqual(a.reserve(act(0), origin=ORIGIN, max_for_origin=50, now="t").record["slot"], 1)
        barrier = threading.Barrier(2, timeout=30)
        for client in (a_client, b_client):              # both build slot-02 on the same tip, then both push
            original = client._single_file_commit

            def built(*args, _orig=original, **kw):
                commit = _orig(*args, **kw)
                try:
                    barrier.wait()
                except threading.BrokenBarrierError:
                    pass                                 # the loser's rebuild after rejection: no partner left
                return commit
            client._single_file_commit = built
        out = {}
        threads = [threading.Thread(target=lambda k=k, bb=bb, i=i: out.__setitem__(
            k, bb.reserve(act(i), origin=ORIGIN, max_for_origin=50, now="t"))) for k, bb, i in (("a", a, 1),
                                                                                             ("b", b, 2))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        statuses = sorted(r.status for r in out.values())
        self.assertEqual(statuses, [db.ACQUIRED, db.EXHAUSTED])          # cap 2: exactly one winner
        files = self.remote.files(bf.PROD_PREFIX)
        self.assertEqual(len(files), 2)
        winner = [r for r in out.values() if r.status == db.ACQUIRED][0]
        self.assertEqual(winner.record["slot"], 2)
        fresh = self.budget(self.remote.clone("c"), cap=2).slots()
        self.assertEqual([s["command_id"] for s in fresh][1], winner.record["command_id"])

    def test_loser_takes_the_next_slot_when_the_cap_allows(self):
        a_client, b_client = self.remote.clone("a"), self.remote.clone("b")
        a, b = self.budget(a_client), self.budget(b_client)
        barrier = threading.Barrier(2, timeout=30)
        for client in (a_client, b_client):
            original = client._single_file_commit

            def built(*args, _orig=original, **kw):
                commit = _orig(*args, **kw)
                try:
                    barrier.wait()
                except threading.BrokenBarrierError:
                    pass
                return commit
            client._single_file_commit = built
        out = {}
        threads = [threading.Thread(target=lambda k=k, bb=bb, i=i: out.__setitem__(
            k, bb.reserve(act(i), origin=ORIGIN, max_for_origin=50, now="t"))) for k, bb, i in (("a", a, 1),
                                                                                             ("b", b, 2))]
        for t in threads:
            t.start()
        for t in threads:
            t.join(60)
        self.assertEqual({r.status for r in out.values()}, {db.ACQUIRED})
        self.assertEqual(sorted(r.record["slot"] for r in out.values()), [1, 2])
        slots = self.budget(self.remote.clone("c")).slots()
        self.assertEqual(len({s["command_id"] for s in slots}), 2)

    def test_stale_cached_tip_is_never_used_for_the_ledger(self):
        a_client, b_client = self.remote.clone("a"), self.remote.clone("b")
        a, b = self.budget(a_client, cap=1), self.budget(b_client, cap=1)
        self.assertEqual(a.usage()["used"], 0)                           # A caches the tip (ttl 60 s)
        self.assertEqual(b.reserve(act(1), origin=ORIGIN, max_for_origin=5, now="t").status, db.ACQUIRED)
        self.assertEqual(a.usage()["used"], 1)                            # not the cached 0
        r = a.reserve(act(2), origin=ORIGIN, max_for_origin=5, now="t")
        self.assertEqual(r.status, db.EXHAUSTED)                          # fresh read: B's slot is counted
        self.assertEqual(len(self.remote.files(bf.PROD_PREFIX)), 1)

    def test_push_landed_but_response_lost(self):
        client = self.remote.clone("a")
        original = client._push

        def push_then_lose(src, branch):
            original(src, branch)
            raise RuntimeError("push outcome ambiguous: connection reset")
        client._push = push_then_lose
        r = self.budget(client).reserve(act(1), origin=ORIGIN, max_for_origin=5, now="t")
        self.assertEqual(r.status, db.ACQUIRED)                           # readback, not the response, decided
        self.assertEqual(len(self.remote.files(bf.PROD_PREFIX)), 1)

    def test_push_never_landed_is_unknown_then_a_fresh_wake_reserves_once(self):
        client = self.remote.clone("a")
        with m.patch.object(client, "_push", side_effect=RuntimeError("push outcome ambiguous")):
            r = self.budget(client).reserve(act(1), origin=ORIGIN, max_for_origin=5, now="t")
        self.assertEqual(r.status, db.UNKNOWN)
        self.assertEqual(self.remote.files(bf.PROD_PREFIX), [])
        r2 = self.budget(self.remote.clone("b")).reserve(act(1), origin=ORIGIN, max_for_origin=5, now="t2")
        self.assertEqual((r2.status, r2.record["slot"]), (db.ACQUIRED, 1))

    def test_process_killed_after_the_slot_landed_recovers_without_a_second_slot(self):
        client = self.remote.clone("a")
        r = self.budget(client).reserve(act(1), origin=ORIGIN, max_for_origin=5, now="t")
        self.assertEqual(r.status, db.ACQUIRED)
        # the process dies before the label; a brand-new controller (new clone) resumes the same activation
        r2 = self.budget(self.remote.clone("b")).reserve(act(1), origin=ORIGIN, max_for_origin=5, now="t9")
        self.assertEqual((r2.status, r2.record), (db.RECOVERED, r.record))
        self.assertEqual(len(self.remote.files(bf.PROD_PREFIX)), 1)


if __name__ == "__main__":
    unittest.main()
