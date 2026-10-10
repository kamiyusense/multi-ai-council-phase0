# Batch 29: lane-scope correction of the prod-c1 initial backlog (review comment 6094535676)

Date: 2026-10-10 JST. Start head `35ffa115ea2b4affd7977d1b64f656090ea9e22a`. No LIVE, no Routine change, no Merge.

**Finding (independent review):** the three initial signals #347-#349 and the template scope targeted Blue/Work
bridge test files. The Claude × Jules campaign must stay in its own lane. Accepted; nothing had been modified there.

**Correction**

* `prod-campaign.TEMPLATE.json`: objective `o1-claude-jules-lane`, scope only
  `automation/command_bus/claude_jules_live_adapter.py` and `automation/command_bus/tests/test_claude_jules_*`.
* `initial-backlog.json`: ONE genuine in-lane task (no count padding): `GitLiveClient._push` reports git's
  concurrent-push rejection (`[remote rejected] (failed to update ref)` + `cannot lock ref ... is at X but expected Y`,
  observed in the batch 27 race) as an ambiguous outcome instead of `PushRejected`. Reproduced deterministically
  (`test_the_cited_bug_is_real`). Created as signal issue **#350** (author `kamiyusense`, no labels).
  Other in-lane candidates checked and rejected as not real bugs: `read_text()` without encoding in
  `test_claude_jules_campaign.py` / `test_claude_jules_dispatch_contract.py:137,145` (the files are ASCII), git
  `text=True` in `test_claude_jules_live_adapter.py` (ASCII output). `test_claude_jules_dispatch_contract.py:68`
  is real but is PRD-001's (#338) file, so it is left to avoid a same-file conflict.
* #347-#349: left open and unchanged (their objective `o1-windows-portability` is not in prod-c1), recorded in
  `initial-backlog.json` `excluded` with the reason; `test_out_of_lane_signal_issues_are_never_planned` proves the
  planner skips them ("outside the approved objectives").
* `backlog-readback.json`: fixture == GitHub (#350 signal, #346 control body); #346-#350 OPEN, no labels, no label
  events. `readonly-tick-rehearsal.json` re-run on live GitHub: planned only the #350 task, `sent: []`.

Tests: `InitialBacklogTests` now 6 (lane-only scope and paths, valid and planned once, bug reproduces, out-of-lane
never planned, round trip, runs to PASS in the mock). Full suite: see `checkpoint-batch29.json`.
