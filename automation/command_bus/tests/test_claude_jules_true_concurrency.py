"""Two controllers on two threads that have BOTH read the same snapshot before either writes.

Unlike the interleaved tests (one controller finishes a step before the other
starts), a barrier holds each thread at its first mutating GitHub call until the
other thread has reached its own, so both act on the same stale view.  The
fake's create-only/compare-and-swap semantics stand in for GitHub's (a create
of an existing path fails; a fast-forward with a wrong expected head fails).

What this proves: with the production write primitives, a real race on the
dispatch point and on the adoption point yields one provider dispatch, one
budget slot and one adoption.  What it does not prove: GitHub's own atomicity
under load, or Routine-level concurrency; those stay LIVE questions.
"""
from __future__ import annotations

import threading
import unittest

from automation.command_bus.tests.claude_jules_autoloop_fakes import NOW, TARGET, roadmap, task_spec
from automation.command_bus.tests.test_claude_jules_autoloop_e2e import World

MUTATING = ("create", "update", "fast_forward_branch", "create_branch")


def race(w, *, rounds=1):
    """Run ``rounds`` steps on two fresh controllers per thread, barrier at the first mutation of each step."""
    lock = threading.RLock()
    barrier = threading.Barrier(2, timeout=5)
    local = threading.local()
    met_together: list[str] = []
    originals = {name: getattr(w.github, name) for name in ("get", "list", *MUTATING)}

    def guarded(name):
        real = originals[name]

        def call(*args, **kwargs):
            if name in MUTATING and not getattr(local, "met", False):
                local.met = True
                try:
                    barrier.wait()  # both threads have read their snapshot by now
                    met_together.append(name)
                except threading.BrokenBarrierError:
                    pass  # the other thread finished its step without writing
            with lock:
                return real(*args, **kwargs)
        return call

    for name in originals:
        setattr(w.github, name, guarded(name))
    outcomes: dict[str, list] = {"a": [], "b": []}
    errors: list[BaseException] = []

    def worker(key):
        try:
            for _ in range(rounds):
                local.met = False
                outcomes[key].append(w.controller().step(now=NOW))
                try:
                    barrier.wait() if not local.met else None
                except threading.BrokenBarrierError:
                    pass
        except BaseException as exc:  # surfaced to the test
            errors.append(exc)
            barrier.abort()

    threads = [threading.Thread(target=worker, args=(k,)) for k in outcomes]
    for t in threads:
        t.start()
    for t in threads:
        t.join(20)
    barrier.abort()
    for name, real in originals.items():
        setattr(w.github, name, real)
    if errors:
        raise errors[0]
    race.met_together = met_together
    return outcomes["a"] + outcomes["b"]


class TrueConcurrencyTests(unittest.TestCase):
    def test_racing_first_dispatch_creates_one_command_and_one_slot(self):
        for _ in range(5):  # repeat: thread scheduling differs per run
            w = World(plan=roadmap(task_spec()))
            results = race(w)
            self.assertEqual(len(race.met_together), 2)  # both threads were held at a write with the same view
            self.assertEqual(len(w.commands()), 1, [r.status for r in results])
            self.assertEqual(len(w.controller().dispatcher.budget.slots()), 1)
            self.assertLessEqual(sum(r.status == "DISPATCHED" for r in results), 2)
            for r in results:
                self.assertIn(r.status, {"DISPATCHED", "NO-OP", "UNKNOWN", "WAITING_FOR_RESULT", "CARRIER_BUSY"},
                              r.reason)
            # whatever each thread saw, a later fresh wake agrees on one in-flight command
            self.assertEqual(w.step().status, "WAITING_FOR_RESULT")
            self.assertEqual(len(w.commands()), 1)

    def test_racing_adoption_fast_forwards_once(self):
        for _ in range(5):
            w = World(plan=roadmap(task_spec()))
            w.deliver(w.jules.run(w.step().details["command_id"]))
            self.assertEqual(w.step().status, "PASS")
            before = w.github.branches[TARGET]
            results = race(w)
            self.assertEqual(len(race.met_together), 2)
            ffs = [x for x in w.github.writes if x[0] == "ff" and x[1] == TARGET]
            self.assertEqual(len(ffs), 1, [r.status for r in results])
            self.assertNotEqual(w.github.branches[TARGET], before)
            for r in results:
                self.assertIn(r.status, {"ADOPTED", "NO-OP", "UNKNOWN", "COMPLETE"}, r.reason)
            final = w.controller().run_until_boundary(now=NOW)
            self.assertEqual(final[-1].status, "COMPLETE")
            self.assertEqual(len(w.commands()), 1)

    def test_racing_wakes_while_waiting_write_nothing(self):
        w = World(plan=roadmap(task_spec()))
        w.step()
        writes = list(w.github.writes)
        results = race(w, rounds=3)
        self.assertTrue(all(r.status == "WAITING_FOR_RESULT" for r in results))
        self.assertEqual(w.github.writes, writes)


if __name__ == "__main__":
    unittest.main()
