# Batch 28: independent-review P0 fixes for PR #345

Date: 2026-10-10 JST. Scope: exactly the two P0 findings; P1 deferred. No LIVE, no Routine change, no Merge.
Start head `8fcff3268edf4b7ce71d92f75e51547bf4e6da02` (= remote), main `4bb5cd72…`.

## P0-1: the control issue is required for any new LIVE start

`GhLiveWritePort.stop_requested()` now refuses (HUMAN_STOP) every new Jules start (label) and every new task
issue when the campaign's `control_issue` is: not set or not a positive integer; missing on GitHub; unreadable;
a task issue; CLOSED; or labeled `loop-stop`. Comments of running work (records, checkpoints) are unaffected.
Before this, a campaign without `control_issue` returned "no stop" and could start work.

Compatibility: every existing LIVE test campaign gets a control issue from `LoopWorld` and still passes. The PRD-C2
pilot campaign file has no control issue, so it cannot go LIVE through the adapter until one is set; that is
intended (no stop switch, no LIVE).

Tests `ControlIssueRequiredTests` (4): five bad states each block every start (no label, no slot); unreadable
blocks; a task issue cannot be the control issue; an open one lets the loop run. They fail on the batch-27 code.

## P0-2: the campaign starts with real work

* Control issue **#346** and three signal issues **#347, #348, #349** created on GitHub (author `kamiyusense`,
  trusted writer; no labels; no task block, so neither the Reviewer nor Jules acts on them; no workflow has an
  `issues` trigger, and Routine triggers are pull_request only).
* Each signal is a real Windows-only bug: `Path.read_text()` without an encoding reading a non-ASCII UTF-8 file, in
  three independent test files, found by an instrumented run of the suite on main `4bb5cd7`. They are not run on
  Windows yet (stated in each issue); PRD-002 is the observed Windows failure of the same pattern.
* `initial-backlog.json` (fixture) == what GitHub returns: readback with the adapter's own GET path
  (`backlog-readback.json`: signals equal, control body equal, all OPEN, no labels, no label events).
* `prod-campaign.TEMPLATE.json`: objective `o1-windows-portability` scoped to exactly those three files,
  `control_issue: 346`; still invalid until a human approves the objective.
* Read-only tick against live GitHub with the template approved only in a local temp copy: preflight OK (HTTP 200,
  private), planner read the signals from GitHub and prepared the first task issue, `sent: []`, `live: false`
  (`readonly-tick-rehearsal.json`).
* Tests `InitialBacklogTests` (3): the planner proposes all three in turn, each valid and never twice, and the cited
  file:line exists on this tree; signal issues round-trip exactly; the backlog runs to 3 PASS in the mock with no
  human step.

## Remaining UNKNOWN

The Routine cloud session pushing slot files to the data branch; Jules on a duplicate concurrent label; Draft-PR
Routine wake behaviour; whether these three files really fail on a Windows host (pattern evidence only); a real
LIVE multi-task run.
