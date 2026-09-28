# Control Tower live migration preflight v1 — checkpoint

## Baseline

Repository:
`kamiyusense/multi-ai-council-phase0`

Fresh main before this batch:

`88020699a00056d3635899c2d9d4c7739f87a25b`

The following prerequisite PRs were already merged before this batch:

- PR #80 — Semi-Auto timing footer policy;
- PR #81 — durable registration readiness gate;
- PR #82 — Semi-Auto timing presentation hints;
- PR #84 — Jules Session createTime accepted-at provenance/readback.

Issue #33 remained:

`🚦 Phase 0 Loop Status — ⚫ STOPPED`

with zero comments.

No live Control Tower migration is performed in this batch.

## Purpose

Close a fail-closed integration gap between the already-merged registration
readiness gate and the already-merged prepare-only Issue migration planner.

Before this batch those components were individually fail-closed, but a future
caller could theoretically invoke the Issue planner directly with a manually
constructed ControlTowerModel.

This batch adds a production-facing pure preflight that refuses to create an
Issue migration plan until durable registration is READY.

## Implemented

Added:

`automation/command_bus/control_tower_live_preflight.py`

Main flow:

```text
bounded static registry
+
existing TransitionProjectionResult inventory
        |
        v
assess_registration_readiness
        |
        +-- missing / UNKNOWN -> NOT_WIRED
        +-- mismatch / malformed -> BLOCKED
        |
        v
verified transition -> presentation bridge
        |
        v
ControlTowerModel
        |
        v
prepare-only Issue #33 migration plan
```

No network or GitHub write occurs in this module.

## Required gates

Before `READY`:

1. the registry must validate;
2. at least one lane must be enabled;
3. every enabled registry lane must have an existing
   `TransitionProjectionResult`;
4. every accepted durable projection must use the exact same `loop_id`;
5. registration readiness must be `READY`;
6. caller presentation metadata may reference enabled lanes only;
7. target refs and event kinds must pass the existing bounded presentation
   bridge;
8. a verified durable lane may not silently become presentation UNKNOWN;
9. Issue #33 readback must be usable by the prepare-only Issue planner.

If Issue readback itself is unavailable/malformed after durable gates pass, the
preflight returns `UNKNOWN` and no Issue plan.

## Zero-lane protection

The existing registration readiness helper intentionally allows a registry with
zero enabled lanes to be structurally READY.

For **live migration preflight**, zero enabled durable lanes are explicitly
`NOT_WIRED`.

This prevents replacing Issue #33 with an empty Control Tower merely because all
placeholder lanes are disabled.

## Notification separation

The preflight preserves the existing notification rule:

- a BLOCKED display state alone does not create a comment;
- a notification is prepared only when the durable event kind is explicitly
  `TURN_COMPLETE` or `HUMAN_NEEDED`;
- ETA OVERDUE remains presentation-only and creates no notification.

## Semi-Auto schedule safety

A Semi-Auto schedule hint may be attached only after durable lane registration.

The existing Control Tower renderer still enforces:

- schedule hints only on SEMI_AUTO presentation lanes;
- ETA state does not alter durable runtime state;
- OVERDUE may coexist with SEMI_AUTO;
- no ETA-only HUMAN_NEEDED / takeover / owner-expiry behavior.

## Stable durable loop ID audit

Fresh read-only investigation was performed before this implementation.

### Claude lanes

PR #25 branch `feature/claude-night-loop-prepare` was inspected.

`automation/command_bus/claude_loop.py` accepts `loop_id` as a caller input.
It does not assign a final fixed durable loop ID for:

- Claude -> Gemini;
- Claude -> Claude.

The handover also states both Claude standalone loops are still PREPARE_ONLY /
live-blocked.

Therefore their final stable durable Control Tower IDs remain **UNKNOWN**.

### ChatGPT Semi-Auto

The active semi-auto command branch
`feature/chat-work-command-bus` contains sequential command/status records such
as:

- `relay-dev-loop-039-core-pr3-overlay-runner.json`;
- related `relay-dev-loop-...-status/readback` requests.

Those request documents identify commands/tasks and target branch/head/tree.
They do not contain a durable owner-chain `loop_id`.

The branch has no
`automation/command_bus/loop_owner_events/` directory.

Therefore the human Loop number / command-id suffix must **not** be treated as
the stable durable Control Tower `loop_id`.

### Work -> Gemini

Fresh branch discovery found no dedicated Gemini runtime branch and no evidence
establishing a final stable durable `Work -> Gemini` loop ID.

Therefore:

`CONTROL-TOWER-REAL-LOOP-IDS-001 = UNKNOWN`

remains correct.

## Roadmap sequencing

The Control Tower v2 roadmap in open PR #72 states:

- CT-3 Dynamic Development lanes begins **after runtime migration is stable**;
- CT-4 real multi-loop integration begins only after real loops expose stable
  durable loop IDs.

Accordingly this batch does not start CT-3 and does not live-migrate Issue #33.

## Tests

Added coverage for:

- current repository placeholder registry + no durable inventory -> NOT_WIRED;
- all enabled lanes required before plan creation;
- one exact durable lane -> READY model + Issue plan;
- UNKNOWN durable transition -> NOT_WIRED;
- durable loop-id mismatch -> BLOCKED;
- zero enabled lanes -> NOT_WIRED for live migration;
- unregistered presentation metadata -> BLOCKED;
- unsafe target/event metadata -> BLOCKED;
- overdue Semi-Auto schedule remains runtime SEMI_AUTO with no notification;
- BLOCKED display alone does not invent HUMAN_NEEDED;
- explicit durable HUMAN_NEEDED event prepares one notification;
- unusable Issue readback -> UNKNOWN after durable gates.

## Explicitly not performed

- no Issue #33 PATCH;
- no Issue comment POST;
- no workflow_dispatch;
- no owner/state/receipt/evidence/provider mutation;
- no Jules/Claude/Gemini/provider/model execution;
- no real takeover;
- no placeholder ID promotion;
- no CT-3 Development migration;
- no Windows executable;
- no default-branch direct write;
- no Merge in this batch.

## Remaining live boundary

The new preflight is expected to remain `NOT_WIRED` with the current four
placeholder registry IDs.

Live Issue #33 migration remains blocked until the real loops expose stable
durable IDs and existing durable transition verification returns accepted
`TransitionProjectionResult` values under those exact IDs.

## Exact-head verification

- exact tested PR head:
  `6d540692d1af8e62cf02bc5bd42ea82ac02fb185`
- GitHub Actions run:
  `36384877964` — **SUCCESS**
- focused Status/runtime/validation suite:
  **246/246 PASS**
- full command-bus suite:
  **571/571 PASS**
- command-bus JSON schemas parsed:
  **20/20 PASS**
- Python compileall:
  **PASS**
- `git diff --check`:
  **PASS**
- representative live-preflight tests were present in the exact-head CI log:
  - repository placeholder registry without durable inventory -> NOT_WIRED;
  - all enabled lanes require exact durable transitions before plan;
  - exact durable lane -> READY model + Issue plan;
  - zero enabled lanes cannot live-migrate;
  - ETA OVERDUE remains presentation-only and creates no notification;
  - unusable Issue readback -> UNKNOWN after durable gates.
- tested head -> current head compare:
  to be read back after this documentation-only evidence commit.
- Issue #33 live mutation:
  **NONE required; fresh readback must remain the deployed single-loop STOPPED display.**
