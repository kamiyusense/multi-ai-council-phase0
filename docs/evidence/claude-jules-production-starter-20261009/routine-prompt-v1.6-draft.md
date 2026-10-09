# Reviewer Routine prompt v1.6 (DRAFT, not applied)

Status: **prepared, not applied**. The live Routine `trig_01U2DaBYLqaF5uLgovs1WY2Y` stays on v1.5.1
(`../claude-jules-stop-resistant-20261007/routine-prompt-v1.5.1.md`). Apply v1.6 only when campaigns with more
than one task are started. The first production proof (PRD-C1, one task) does not need it.

## Why a change is needed

A campaign task's `next_task` cannot hold the next task's full issue body. Each body holds a task block, and
that block holds its own `next_task`, so the JSON escaping would nest once per round. The manifest therefore
pins the next task by reference (`body_ref`), and the reviewer creates the issue from the manifest instead of
inlining it. The reviewer still never adds a label. Starting the next task is the Production Starter's job.

## Exact changes against v1.5.1

1. The version string becomes `CLAUDE_CLOSED_LOOP_REVIEWER_V1.6`.
2. In LAYER 3, this line:

   > - PASS: no PR comment; create the next_task issue (no labels) unless an open issue with that title exists; decision ADOPT_RECORDED.

   is replaced by:

   > - PASS: no PR comment; decision ADOPT_RECORDED. Next issue (no labels), unless an open issue with the next_task title exists:
   >   - if next_task has "body", create the issue with next_task title and body;
   >   - if next_task has "body_ref" {campaign_id, seq, task_sha256, path, ref}: run `git fetch origin <ref>` and `git show FETCH_HEAD:<path> > /tmp/campaign.json`, then `python3 -m automation.command_bus.claude_jules_production_starter render-next --campaign /tmp/campaign.json --seq <seq> --task-sha256 <task_sha256>`. If it prints JSON {title, body}, create the issue with exactly that title and body (paste the body verbatim, do not edit it). If it fails, create no issue, set next_issue null and say why in the receipt summary.
   >   - Never add a label to it. The Production Starter alone decides whether it starts.

Nothing else changes: the hard rules, Layers 1 and 2, the receipt keys and the corrective format all stay the same.

## Why this is safe

* `render-next` refuses a body whose `task_sha256` differs from the pinned one, so the reviewer can only create
  the task that the human-approved manifest prepared.
* If the pasted body changes, the Starter blocks it anyway: it compares the issue's task block against the
  manifest's `task_sha256` ("edited after preparation").
* The reviewer still creates the issue before the receipt, as in v1.5.1. The Starter waits (DEFER) until the
  PASS receipt naming that issue exists.
