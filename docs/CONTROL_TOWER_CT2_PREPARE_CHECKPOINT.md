# Phase 0 Control Tower v2 — CT-2 prepare-only checkpoint

## Baseline

- Repository: `kamiyusense/multi-ai-council-phase0`
- Baseline main:
  `26c433afb08191a8cc1d6e0ea640889c70b8410d`
- PR #77 CT-1 static foundation: merged.
- Issue #33 at batch start:
  `🚦 Phase 0 Loop Status — ⚫ STOPPED`
- Issue #33 comments at batch start: 0.

## Boundary

This batch prepares the single-loop -> Multi-loop Control Tower migration without
performing any live Issue mutation.

It adds no GitHub network client and contains no PATCH/POST path.

## Implemented

`automation/command_bus/control_tower_issue_plan.py` adds a pure prepare-only
migration boundary.

Given:

- an already-built verified `ControlTowerModel`;
- a fresh Issue #33 readback;
- optional existing comment bodies for dedupe;

it prepares:

- exact expected aggregate title;
- exact expected Control Tower body;
- Development-block-preserving migration output;
- bounded notification plans for TURN_COMPLETE / HUMAN_NEEDED only.

## Pre-write conflict gate

The planner records the exact base Issue snapshot.

Before any future live write, `assert_issue_unchanged` requires Issue #33 to
still match the base:

- issue number;
- open state;
- title;
- body.

Any change blocks overwrite.

This preserves the existing Signal rule that an Issue edit after readback must
not be overwritten blindly.

## Post-write readback gate

`verify_issue_applied` requires exact title/body readback after a future write.

A mismatch is failure/UNKNOWN at the live adapter layer; this module never
blindly retries.

## Notification semantics

The prepare layer does not infer notification events from display state.

Only lanes whose durable event kind is explicitly:

- `TURN_COMPLETE`; or
- `HUMAN_NEEDED`

produce a notification plan.

A BLOCKED/UNKNOWN display lane without such a durable event kind does not invent
a comment.

Dedupe marker identity is:

`kind + loop_id + durable event_id`

Existing matching markers are replay NO-OP for that lane/event only.

## Private data boundary

Notification bodies use only bounded Control Tower lane fields and safe detail
refs such as `issue:33` / `pr:N`.

No private ChatGPT / Claude / Work URL is accepted by the CT-1 registry, and
this CT-2 planner introduces no new URL field.

## Tests

Coverage includes:

- single-loop legacy body -> multi-loop title/body plan;
- Development managed block preservation;
- no mutation of caller model/Issue input;
- title/body/state conflict detection before write;
- exact post-write readback requirement;
- only TURN_COMPLETE/HUMAN_NEEDED notification planning;
- loop-specific durable-event replay NO-OP;
- BLOCKED/UNKNOWN display alone does not invent notification;
- private URL absence from notification plans;
- wrong/closed Issue rejection;
- already-matching Issue -> Issue update NO-OP and comment replay NO-OP.

## Explicitly not performed

- no live Issue #33 PATCH;
- no live Issue #33 comment POST;
- no workflow_dispatch;
- no owner/runtime ledger write;
- no provider/model/Jules/Claude execution;
- no live Control Tower migration;
- no Windows executable;
- no Merge in this batch.

## Remaining CT-2 live boundary

Still required before live migration:

1. production multi-loop collection of already verified per-loop projections;
2. exact durable loop IDs for the real lanes, or an explicitly accepted
   presentation-only registry mapping to verified durable loop IDs;
3. live adapter that performs one Issue update attempt only after the conflict
   gate and exact readback;
4. live notification adapter that preserves loop_id + durable event_id dedupe;
5. explicit human approval for the first deployed Issue #33 migration.

This batch intentionally stops before those live effects.

## Evidence to fill after exact-head CI

- exact tested PR head: PENDING
- GitHub Actions run: PENDING
- focused tests: PENDING
- full command-bus tests: PENDING
- schema parse: PENDING
- compileall: PENDING
- git diff --check: PENDING
- tested head -> current head compare: PENDING
- Issue #33 live mutation: MUST REMAIN NONE
