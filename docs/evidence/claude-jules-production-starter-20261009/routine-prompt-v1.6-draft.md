# Reviewer + Loop Routine prompt v1.6 (DRAFT, not applied)

Status: **prepared, not applied**. The live Routine `trig_01U2DaBYLqaF5uLgovs1WY2Y` stays on v1.5.1, and no
trigger was changed. This draft replaces the batch 16 v1.6 draft. That draft only added `body_ref`.

## What the official documentation says, and why the design changed (checked 2026-10-09)

Source: <https://code.claude.com/docs/en/routines>

* **GitHub triggers:** a routine can subscribe to **Pull request** events (opened, closed, assigned, labeled,
  synchronized, or otherwise updated) and **Release** events, and nothing else. There is **no `issues` and no
  `issue_comment` trigger**. The batch 16 Starter Routine draft relied on those events, so it is superseded.
* **Filters:** pull request events can be filtered by author, title, body, base or head branch, labels, is
  draft, and is merged.
* **Caps:** GitHub events have per-routine and per-account hourly caps. Events beyond the cap are **dropped**,
  not queued. A lost wake is therefore a normal case, and the recovery wake below covers it.
* **Schedules:** the minimum interval is **one hour**. A routine can combine schedule, API and GitHub triggers.
* **Billing:** routine runs draw down subscription usage.
  > "When a routine hits your subscription usage limit, organizations with usage credits turned on can keep
  > running routines on metered overage."

  A human must confirm that usage credits are **off**. Otherwise an unattended loop could run on metered overage.
  This is a Billing setting, and automation never changes it.

## Design: one Routine, the PR event is the heartbeat

The Starter and Loop no longer need a Routine of their own. The same reviewer run that judged a PR continues
with a loop tick:

```
pull_request.opened / synchronize      -> Layers 1-3 (unchanged) -> receipt -> LAYER 4 loop tick
pull_request.closed (is merged = true) -> LAYER 4 loop tick (merge-dependent work resumes)
schedule, hourly (recovery)            -> review any open task PR head with no receipt, then LAYER 4 loop tick
```

The responsibilities stay separate. Layers 1-3 judge the PR. Layer 4 runs the deterministic loop code. Only that
code decides what may start, and Claude performs exactly the writes it names.

## Trigger changes this needs (human approval; not made)

1. Add `pull_request.closed` with the filter "is merged = true" to the existing webhook trigger, or as a second
   one. Without it, merge-dependent work resumes only on the next other PR event or recovery wake.
2. Add an hourly schedule trigger (for example at minute 7) for recovery. Without it, a run that dies between the
   receipt and the next start waits until a human presses "Run now". `test_without_a_recovery_wake_a_dead_run_waits_for_a_human`
   shows this. The recovery tick is cheap when nothing changed: no write, because the checkpoint is written only
   on change or on a heartbeat.

## Exact prompt changes against v1.5.1

1. The version string becomes `CLAUDE_CLOSED_LOOP_REVIEWER_V1.6`.
2. **Hard rules.** "Never add the `jules` label to any issue. Never create a Jules task by any other means." is
   replaced by:

   > Never add the `jules` label and never create an issue except as LAYER 4 instructs, and only the exact write
   > the loop code printed in this run. Never create a Jules task by any other means.

3. **Layer 3, PASS.** The `next_task` handling is the `body_ref` text of the batch 16 draft: `render-next`, create
   the issue verbatim, no label.
4. **New LAYER 4** (after the receipt; or first, when the wake is `pull_request.closed` or the schedule):

   > LAYER 4 - loop tick (deterministic; no judgement beyond writing a proposal):
   > - Run `python3 -m automation.command_bus.claude_jules_loop tick --campaign <campaign file> --controller <run id>`.
   >   It prints exactly one next write (`create_issue`, `comment`, or `add_label jules`) or a final outcome.
   > - Perform that one write. Then run it again with `--session-nonce` for every intent you wrote, and
   >   `--label-written-nonce` after you added the label. At most 8 writes per wake.
   > - If it asks for a proposal for a signal, write a `CLAUDE_TASK_PROPOSAL_V1` JSON for that signal. It must stay
   >   inside the objective's scope and approved operations, and name concrete acceptance criteria and test
   >   commands. The code validates it, and a rejected proposal is skipped.
   > - Never repeat a write whose result you did not see; run the tick again instead.
   > - The final outcome (CONTINUE, MERGE_WAIT, NO_SAFE_TASK, GOAL_COMPLETE, DEFER, HARD_STOP_PROVIDER) and its
   >   human actions go into the push notification.

5. **Scheduled wakes.** "If the wake is the schedule: for every open pull request whose body links a closed-loop
   task issue and whose head has no receipt, run Layers 1-3 for it. Then run LAYER 4."

## UNKNOWN before this can go live

* Whether `gh` is authenticated inside a Routine run. The v1.5 runs used the GitHub MCP tools. The loop's
  label-history read needs the issue events API.
  * If `gh` works, a `gh`-backed port runs the tick directly.
  * If it does not, the MCP tools must supply label history. Otherwise the Starter returns `DEFER READ_UNKNOWN`
    and never starts: safe, but nothing starts.
* A CLI entry point `claude_jules_loop tick` that drives a real port. It is designed above. This batch implements
  the loop over an abstract port and tests it fully in the mock. The real-port CLI and its send path belong to
  the LIVE activation step, and no send path exists today.
* Whether usage credits are off (Billing, human).
