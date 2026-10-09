# Reviewer + Loop Routine prompt v1.6: final apply candidate (NOT applied)

Status: **prepared, not applied** (batch 18). The live Routine `trig_01U2DaBYLqaF5uLgovs1WY2Y` stays on v1.5.1, and
no trigger or schedule was changed. This file replaces the batch 16 and batch 17 drafts; git keeps their history.

## Facts this is built on

**Official documentation** (<https://code.claude.com/docs/en/routines>, read 2026-10-09):

* **GitHub triggers:** Pull request and Release events only. There is no `issues` or `issue_comment` trigger.
  Pull request filters include "is merged".
* **Caps:** events over the per-routine and per-account hourly caps are **dropped**, not queued.
* **Schedules:** at least **1 hour** apart. A routine may combine schedule, API and GitHub triggers.
* **What a run is:** a full Claude Code cloud session. It runs shell commands in the cloned repository (default
  branch) and uses the connectors you include.
* **Usage:** runs draw down subscription usage.
  * Without usage credits, runs are rejected until the usage window resets.
  * **With usage credits on, routines can keep running on metered overage.**
* **Usage credits:** turned on or off at Settings → Usage, billed at API rates
  (<https://support.claude.com/en/articles/12429409-manage-usage-credits-for-paid-claude-plans>).

**Observed in the 5 earlier runs** (read-only from their logs):

* the Routine ran `python3`, `git` and `date` in Bash;
* it read and wrote GitHub through the GitHub MCP tools: `pull_request_read`, `issue_read` (`get`,
  `get_comments`), `issue_write`, `add_issue_comment`, `get_file_contents`, `list_commits`, `get_commit`,
  `search_issues`;
* the trigger context tells the session to use `gh api --hostname github.com …`, but no run has used `gh`, so
  **`gh` authentication inside a run is UNKNOWN**;
* none of the MCP calls seen reads issue **events**. The label history needs
  `GET /repos/{o}/{r}/issues/{n}/events` with every page. Locally that works with `gh`, and #335's
  `labeled jules` event was read back.
* The repository is **private**: an unauthenticated GET returns 404, so a token-less fallback does not exist.

## Design

```
pull_request.opened / synchronize   -> Layers 1-3 (unchanged) -> receipt -> LAYER 4
pull_request.closed, is merged      -> LAYER 4
schedule, hourly (recovery)         -> Layers 1-3 for every open task PR head without a receipt, then LAYER 4
```

LAYER 4 is one deterministic command. The code chooses the writes, and Claude does not choose any write in
Layer 4:

```
python3 -m automation.command_bus.claude_jules_starter_gh tick \
    --campaign <manifest on main> \
    --route-declaration docs/evidence/claude-jules-production-starter-20261009/route-declaration.json \
    --controller "routine-$(date -u +%Y%m%dT%H%M%S)" \
    --live-authorization <authorization file on main>
```

* Inside one run it reads GitHub back after every write. Only that run's intent may lead to the label.
* It never re-sends a write whose outcome is unknown.
* It writes only loop records, the `jules` label on an authorized campaign issue, and campaign task issues.
* Without a valid authorization it sends nothing. It prints what it would have done.

## Exact prompt changes against v1.5.1

1. The version string becomes `CLAUDE_CLOSED_LOOP_REVIEWER_V1.6`.
2. **Hard rules.** "Never add the `jules` label to any issue. Never create a Jules task by any other means." is
   replaced by:

   > Never add a label and never create an issue yourself. The only exception is that LAYER 4 runs one command,
   > which may do so under the human-approved LIVE authorization file. Never create a Jules task by any other means.

3. **Layer 3, PASS.** Add the `next_task.body_ref` rule:

   > If next_task has "body_ref" {campaign_id, seq, task_sha256, path, ref}, run `git fetch origin <ref>`, then
   > `git show FETCH_HEAD:<path> > /tmp/campaign.json`, then
   > `python3 -m automation.command_bus.claude_jules_production_starter render-next --campaign /tmp/campaign.json --seq <seq> --task-sha256 <task_sha256>`.
   > Create the issue with exactly the printed title and body, with no labels. If the command fails, create no
   > issue and set next_issue null.

4. **New LAYER 4**, after the receipt, or directly for a `closed` or schedule wake:

   > LAYER 4 - loop tick. First run `gh auth status`. If it fails, report "LAYER 4 skipped: gh not authenticated"
   > and stop. The loop never starts without the label history.
   > Then run the tick command above exactly once and include its JSON output in the notification.
   > Do not perform any write the command did not perform.

5. **Schedule wakes.**

   > If the wake is the schedule, first list the open pull requests whose body links a closed-loop task issue.
   > Run Layers 1-3 for each head that has no receipt. Then run LAYER 4.
   > If nothing is pending (the tick prints DEFER or MERGE_WAIT with no change), end the run.

## Why the hourly recovery wake is needed

The mock proves this (`test_no_new_pr_event_after_a_crash_needs_the_recovery_wake`). After a run dies between
the PASS receipt and the next start, **no PR event will ever come**, because the next Jules task never started.
Without a schedule the loop waits for a human "Run now". The same holds when:

* the quota resets;
* a GitHub outage ends;
* a lease expires;
* an event was dropped over the cap.

**Cost:** at most 24 runs a day. A quiet run is one tick that reads GitHub and writes nothing: the checkpoint is
written only on change or on a heartbeat. Pausing the routine stops it, and resuming continues from GitHub state.

**Quota:**

* With usage credits **off**, runs over the limit are rejected until the window resets. The next schedule then
  resumes.
* With usage credits **on**, the documentation says routines can continue on metered overage. That is why the
  LIVE authorization requires `usage_credits_confirmed_off: true` from the human.
