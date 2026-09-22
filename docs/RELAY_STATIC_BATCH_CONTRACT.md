# Relay static batch contract

The command bus has two distinct Relay static actions under the fixed profile
`RELAY_SAFETY_BATCH_V1`.

## Prepare-only action

`APPLY_RELAY_STATIC_BATCH`

- `execution_mode=PREPARE_ONLY`
- `requires_github_write=false`
- validates a future Work handoff
- never modifies PR #4

## Bounded static-write action

`EXECUTE_RELAY_STATIC_BATCH`

- `execution_mode=STATIC_WRITE`
- `requires_github_write=true`
- only authorizes Work to modify the exact target PR after all target-head,
  state, correlation, path, predecessor, expiry and replay gates pass
- never authorizes Jules or a live provider/model

Both actions compare only `expected_target_head` with current PR #4 head.
PR #6 is a dynamic carrier and its head is never a correctness input.

The allowed path specification is limited to:

- `src/relay/**`
- `src/providers/**`
- `tests/relay/**`
- `docs/RELAY_STATIC_CHECKPOINT.md`
- `RELAY_JULES_HANDOFF.md`

The required prohibited scope includes main, `phase0-runs/**`, secrets,
`.github/**`, settings, workflows, billing, auth and API-key paths.

The only permitted test command sequence is fixed in code:

1. `PYTHONPATH=src python -m pytest -q tests`
2. `python -m compileall -q src tests`
3. `git diff --check`

A command-supplied arbitrary shell command is rejected. Missing or mismatched
loop/round/correlation IDs, duplicate commands, terminal receipts, STOP,
HALTED/EXPIRED state, missing predecessor, target-head mismatch, unsafe path
scope, retry other than zero, enabled fallback, unsupported profile or live
model execution all fail closed.

The code-level validator does not itself write GitHub. A Work event handler must
independently enforce this contract before any `EXECUTE_RELAY_STATIC_BATCH`
target write and must produce durable receipt/state evidence afterward.
