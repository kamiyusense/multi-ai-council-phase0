# Phase 0 Control Tower v2 — CT-1 static foundation checkpoint

## Source / baseline

- Repository: `kamiyusense/multi-ai-council-phase0`
- Baseline main:
  `f4b14faeb94de4ce2ec4ba1699bf05d9cec7a1ec`
- Roadmap source at implementation start:
  PR #72 `docs(status): add Control Tower v2 and Windows companion roadmap`
- PR #72 head read at start:
  `e8c227167df362b194aad0c3e7749d918741c3e9`
- Design sources:
  - `docs/PHASE0_CONTROL_TOWER_V2_ROADMAP.md`
  - `docs/SIGNAL_DEVELOPER_CONTROL_TOWER_V2_CHANGE_REQUEST.md`

PR #72 was still OPEN at the start of CT-1. Those documents were read from the
fresh PR #72 head. GitHub current state remains authoritative.

## CT-1 boundary

This batch implements static presentation foundation only.

It does not:

- mutate live Issue #33;
- dispatch the Status workflow;
- acquire/release/handoff an owner;
- write runtime state/receipt/evidence/provider observation;
- start Jules/Claude/Gemini/Work/model execution;
- create a Windows executable;
- add Temporal/Dagster/Langfuse/Electron/Tauri/backend/database dependencies.

## Static registry

Added:

- `automation/command_bus/config/control_tower_registry.json`
- `automation/command_bus/schema/control_tower_registry.schema.json`

The initial bounded registry carries four presentation lanes:

1. ChatGPT Semi-Auto — ChatGPT -> Jules
2. Claude -> Gemini
3. Claude -> Claude
4. Work -> Gemini

Registry data is presentation metadata only.

Allowed entry fields are exactly:

- `loop_id`
- `display_name`
- `mode`
- `controller_kind`
- `worker_kind`
- `display_order`
- `enabled`
- `safe_detail_ref`

The registry cannot carry runtime state, owner generation/fencing truth,
`verified=true`, provider liveness, credentials/API keys/cookies, or private
ChatGPT/Claude/Work URLs.

Maximum registered loops: 8.

## Validation scope

`automation/command_bus/config/` is explicitly classified as STATIC.

Unknown nested command-bus areas still classify UNKNOWN and the existing
bounded-static validation remains fail-closed.

## Pure multi-loop model / renderer

Added `automation/command_bus/control_tower.py`.

The Control Tower does **not** decide durable ownership/liveness.

Input is an already verified per-loop `StatusProjection` plus bounded
presentation fields such as generation / safe target ref / durable event
identity.

Flow:

```text
existing durable transition verification
-> per-loop StatusProjection
-> ControlTowerModel
-> aggregate title + human Markdown + machine JSON
```

A missing or malformed lane input becomes UNKNOWN for that lane only. Healthy
independent lanes remain visible.

The static registry's `mode` does not override the verified per-loop
`display_state`. Example: a registry lane configured as mode=AUTO may render
IDLE when the verified projection is IDLE.

## Human rendering

The pure renderer provides:

- aggregate count title;
- HUMAN NEEDED section before the normal table;
- independent runtime-lane table;
- explicit controller -> worker presentation;
- mode separate from runtime display state;
- bounded target/generation/event fields;
- Development managed block preservation.

The title uses counts rather than an invented global owner.

## Machine-readable snapshot

The same in-memory `ControlTowerModel` produces both human Markdown and the
bounded JSON snapshot.

Marker:

`<!-- phase0-control-tower-json:v1 ... -->`

Snapshot fields include:

- schema_version
- project
- generated_at
- loop_id
- display_name
- mode
- display_state
- controller_kind
- worker_kind
- generation
- target_ref
- last_event_kind
- last_event_id
- human_action
- safe_detail_ref

Private URLs are not accepted.

## Notification foundation

CT-1 does not post comments.

The pure notification dedupe marker accepts only:

- TURN_COMPLETE
- HUMAN_NEEDED

and binds:

`kind + loop_id + durable event_id`

RUNNING notification markers are rejected.

## Regression coverage

Added tests cover:

- repository registry/schema contract;
- zero enabled lanes;
- one verified lane;
- mixed SEMI_AUTO + AUTO + IDLE + BLOCKED lanes;
- one malformed/missing lane becoming UNKNOWN without erasing healthy lanes;
- registry mode remaining presentation metadata rather than runtime truth;
- human Markdown and machine snapshot generated from the same model;
- Development block preservation;
- runtime-truth/private-URL/unknown-field registry rejection;
- duplicate/overflow registry rejection;
- loop-specific durable-event notification dedupe;
- invalid generated timestamp;
- mismatched lane identity;
- config path classified STATIC while unknown nested areas remain fail-closed.

## Live Issue #33

CT-1 contains no code path that writes Issue #33.

The existing deployed single-loop Issue #33 must remain unchanged during this
batch.

Live migration from single-loop Status to Multi-loop Control Tower belongs to
CT-2 and remains the next major boundary after CT-1 is green.

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
