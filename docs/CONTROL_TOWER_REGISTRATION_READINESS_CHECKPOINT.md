# Control Tower durable registration readiness — checkpoint

## Baseline

- Repository: `kamiyusense/multi-ai-council-phase0`
- Baseline main:
  `04b37b3b9d27705448d68048acc2be7a7127c6a2`
- PR #78 CT-2 prepare-only migration plan: merged.
- Issue #33 remains deployed as the existing single-loop STOPPED display.
- No live Control Tower migration is performed in this batch.

## Purpose

Prevent CT-1 presentation registry IDs from being mistaken for already-proven
durable runtime identities.

The Control Tower v2 roadmap states:

- `loop_id` is the durable correctness identity;
- do not assume the four final loop IDs exist yet;
- use static fixtures/registry entries until durable IDs are explicitly
  available;
- real multi-loop integration belongs to CT-4 only after stable durable loop IDs
  exist.

This batch adds a fail-closed registration readiness gate for that boundary.

## Implemented

Added:

`automation/command_bus/control_tower_registration.py`

The gate accepts:

- the bounded Control Tower registry; and
- an existing mapping of durable `TransitionProjectionResult` values.

It does **not** accept a raw list of loop-id strings as proof.

For every enabled registry lane, READY requires:

1. an existing `TransitionProjectionResult` under the exact same loop_id;
2. transition status is one of VALID / TERMINAL / BLOCKED;
3. the accepted transition has an existing projection;
4. the accepted transition has an existing OwnerDecision;
5. `projection.loop_id` exactly equals the registry loop_id.

UNKNOWN transition results remain NOT_WIRED.

Missing enabled lanes remain NOT_WIRED.

Mismatched or malformed accepted transition records are BLOCKED.

Extra verified transitions that are not registered are ignored and never make a
missing registered lane READY.

Disabled presentation lanes do not require a durable transition.

## Current repository result

Fresh readback before this branch found that the four current CT-1 registry IDs:

- `chatgpt-semi-auto`
- `claude-gemini`
- `claude-claude`
- `work-gemini`

currently appear as presentation/test identities, not as independently proven
final durable runtime IDs.

Therefore the expected production state remains:

`CONTROL_TOWER_REGISTRATION = NOT_WIRED`

until verified durable transition results exist under those exact IDs or the
registry is deliberately updated to the real durable IDs after they become
stable.

This module does not perform repository discovery itself and does not invent a
mapping.

## Tests

Added coverage for:

- repository registry + missing durable inventory -> NOT_WIRED;
- registry ID alone never counts as proof;
- exact matching durable transition -> READY;
- UNKNOWN transition -> NOT_WIRED;
- projection loop-id mismatch -> BLOCKED;
- non-transition object -> BLOCKED;
- incomplete accepted transition -> BLOCKED;
- disabled lane does not require durable identity;
- unrelated verified transition cannot satisfy a missing registered lane;
- multiple enabled lanes require all identities before READY.

## Explicitly not performed

- no Issue #33 PATCH/comment;
- no workflow_dispatch;
- no live multi-loop collector;
- no owner/runtime/provider writes;
- no provider/model/Jules/Claude execution;
- no registry promotion of placeholder IDs into durable truth;
- no Windows app;
- no Merge in this batch.

## Remaining live boundary

Still unresolved:

`CONTROL-TOWER-REAL-LOOP-IDS-001 = UNKNOWN`

A real collector/migration may proceed only after the final durable loop IDs are
available through existing durable transition verification.

## Exact-head verification

- exact tested PR head:
  `2fd125f298cb304a85171a8d223f7533314d5a3c`
- GitHub Actions run:
  `36377164603` — **SUCCESS**
- focused Status/runtime/validation suite:
  **236/236 PASS**
- full command-bus suite:
  **523/523 PASS**
- command-bus JSON schemas parsed:
  **19/19 PASS**
- Python compileall:
  **PASS**
- `git diff --check`:
  **PASS**
- representative registration-readiness tests were present in the exact-head CI log:
  - repository registry without verified inventory -> NOT_WIRED;
  - registry id alone never counts as READY;
  - matching existing TransitionProjectionResult -> READY;
  - durable projection loop-id mismatch -> BLOCKED.
- tested head -> current head compare:
  to be read back after this documentation-only evidence commit.
- Issue #33 live mutation:
  **NONE required; fresh readback must remain the deployed single-loop STOPPED display.**
