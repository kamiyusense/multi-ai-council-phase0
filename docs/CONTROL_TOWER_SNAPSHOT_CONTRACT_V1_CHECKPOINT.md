# Control Tower machine snapshot contract v1 — checkpoint

## Baseline

Repository:
`kamiyusense/multi-ai-council-phase0`

Baseline main:

`c5501976ab0779fea26f6c58aa4ca49d3c6060be`

Fresh readback showed PR #89 had advanced main after PR #88 by changing only
`.github/workflows/loop-status-signal-test.yml` to keep focused tests
compatible with older PR heads.

Issue #33 remained:

`🚦 Phase 0 Loop Status — ⚫ STOPPED`

with zero comments.

## Problem

Control Tower v2 already emitted a bounded machine-readable JSON block inside
Issue #33:

`<!-- phase0-control-tower-json:v1 ... -->`

and a dedicated schema existed for nested Semi-Auto schedule hints.

However, there was no formal schema or strict read-only parser for the complete
Control Tower snapshot consumed by a future Windows Signal Companion.

Without a strict consumer contract, the Windows side could drift into:

- accepting unknown fields;
- accepting private URL-bearing values;
- silently interpreting malformed timestamps;
- reconstructing runtime correctness from presentation data;
- accepting multiple/conflicting machine snapshot markers;
- tolerating an unbounded number of lanes.

## Added machine snapshot schema

Added:

`automation/command_bus/schema/control_tower_snapshot.schema.json`

Top-level fields are exactly:

- `schema_version`
- `project`
- `generated_at`
- `loops`

The snapshot is fixed to:

- `schema_version = 1`
- `project = phase0`
- maximum 8 lanes.

Each lane is bounded to the exact presentation fields already emitted by the
Control Tower renderer:

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
- schedule_hint
- human_action
- safe_detail_ref
- identity_state

The nested schedule hint references the existing
`control_tower_schedule_hint.schema.json`.

The schema contains no:

- owner chain;
- fencing token;
- provider liveness proof;
- credential/API key;
- private URL;
- takeover command.

## Added strict read-only parser

Added:

`automation/command_bus/control_tower_snapshot.py`

The parser:

- performs no GitHub/provider writes;
- performs no owner/takeover action;
- derives no runtime correctness;
- accepts exactly one v1 marker from an Issue body;
- rejects missing or multiple markers;
- rejects malformed JSON;
- rejects unknown top-level or lane fields;
- rejects more than 8 lanes;
- rejects duplicate loop IDs;
- requires timezone-aware generated_at;
- validates bounded mode/state/controller/worker/identity enums;
- validates generation and safe target/detail refs;
- validates durable event labels/ids;
- validates nested Semi-Auto schedule hints with the existing schedule validator;
- rejects schedule hints on AUTO presentation lanes;
- rejects URL-like lane content.

Maximum machine snapshot size is 64 KiB.
Maximum Issue body size accepted by the read-only parser is 256 KiB.

These are parser safety bounds, not runtime timeout or correctness rules.

## Windows Signal Companion boundary

The future Windows Signal Companion may use this parser/schema to render a
compact tray/flyout view.

It must continue to treat the snapshot as **presentation only**.

In particular:

```text
snapshot display_state
snapshot generation
snapshot identity_state
snapshot eta_state
```

must not independently trigger:

- owner acquisition/release;
- fencing changes;
- provider-dead inference;
- retry;
- takeover;
- GitHub write.

Windows remains read-only.

## Empty snapshot behavior

A v1 snapshot with zero loops is structurally valid presentation JSON.

That does **not** mean runtime registration is READY.

The already-merged live migration preflight separately rejects zero enabled
durable lanes.

Therefore:

```text
snapshot parser accepts []
!=
live migration readiness
```

The read-only display contract and durable registration contract remain
separate.

## Fixture / tests

Added fixture:

`automation/command_bus/tests/fixtures/control_tower_snapshot/v1_semi_overdue.json`

It represents a Semi-Auto lane with:

- runtime display_state = SEMI_AUTO;
- identity_state = PLACEHOLDER;
- task_size = MEDIUM;
- eta_state = OVERDUE.

Added regression coverage for:

- repository fixture strict parsing;
- actual renderer -> Issue marker -> parser round trip;
- exact bounded schema fields;
- missing/multiple marker rejection;
- unknown top-level/lane field rejection;
- private/URL-like value rejection;
- malformed schedule rejection;
- schedule on AUTO lane rejection;
- >8 lanes rejection;
- duplicate loop-id rejection;
- naive generated_at rejection;
- bounded identity_state behavior;
- empty snapshot presentation parsing.

## Explicitly not performed

- no Issue #33 mutation;
- no workflow_dispatch;
- no provider/model execution;
- no runtime ledger mutation;
- no takeover;
- no final durable loop ID assignment;
- no CT-3 Development migration;
- no Windows executable;
- no GitHub write capability for Windows;
- no Merge in this batch.

## Exact-head verification

- exact tested PR head:
  `62951fa9955f87c39d0df0af9d75e4b1f40e9e9e`
- GitHub Actions run:
  `36388458286` — **SUCCESS**
- focused Status/runtime/validation suite:
  **260/260 PASS**
- full command-bus suite:
  **585/585 PASS**
- command-bus JSON schemas parsed:
  **21/21 PASS**
- Python compileall:
  **PASS**
- `git diff --check`:
  **PASS**
- representative snapshot-contract tests were present in the exact-head CI log:
  - renderer output round-trips through the strict read-only parser;
  - missing/multiple snapshot start markers fail closed;
  - private/URL-like values fail closed;
  - unrelated managed HTML comment closers after the snapshot are accepted.
- initial failed run:
  `36388369726` failed because the parser incorrectly treated unrelated managed
  block comment closers as duplicate snapshot closers. No write/retry was
  performed against live Issue #33. The parser was corrected to scope the
  closing marker to the unique Control Tower start marker and the new exact
  head was re-tested.
- tested head -> current head compare:
  to be read back after this documentation-only evidence commit.
- Issue #33 live mutation:
  **NONE required; fresh readback must remain the deployed single-loop STOPPED display.**
