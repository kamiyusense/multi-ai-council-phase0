"""Re-runs the mock E2E tests and prints what each World actually did (rounds, faults, restarts, duplicates).

    python3 docs/evidence/claude-jules-production-starter-20261009/e2e_stats.py
"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from automation.command_bus import claude_closed_loop_review as review  # noqa: E402
from automation.command_bus.tests import starter_world as sw  # noqa: E402
from automation.command_bus.tests import test_claude_jules_starter_e2e as e2e  # noqa: E402

worlds = []
_init = sw.World.__init__


def _record(self, *a, **k):
    _init(self, *a, **k)
    worlds.append(self)


sw.World.__init__ = _record
stats = {}
for name in ("test_twelve_rounds_with_corrective_restarts_duplicates_and_blocked_isolation",
             "test_quota_exhaustion_pauses_and_reset_resumes", "test_two_independent_campaigns_share_one_concurrency_slot",
             "test_budget_exhausted_task_is_isolated"):
    worlds.clear()
    r = unittest.TextTestRunner(verbosity=0, stream=open("/dev/null", "w")).run(e2e.MultiRoundE2ETests(name))
    stats[name] = {"ok": r.wasSuccessful(), "worlds": []}
    for w in worlds:
        receipts = [rec for n in w.gh.issues for rec in (w.receipts(n) if w.gh.issues[n]["comments"] else [])]
        stats[name]["worlds"].append({
            "pass_receipts": sum(1 for x in receipts if x["verdict"] == review.PASS),
            "needs_correction_receipts": sum(1 for x in receipts if x["verdict"] == review.NEEDS_CORRECTION),
            "task_blocked": sum(1 for x in receipts if x["decision"] == "TASK_BLOCKED"),
            "jules_starts": sum(w.jules_starts.values()),
            "max_labeled_events_per_issue": max([e2e.labeled(w, n) for n in w.gh.issues] or [0]),
            "controller_runs": w.controllers, "controller_crashes": sum("crashed" in l for l in w.log),
            "events_delivered": w.delivered, "faults_left": len(w.gh.faults)})
worlds.clear()
r = unittest.TextTestRunner(verbosity=0, stream=open("/dev/null", "w")).run(
    e2e.EnduranceTests("test_forty_round_campaign_under_random_faults"))
w = worlds[0]
receipts = [rec for n in w.gh.issues for rec in w.receipts(n)]
stats["test_forty_round_campaign_under_random_faults"] = {"ok": r.wasSuccessful(), "worlds": [{
    "pass_receipts": sum(1 for x in receipts if x["verdict"] == review.PASS),
    "needs_correction_receipts": sum(1 for x in receipts if x["verdict"] == review.NEEDS_CORRECTION),
    "jules_starts": sum(w.jules_starts.values()),
    "max_labeled_events_per_issue": max(e2e.labeled(w, n) for n in w.gh.issues),
    "controller_runs": w.controllers, "controller_crashes": sum("crashed" in l for l in w.log),
    "events_delivered": w.delivered, "faults_injected": 30, "faults_left": len(w.gh.faults)}]}
print(json.dumps(stats, indent=2))
