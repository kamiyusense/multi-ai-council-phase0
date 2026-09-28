# Control Tower migration recovery v1 — checkpoint

## Baseline

Repository:
`kamiyusense/multi-ai-council-phase0`

Baseline main:

`69d0d4c81ce74144fa94dee38cc6e2f97a5ac030`

PR #90 snapshot contract was already merged.

PR #91 durable collector may still be open independently; this recovery batch
does not depend on its branch.

Issue #33 remained the deployed single-loop STOPPED display.

No live Control Tower migration or rollback is performed in this batch.

## Purpose

Define the recovery/rollback boundary for the first live single-loop ->
Multi-loop Control Tower migration without introducing automatic rollback or
destructive behavior.

The recovery rule is deliberately conservative:

```text
original Issue snapshot
-> verified Control Tower migration
-> later rollback requested explicitly
-> current Issue must still equal exactly what that migration wrote
-> restore the exact original title/body
```

If the Issue changed after migration, rollback does not overwrite it.

## Implemented

Added:

`automation/command_bus/control_tower_migration_recovery.py`

The module is transport-neutral.

It contains:

- `ControlTowerRollbackPlan`
- `prepare_control_tower_rollback()`
- `verify_control_tower_rollback()`
- `ControlTowerRollbackPublisher`

No production GitHub adapter is added here.

## Rollback is never automatic

Nothing in this module reacts automatically to:

- ETA overdue;
- snapshot parse failure;
- provider state;
- owner expiry;
- BLOCKED;
- failed notification;
- a timer;
- Windows Signal Companion state.

A caller must explicitly invoke rollback with the original
`ControlTowerIssuePlan`.

## Exact compare-and-swap boundary

Before preparing rollback:

- Issue number must still be #33;
- Issue must still be OPEN;
- current title must exactly equal the migration's expected title;
- current body must exactly equal the migration's expected body.

Any human edit, later Control Tower refresh, or unrelated mutation blocks the
rollback plan.

Before writing rollback, the publisher independently reads Issue #33 again and
requires the same exact applied migration snapshot.

This prevents recovery from overwriting newer work.

## Restore target

Rollback restores exactly:

`migration_plan.base`

That is the original pre-migration Issue #33 title/body captured by the
prepare-only migration plan.

This includes the original Development managed block without reconstructing it
from new logic.

The rollback code does not infer or regenerate the old single-loop body.

## Retry-zero behavior

The rollback publisher performs at most one PATCH attempt for a rollback plan.

If the transport result is ambiguous:

- read Issue #33 back;
- if exact original title/body is present -> RECOVERED;
- otherwise -> UNKNOWN;
- do not resend.

The same exact rollback plan is protected by an in-memory replay guard within
the publisher instance.

The in-memory guard is defense-in-depth only and is not claimed as durable
exactly-once state.

## Notification comments

Rollback modifies Issue title/body only.

It does not:

- list comments;
- delete comments;
- post compensating comments;
- remove TURN COMPLETE;
- remove HUMAN NEEDED.

Existing notification comments remain append-only evidence.

## No-op rollback

If a migration plan's expected title/body already equal its base snapshot,
rollback is a verified NO-OP and performs no PATCH.

## Tests

Mock regression coverage includes:

- exact applied migration -> rollback plan;
- human body edit blocks prepare;
- later title refresh blocks prepare;
- closed Issue blocks prepare;
- verified rollback restores exact original title/body;
- original Development block is restored exactly;
- pre-write conflict blocks with zero PATCH;
- ambiguous PATCH that applied -> RECOVERED without resend;
- ambiguous PATCH that did not apply -> UNKNOWN, then replay guard blocks retry;
- same rollback plan cannot be attempted twice;
- rollback does not read/post/delete notification comments;
- no-op rollback performs zero PATCH.

## Relationship to live migration

This module does not authorize the first live migration.

The already-merged gates still apply first:

- explicit DURABLE identity adoption;
- durable TransitionProjectionResult;
- registration readiness;
- live migration preflight;
- exact Issue migration plan;
- retry-zero Issue publisher.

Only after an actual migration has been verified can its exact plan be used as
rollback evidence.

## Explicitly not performed

- no Issue #33 PATCH;
- no Issue comment mutation;
- no workflow_dispatch;
- no provider/model execution;
- no runtime ledger write;
- no takeover;
- no final durable loop ID assignment;
- no automatic rollback trigger;
- no Windows executable;
- no Merge in this batch.

## Exact-head verification

- exact tested PR head:
  `eaf9c42f9253b9f6aba1bf4efe044e222676e043`
- GitHub Actions run:
  `36390786698` — **SUCCESS**
- focused Status/runtime/validation suite:
  **271/271 PASS**
- full command-bus suite:
  **596/596 PASS**
- command-bus JSON schemas parsed:
  **21/21 PASS**
- Python compileall:
  **PASS**
- `git diff --check`:
  **PASS**
- representative recovery tests were present in the exact-head CI log:
  - exact applied migration is required before rollback plan;
  - human/later Issue edits block rollback;
  - ambiguous PATCH that applied is recovered by readback without resend;
  - notification comments remain untouched;
  - identical rollback plan cannot be attempted twice.
- tested head -> current head compare:
  to be read back after this documentation-only evidence commit.
- Issue #33 live mutation:
  **NONE required; fresh readback must remain the deployed single-loop STOPPED display.**
