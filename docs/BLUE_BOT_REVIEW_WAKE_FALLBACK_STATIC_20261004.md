# Blue bot-authored review wake fallback — STATIC design

Status: STATIC only. No task setting change, no new scheduled task, no LIVE generation, no Merge.

## Observed production boundary

BWJ-4 generation 3 posted exactly one valid `[CW_BLUE_V1]` PR review to carrier #167 from
`github-actions[bot]`:

- review: `5403033562`
- submitted: `2026-10-03T22:18:25Z`
- carrier commit: `5f9e210bc17ed695610e23b1c1699e11f5c8ed4b`
- target #172 remained unchanged
- no Blue terminal receipt was produced
- Blue PR Review Lane `last_run_time` did not advance

A separate user-approved diagnostic posted one human-authored non-command PR review:

- review: `5405068143`
- submitted: `2026-10-04T08:34:58Z`
- author: `kamiyusense`
- body intentionally did **not** begin with `[CW_BLUE_V1]`

The existing Blue PR Review Lane then advanced `last_run_time` to
`2026-10-04T08:36:13.768648Z`, approximately 75 seconds later. The target and
carrier remained unchanged and no new Blue receipt was created, which is the
expected NO-OP result for a non-command review.

This demonstrates that the current Blue task, repository authorization, carrier
label and pull-request-review event route are live for a human-authored review.
It does **not** identify the undocumented internal reason why the bot-authored
generation-3 review did not create a recorded Work run.

Current diagnosis:

- general Blue task outage: rejected by the human control
- wrong repository/label/event type: rejected by the human control
- malformed generation-3 command review: rejected by GitHub readback/static gates
- exact bot-event suppression/filter/delivery mechanism: **UNKNOWN**
- generation 3 overall: **UNKNOWN / consumed**, never retry

Official OpenAI documentation confirms GitHub PR activity, including PR reviews,
is a supported event-trigger family, but does not document bot-authored review
delivery semantics. Do not invent that rule from the observation.

## Why not impersonate a human

Do **not** solve this by:

- PAT/user token creation
- GitHub App impersonation
- secret/permission expansion
- browser automation that submits as the user
- asking the user to manually relay every command

Those approaches either cross an approval/security boundary or defeat the
copy-elimination goal.

## Safe fallback shape

The smallest durable fallback is a **scheduled reconciliation turn** that reads
the carrier as the source of truth instead of depending on the webhook actor.

Conceptual flow:

```text
GitHub Actions / other controller
  -> durable [CW_BLUE_V1] review on #167
  -> webhook wake may or may not happen
  -> scheduled Blue reconciler fresh-reads #167
  -> selects oldest unprocessed durable Blue command
  -> existing generation/target/expiry/duplicate gates
  -> normal Blue terminal receipt
```

The review remains the durable command. The schedule is only a wake hint.
Author identity is diagnostic metadata, not execution authority.

## New STATIC primitive

`automation/command_bus/blue_work_poll_reconcile.py` adds a prepare-only selector.

It:

1. requires complete reviews/comments readback;
2. applies the fixed Work generation fence first;
3. validates the existing terminal receipt set;
4. parses exact `[CW_BLUE_V1]` submitted COMMENT reviews;
5. validates each command with the existing command contract;
6. treats bot and human authors identically for selection;
7. removes commands already covered by a terminal receipt;
8. deterministically selects the oldest remaining command;
9. returns metadata only; it performs no GitHub write, Work scheduling, target
   mutation, provider call or Jules/model execution;
10. keeps `retry=0` and `fallback=disabled`.

Expired or stale commands are still selected so the existing downstream worker
gate can terminalize them as STALE/BLOCKED/UNKNOWN instead of leaving them
invisible forever.

Duplicate command identities or malformed/conflicting durable records return
UNKNOWN.

## Concurrency rule

Do **not** run the event-triggered Blue worker and a polling Blue worker as two
independent active executors over the same command stream without an additional
mutual-exclusion primitive.

The current terminal-receipt dedupe is a replay guard, not a proven distributed
lock. Two workers starting before either receipt exists could race.

Therefore the preferred first fallback activation is:

1. keep the current carrier/protocol/generation unchanged;
2. pause the current Blue PR Review Lane;
3. enable one Blue scheduled reconciler using the same fixed
   `WORKER_GENERATION=1`;
4. process at most one logical command per run;
5. after terminal receipt, stop;
6. leave Yellow/Green/Red event lanes unchanged.

That cutover is a **task settings change** and is intentionally not performed by
this STATIC work. It requires explicit human approval and fresh task readback.

A future hybrid event+poll design needs a real durable claim/CAS primitive before
both executors can be active at once.

## Operational trade-off

The polling fallback prioritizes correctness and unattended recovery over low
latency. The exact supported recurrence and account task limit must be fresh-read
at activation time. Do not hard-code historical account limits into correctness.

If the product later exposes bot-event delivery guarantees or a safe event
trigger that demonstrably accepts the automated actor, the polling fallback can
be retired without rewriting command history.

## Activation boundary

Before enabling the fallback:

- fresh-read current main, #167, #172 and worker generation;
- verify generation-3 remains consumed and has no terminal receipt;
- inspect the current Blue task and intended replacement task configuration;
- verify no other active Blue executor would race;
- run exact-head CI for this STATIC change;
- preserve artifact/hash/checkpoint;
- obtain explicit approval for the task settings cutover.

Forbidden without that approval:

- pause/edit/delete the existing Blue task;
- create/enable the scheduled reconciler;
- generation 4 LIVE;
- Run now;
- repost generation-3 command;
- manual receipt fabrication;
- provider/Jules/model start;
- permission/secret/PAT/App changes;
- Merge.

## Recovery

If the fallback task is later enabled and its execution outcome is ambiguous,
read GitHub carrier reviews/comments and task run metadata before any further
action. Never resend the same command. Durable GitHub state remains canonical.
