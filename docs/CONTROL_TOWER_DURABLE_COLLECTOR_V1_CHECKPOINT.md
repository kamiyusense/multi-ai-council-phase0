# Control Tower durable collector v1 — checkpoint

## Baseline

Repository:
`kamiyusense/multi-ai-council-phase0`

Baseline main:

`69d0d4c81ce74144fa94dee38cc6e2f97a5ac030`

PR #90 machine snapshot contract was merged before this batch.

Issue #33 remained the deployed single-loop STOPPED display.

No live Control Tower migration is performed in this batch.

## Purpose

Provide the missing read-only bridge between a real durable runtime loop and the
already-merged Control Tower registration/live-migration preflight.

This collector does not decide loop identity, does not invent durable records,
and does not write anything.

It reuses the existing durable transition path.

## Implemented

Added:

`automation/command_bus/control_tower_durable_collector.py`

Per-loop flow:

```text
durable loop_id
  |
  v
state readback
+ complete bounded owner-event chain
  |
  v
existing build_fetch_plan()
  |
  v
exact source receipt
+ exact evidence refs
+ canonical provider observation when active
+ fresh target PR readback
  |
  v
independent second readback of durable records and target
  |
  v
existing project_durable_transition()
  |
  v
TransitionProjectionResult
```

No runtime correctness logic is reimplemented.

## Registry behavior

`collect_registry()` accepts the existing Control Tower display registry.

Rules:

- zero enabled lanes -> NOT_WIRED;
- any enabled lane whose `identity_state != DURABLE` -> NOT_WIRED;
- PLACEHOLDER lanes cause **no durable GitHub reads**;
- only explicit DURABLE lanes are collected;
- every enabled DURABLE lane must be collected before inventory status READY.

Therefore the current repository registry remains NOT_WIRED until real loop IDs
are explicitly adopted as DURABLE.

## Exact durable readbacks

The collector reads only records named by the validated state/owner chain.

It uses the existing `build_fetch_plan()` to determine:

- source receipt ref;
- evidence refs;
- provider observation ref;
- expected repository;
- expected PR;
- generation/fencing/event context.

Bounds:

- owner chain: 1..100 generations;
- evidence refs: max 32;
- loop_id uses the existing bounded command-bus component format.

Unexpected owner filenames, duplicate paths, path escapes, malformed records, or
missing durable records fail closed.

## Read-consistency guard

To avoid projecting a mixed-time snapshot, after reading all referenced
materials the collector independently re-reads:

- mutable state;
- complete owner chain;
- source receipt;
- every evidence document;
- provider observation when present;
- fresh target PR.

Any change during collection returns UNKNOWN.

This is read-only and performs no retry or write.

## Fresh target boundary

The target reader is injected.

For active owner events:

- repository and PR identity must match;
- target must be OPEN;
- target must be non-merged.

The target head is passed to the existing durable transition verifier.

A stable but moved target head can therefore be collected as a verified
BLOCKED transition rather than being silently treated as healthy.

If the target changes between the two collector reads, collection is UNKNOWN.

For TERMINAL / RELEASE owner generations, the active-open constraint does not
apply, but target identity is still read and bound through the existing
transition verifier.

## PLACEHOLDER safety

The collector will not use the four current presentation placeholders as live
runtime IDs merely because matching GitHub paths happen to appear.

Current expected result:

```text
identity_state = PLACEHOLDER
-> collect_registry = NOT_WIRED
-> no durable read attempt
```

Only after a real loop has explicitly adopted a stable ID and the registry entry
is changed to DURABLE does collection begin.

## Tests

Added mock regression coverage for:

- valid active durable loop -> COLLECTED / VALID / SEMI_AUTO;
- PLACEHOLDER registry -> NOT_WIRED with zero durable/target reads;
- DURABLE registry -> READY transition inventory;
- zero enabled lanes -> NOT_WIRED;
- missing exact receipt -> UNKNOWN;
- state mutation during collection -> UNKNOWN;
- receipt mutation -> UNKNOWN;
- evidence mutation -> UNKNOWN;
- provider observation mutation -> UNKNOWN;
- target mutation -> UNKNOWN;
- active closed target -> UNKNOWN;
- stable moved target head -> COLLECTED / BLOCKED;
- TERMINAL generation without provider observation -> COLLECTED / TERMINAL / IDLE;
- unsafe loop_id -> BLOCKED before reads.

All transports are deterministic fakes.

## Explicitly not performed

- no GitHub live collector execution;
- no Issue #33 mutation;
- no workflow_dispatch;
- no owner/state/receipt/evidence/provider write;
- no provider/model/Jules/Claude/Gemini execution;
- no final durable loop ID assignment;
- no takeover;
- no CT-3 Development migration;
- no Windows executable;
- no Merge in this batch.

## Remaining boundary

The collector implementation is ready, but the current four real runtime lanes
still do not expose explicitly adopted stable DURABLE loop IDs.

Therefore:

`CONTROL-TOWER-REAL-LOOP-IDS-001 = UNKNOWN`

remains the live integration blocker.

Once a real loop adopts a DURABLE ID, this collector can be used as the
read-only evidence source for the already-merged Control Tower live preflight.

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
