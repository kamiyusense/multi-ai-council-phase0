"""Re-runs the planner-loop endurance scenarios and prints what each actually did.

    python3 docs/evidence/claude-jules-production-starter-20261009/e2e_loop_stats.py
"""
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))
from automation.command_bus import claude_closed_loop_review as review  # noqa: E402
from automation.command_bus import claude_jules_loop as loop  # noqa: E402
from automation.command_bus.tests import test_claude_jules_loop as t  # noqa: E402

out = {}
for rounds, seed in ((40, 7), (100, 11), (300, 23)):
    case = t.LoopEnduranceTests("test_forty_round_planner_loop_with_faults_merges_and_new_work")
    w, merges = case.run_endurance(rounds, seed)
    by = t.tasks_by_signal(w)
    receipts = [r for n in w.gh.issues for r in w.receipts(n)]
    case.check(w, rounds)                      # raises if any invariant fails
    out[f"{rounds}_rounds"] = {
        "invariants": "PASS",
        "signals_merged": sum(1 for s in by if s != "human-op" and w.pr_merged(by[s][0])),
        "jules_starts": sum(w.jules_starts.values()),
        "max_labeled_events_per_issue": max(t.labeled(w, n) for n in w.gh.issues),
        "pass_receipts": sum(1 for r in receipts if r["verdict"] == review.PASS),
        "corrective_rounds": sum(1 for r in receipts if r["verdict"] == review.NEEDS_CORRECTION),
        "loop_ticks": len(w.ticks), "loop_crashes": w.loop_crashes,
        "tick_outcomes": dict(Counter(x.outcome for x in w.ticks)),
        "checkpoints_written": sum(1 for x in w.ticks if x.checkpoint_written),
        "human_merge_batches": merges, "faults_injected": w.faults_injected, "faults_fired": w.faults_fired,
        "final_outcome": w.ticks[-1].outcome,
        "final_human_actions": w.ticks[-1].human_actions,
    }
print(json.dumps(out, indent=2))
