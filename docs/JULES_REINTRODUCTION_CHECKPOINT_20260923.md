# Jules Reintroduction Checkpoint — 2026-09-23

Repository: `kamiyusense/multi-ai-council-phase0`

Status: **STATIC CONTRACT READY / FIRST LIVE ROUND-TRIP UNKNOWN / TARGET UNCHANGED**

## Canonical heads at checkpoint

PR #4:
- branch: `feature/relay-transport-7070955470193506982`
- head: `2fc399ac7b415746763114c3951aa2e3b45adee7`
- tree: `9e2d22b7caf001449d1a5aa4fd374fec81a415fe`
- state: OPEN

PR #6:
- branch: `feature/chat-work-command-bus`
- dynamic carrier; fresh-read before every action

## New role policy now in force

- Sol Chat: design, semantic review, Jules task design
- Work / Luna: relay, Cloud Browser operation, deterministic validation,
  receipt/readback
- Jules: main implementation role
- GitHub: durable source of truth

The previous blanket Jules prohibition ended only after
`docs/CURRENT_SAFE_BATCH_TERMINAL_CHECKPOINT_20260923.md` and its fresh
readback.

## First bounded Jules contract

Implemented on PR #6:
- `automation/command_bus/jules_static.py`
- `automation/command_bus/jules_launch_backend.py`
- `automation/command_bus/tests/test_jules_static.py`
- `automation/command_bus/validation_scope.py`
- `docs/WORK_COMMAND_BUS_RUNTIME_CONTRACT.md`

Static contract checks: **14/14 PASS**.

The first probationary task is intentionally tiny:
- fresh Jules session only
- disposable workspace only
- TREE_IDENTITY_V1 before mutation
- old Jules task/workspace reuse forbidden
- exactly one modifiable path:
  `tests/relay/test_dispatcher.py`
- MODIFY only
- objective: add one unittest proving pre-dispatch
  `abort_signal={"aborted": True}` blocks before slot reservation and provider
  dispatch
- implementation files forbidden
- retry=0
- fallback disabled

A durable launch reservation is mandatory before Jules may be started:
`automation/command_bus/jules_launch_attempts/<loop>/<command_id>.json`

A recovered reservation never authorizes another launch.

## First round-trip attempt

Command:
`jules-first-roundtrip-001-000001`

The atomic command/state/evidence commit was:
`3c3d9dc8a3deb43766f5f4cbb7fd5cd195a7588b`

The Work command-bus task ran after that commit, but:
- launch reservation: ABSENT
- terminal receipt: ABSENT
- Work-written state transition: ABSENT
- PR #4 head/tree change: NO

Therefore the command was closed as terminal **UNKNOWN** under retry=0.

Do **not** replay command 001.

Because the mandatory pre-launch reservation is absent, an authorized Jules
launch cannot be established. Since the Work runtime returned no durable
execution record, actual live Jules start is **UNKNOWN**, not inferred either
way.

Evidence:
`automation/command_bus/evidence/jules-reintroduction-roundtrip-001-terminal-20260923.json`

## Command-bus hygiene

All 27 current state files were read back.

RUNNING states: **0**

Therefore no old RUNNING command is currently eligible to be accidentally
selected as a fallback command.

## Remaining blocker

The current blocker is the **Work event / durable execution route**, not the
Jules safety contract and not PR #4.

A Work task wake has repeatedly occurred without producing the required durable
receipt/state for recent commands. A second Jules launch must not be attempted
until that runtime route is understood or replaced by a verifiable route.

The next Jules command, when the runtime route is verified, must use a new
command identity. It must not reuse `jules-first-roundtrip-001`.

## Safety state

- PR #4 changed by this Jules attempt: NO
- Merge: NO
- main direct write: NO
- force push: NO
- branch deletion: NO
- API key / Billing / Credits / Overages / settings / permissions changes: NO
- retry: 0
- fallback: disabled
