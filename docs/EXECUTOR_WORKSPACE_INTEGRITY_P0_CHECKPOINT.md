# Executor Workspace Integrity Gate — P0 Checkpoint

Updated: 2026-09-23
Repository: `kamiyusense/multi-ai-council-phase0`
Branch: `feature/chat-work-command-bus`
Target PR for identity checks only: PR #4
Status: IMPLEMENTED / VALIDATED

## Scope

This checkpoint implements the P0 subset of
`docs/EXECUTOR_WORKSPACE_INTEGRITY_GATE_PROPOSAL.md` as a provider-neutral
executor safety gate. It does not start Jules, Codex, Claude, Antigravity, or
any live provider/model. It does not modify PR #4.

## Canonical heads observed

- PR #6 P0 starting head observed: `49c77a8d34561caa6172644a2bfdbcdf9f963619`
- PR #6 current branch head at checkpoint preparation:
  `5de4307cbe04d9ed782ff65bc07680926696299a`
- PR #4 current head:
  `ffcdff208d12620d423592df78af1fd1eb88950e`
- PR #4 verified recovery tree:
  `62e681613be4de68ee5987634a075078f6bb522a`

PR #4 remained unchanged throughout this P0 implementation batch.

## Implemented P0

### Common workspace gate

Added `automation/command_bus/workspace_integrity.py` with
`TREE_IDENTITY_V1`.

The pre-mutation attestation validates:

- repository / PR / target branch identity
- remote name and remote URL identity
- concrete workspace path / Git toplevel
- Git dir and common-dir availability
- observed HEAD equals `expected_target_head`
- observed HEAD tree equals `expected_target_tree`
- observed index tree equals `expected_target_tree`
- tracked worktree is clean
- cached/index diff is clean
- unexpected untracked paths are absent
- unmerged entries are absent
- skip-worktree paths are absent
- assume-unchanged paths are absent
- sparse checkout is disabled unless a future explicit profile supports it
- unsupported submodule state fails closed

Missing or unverifiable required observations produce `UNKNOWN / NO_MUTATION`.

Persistent dirty/uncertain workspaces return a quarantine disposition and are
not reset, cleaned, rebased, stashed, or auto-committed. Disposable stale
workspaces return `RECREATE_REQUIRED`; the allowed recovery is creation of a
new disposable workspace followed by a full new attestation, not repair in
place.

### Mutation / admission gates

Implemented:

- short-lived mutation lease bound to head/tree, executor generation,
  workspace attestation, and path policy
- immediate precommit target-head/tree revalidation
- fixed per-path operation policy with distinct ADD/MODIFY/DELETE/RENAME
  capabilities
- DELETE/RENAME denied unless explicitly listed
- tests / compile / diff evidence required before commit admission
- commit parent must equal expected target head
- commit tree must equal the already-admitted candidate index tree
- commit changed paths/operations must satisfy path policy
- remote readback validates PR head, remote commit, parent, tree, and operations
- ambiguous remote write/readback becomes UNKNOWN; no automatic retry
- retry count remains 0; fallback remains disabled

### Durable executor contract

Extended the existing executor protocol with backward-compatible integrity
fields:

Request:
- `expected_target_tree`
- `requires_clean_workspace`
- `workspace_integrity_profile`
- `path_policy`
- `mutation_lease_ttl_seconds`

Claim (optional all-or-none integrity binding):
- `workspace_attestation_id`
- `workspace_path_fingerprint`
- `observed_head`
- `observed_tree`
- `observed_index_tree`

Result:
- concrete expected target tree
- workspace / commit attestation refs
- mutation lease id
- mutation_started
- target_head_revalidated
- push_attempted
- remote_readback_verified

The durable backend compares concrete target-tree identity in addition to
loop/round/correlation/target-head identity. Legacy PREPARE_ONLY records may
retain `expected_target_tree=UNKNOWN`; a mutating executor must use a concrete
target tree.

### Relay static-write contract

`EXECUTE_RELAY_STATIC_BATCH` now requires:

- concrete `expected_target_tree`
- exact operation policy
- no DELETE or RENAME in the current Relay P0 profile

Current allowed operation policy:

- `src/relay/**`: ADD, MODIFY
- `src/providers/**`: ADD, MODIFY
- `tests/relay/**`: ADD, MODIFY
- `docs/RELAY_STATIC_CHECKPOINT.md`: MODIFY
- `RELAY_JULES_HANDOFF.md`: MODIFY

## Regression fixtures added

`automation/command_bus/tests/test_workspace_integrity.py` covers the P0
matrix including:

- exact clean workspace PASS
- correct HEAD/tree but stale tracked working file BLOCK
- correct HEAD but stale index tree BLOCK
- unexpected untracked path BLOCK
- assume-unchanged BLOCK
- skip-worktree BLOCK
- unsupported sparse checkout BLOCK
- wrong repo/remote/worktree/branch BLOCK
- stale base BLOCK
- missing/unknown observation -> UNKNOWN
- dirty persistent workspace -> quarantine/no destructive repair
- stale disposable workspace -> recreate/new workspace, no in-place repair
- target movement after attestation -> BLOCK
- lease expiry -> BLOCK
- changed path outside allowlist -> BLOCK
- DELETE inside broad allowed path -> BLOCK by operation policy
- RENAME without explicit policy -> BLOCK
- commit parent mismatch -> BLOCK
- commit tree mismatch -> BLOCK
- ambiguous push/readback -> UNKNOWN
- verified remote readback -> PASS

The dedicated Jules-incident regression fixture reproduces the essential
failure shape:

```text
HEAD == expected target head
HEAD tree == expected target tree
index tree == expected target tree
tracked working-tree bytes are stale/different
```

Expected result: BLOCK before a mutation lease can be issued.

`test_executor_workspace_contract.py` additionally verifies durable
head+tree binding and recovery rejection of a mismatched target tree.

## Validation evidence

Earlier validation commands were handled fail-closed under retry=0:

1. `workspace-integrity-p0-validation-001`
   - event run produced no durable terminal evidence
   - state closed as UNKNOWN
   - not replayed

2. `workspace-integrity-p0-validation-002`
   - event runner did not start before the implementation changed
   - state closed as UNKNOWN to prevent delayed stale validation
   - not replayed

Fresh validation `workspace-integrity-p0-validation-003` then executed against
carrier head `f1edb91c7bbcf9cd99409cc0eb0e1b1332b1f8cc`.

Durable terminal receipt:

`automation/command_bus/receipts/workspace-integrity-p0-validation-003/000001.json`

Results:

- exact tree/blob acquisition: PASS
- verified blobs: 79
- empty blobs: 1
- `python -m unittest discover -s automation/command_bus/tests -v`:
  **104 PASS / 0 FAIL**
- `python -m compileall -q automation/command_bus`: **PASS**
- `git diff --check`: **PASS**
- target head observed: `ffcdff208d12620d423592df78af1fd1eb88950e`
- PR #4 modified: NO
- live/Jules/external send: NO
- retry: 0
- fallback: disabled

An independent isolated reconstruction of the exact P0-modified Git blobs also
ran the focused regression set:

- workspace integrity: 28 PASS
- existing executor/backend + integrity contract: 27 PASS
- Relay static contract: 14 PASS
- total focused tests: **69 PASS / 0 FAIL**
- compileall: PASS
- staged `git diff --check`: PASS

This independently confirms the Jules-incident regression fixture blocks the
correct-HEAD / stale-tracked-worktree shape before a mutation lease is issued.

Append-only evidence:

`automation/command_bus/evidence/workspace-integrity-p0-20260923.json`

## Safety state

- PR #4 modified: NO
- Jules started: NO
- live provider/model started: NO
- API key used/created: NO
- Billing/Credits/Overages changed: NO
- settings/permissions changed: NO
- Merge performed: NO
- main direct write: NO
- force push: NO
- branch deletion: NO
- retry: 0
- fallback: disabled

## Remaining boundary / next safe action

P0 implementation and regression validation are PASS.

No PR #4 mutation is authorized by this checkpoint. Before a future mutating
executor is allowed to write, its runtime path must consume a concrete
`expected_target_tree`, run TREE_IDENTITY_V1 against the actual executor
workspace, obtain a mutation lease, revalidate target head/tree immediately
before commit, apply the path+operation policy, verify commit parent/tree/diff,
and perform remote readback.

A workspace Gate failure blocks only that executor's mutation. Read-only
GitHub verification, evidence preservation, independent safe work, and
authorized disposable-workspace recreation remain allowed. Persistent
workspaces are quarantined rather than destructively repaired.

