# Work Command Bus Runtime Contract

Status: canonical runtime contract for the Phase 0 GitHub -> Work/Luna event worker.

Repository: `kamiyusense/multi-ai-council-phase0`

Carrier:
- PR #6
- branch `feature/chat-work-command-bus`

Target:
- PR #4
- branch `feature/relay-transport-7070955470193506982`

## 1. Identity

PR #6 is a dynamic carrier. Its head may advance whenever command/state/
receipt/evidence records are appended. Never compare it to a stored fixed
carrier SHA.

PR #4 is the mutation target. Every target-aware command must compare the
fresh PR #4 head to `expected_target_head`. Commands carrying
`expected_target_tree` must also compare the fresh PR #4 commit tree.

Chat IDs, thread IDs, conversation IDs, browser session IDs, Jules task IDs,
and disposable Work session IDs are never correctness inputs.

## 2. Global safety

Always:
- retry = 0
- fallback = disabled
- process at most one logical command per run
- never replay a command with a terminal receipt
- terminal/closed states are NO-OP
- ambiguity or unverifiable readback is UNKNOWN, not PASS

Never:
- Merge
- direct write to main
- force push
- branch deletion
- Jules start except the single bounded `JULES_BOUNDED_STATIC_ROUNDTRIP` action defined below
- live provider/model start other than that explicitly authorized single Jules action
- live Browser reviewer POC
- API key creation/use
- package installation
- Billing/Credits/Overages mutation
- settings/permissions mutation
- destructive cleanup of a persistent workspace

## 3. Command selection

Prefer the exact command created by the triggering PR #6 event when that event
identity is available.

Otherwise select at most one command whose matching state is RUNNING and has no
terminal receipt.

Ignore COMPLETE, UNKNOWN, HALTED, FAILED, EXPIRED, and any loop already having
a terminal receipt.

Validate:
- repository and target PR
- target=work
- loop / round / correlation
- state RUNNING
- stop_requested=false
- max_rounds<=6
- unexpired command/state
- retry=0
- fallback=disabled
- requires_live_model=false, except `JULES_BOUNDED_STATIC_ROUNDTRIP` which requires true
- duplicate/replay guard

## 4. ECHO_AND_RECEIPT

No target mutation.

Fresh-read PR #4 and require `expected_target_head`.

If valid, write one DONE receipt and set only the matching state COMPLETE.
Receipt must record executed_once=true, observed target head, retry_count=0,
fallback_used=false, and no external/live execution.

Read back receipt/state. Any ambiguous write is UNKNOWN; do not resend.

## 5. STATIC_VALIDATE_COMMAND_BUS

No PR #4 mutation.

Fresh-read current PR #6 commit/tree and require recursive Git tree
`truncated=false`.

Partition `automation/command_bus/**` using
`automation/command_bus/validation_scope.py`.

STATIC:
- direct `automation/command_bus/*.py`
- `automation/command_bus/README.md`
- `automation/command_bus/tests/**`
- `automation/command_bus/schema/**`

LEDGER:
- commands/**
- events/**
- evidence/**
- receipts/**
- state/**
- review_requests/**
- review_claims/**
- review_responses/**
- review_receipts/**
- review_wake_attempts/**
- execution_requests/**
- execution_claims/**
- execution_results/**
- execution_receipts/**
- jules_launch_attempts/**

Any unclassified blob under `automation/command_bus/**` is UNKNOWN.

Fetch and verify every STATIC blob by exact Git blob SHA, including zero-byte
files. Reconstruct only STATIC paths in an isolated scratch directory. Do not
materialize the full historical ledger.

Read only the active command/state, terminal receipt if present, and explicit
predecessor records needed for the current operation.

Run, with no package install:

```text
python -m unittest discover -s automation/command_bus/tests -v
python -m compileall -q automation/command_bus
git diff --check
```

A deterministic staged equivalent of diff-check is acceptable.

Receipt evidence must include:
- current carrier head tested
- total command_bus blob count
- static blob count
- ledger blob count
- unknown blob count
- verified static blob count
- zero-size static blob count
- unittest count/result
- compileall result
- diff-check result

All PASS => DONE + COMPLETE. Otherwise terminal UNKNOWN/BLOCKED when durable
writing remains available.

## 6. VALIDATE_RELAY_TARGET_WORKSPACE

Read-only target validation.

Require fresh target head and tree to match command expectations.

Reconstruct exact PR #4 tree:
- recursive tree truncated=false
- supported entries only
- every blob fetched by blob SHA
- every blob Git SHA reverified
- modes preserved
- isolated disposable workspace
- resulting `git write-tree` exactly equals target commit tree

Require no unexpected tracked/index/untracked/hidden-index state.

Run:

```text
PYTHONPATH=src python -m unittest discover -s tests -t . -v
python -m compileall -q src tests
git diff --check
```

No package installation.

PASS => DONE + COMPLETE without PR #4 mutation. Any uncertainty => terminal
UNKNOWN/BLOCKED, retry=0.

## 7. EXECUTE_RELAY_STATIC_BATCH

This is the only action permitted to modify PR #4.

Require:
- profile=RELAY_SAFETY_BATCH_V1
- workspace_integrity_profile=TREE_IDENTITY_V1
- execution_mode=STATIC_WRITE
- requires_github_write=true
- concrete expected target head + tree
- exact allowed/prohibited paths
- exact path operation policy
- retry=0 / fallback disabled / live=false
- fixed unittest/compileall/diff commands from section 6

Before mutation, perform the same exact reconstruction/tree identity checks as
section 6 and run the baseline tests.

Only allowed-path ADD/MODIFY operations are permitted unless DELETE/RENAME are
explicitly present in the command policy.

Preserve:
- cancel/abort scoped to intended provider/session
- no second prompt/restart after cancel
- STOP blocks new dispatch
- timeout retry=0
- fallback disabled
- peer provider success/raw evidence survives another provider failure
- raw evidence snapshot occurs before classification
- malformed/UNKNOWN never success
- Codex API-key/gateway/non-subscription routes rejected
- Claude dangerous permission bypass false
- Antigravity account/subscription-only and live_ready=false
- ProviderAdapter bridge + three-provider mock integration
- no real provider/model start

Run post-change tests. Fix only deterministic failures caused by the current
allowed diff.

Immediately before commit fresh-read target head/tree again. They must still
match command expectations.

Create at most one normal fast-forward target commit whose parent is exactly
the expected target head. Ambiguous write => read back, never resend.

Verify remote head, parent, tree, changed paths and operations. Then write one
terminal receipt and matching COMPLETE state.

If target commit succeeded but receipt/state writing was interrupted, a later
run may only complete durable receipt/state after exact readback; it must never
create a second target implementation commit.

## 8. JULES_BOUNDED_STATIC_ROUNDTRIP

This is the only Jules launch authorized by the current runtime contract.
It is a one-task probationary round-trip. Larger Jules work is not permitted
until this first round-trip reaches a verified terminal receipt.

Require:
- profile=`JULES_FRESH_STATIC_V1`
- user_authorization=`EXPLICIT_NEXT_BATCH_JULES_2026-09-23`
- target PR #4
- concrete expected_target_head + expected_target_tree
- workspace_integrity_profile=`TREE_IDENTITY_V1`
- fresh_session_required=true
- disposable_workspace_required=true
- reuse_existing_jules_task=false
- retry=0
- fallback=disabled
- requires_live_model=true
- requires_github_write=true
- launch_route=`WORK_CLOUD_BROWSER_JULES_UI`
- starting_branch=`feature/relay-transport-7070955470193506982`
- issue_label_launch=false
- branch_selection_evidence_required=true
- exactly one allowed path: `tests/relay/test_dispatcher.py`
- only operation: MODIFY
- no implementation-file modification
- fixed tests:
  - `PYTHONPATH=src python -m unittest discover -s tests -t . -v`
  - `python -m compileall -q src tests`
  - `git diff --check`

Before launch:
1. Fresh-read PR #4 current head/tree and require exact command match.
2. Reconstruct the target in a new disposable workspace.
3. Enforce TREE_IDENTITY_V1: exact HEAD/tree/index/tracked worktree, no
   unexpected untracked files, no hidden index flags.
4. Run baseline tests.
5. Append exactly one durable launch reservation at
   `automation/command_bus/jules_launch_attempts/<loop>/<command_id>.json`
   and read it back.
6. Open Jules only through Work Cloud Browser. Do not use a GitHub Issue
   `jules` label for this non-default target.
7. In the Jules repo/branch selector, choose repository
   `kamiyusense/multi-ai-council-phase0` and exact starting branch
   `feature/relay-transport-7070955470193506982`.
8. Before submitting the task, capture durable evidence that the exact branch
   was selected. UI text alone is transport evidence, not final correctness;
   the resulting commit parent/tree must still be verified after publication.
9. Only the same Work run that created and verified the fresh launch
   reservation may start Jules. A recovered reservation never authorizes a
   second launch.

First Jules task:
- fresh Jules session only
- source must be the exact non-default branch selected in Jules UI
- never fall back to `main`; if exact branch selection is unavailable or
  unverifiable, stop BLOCKED/UNKNOWN before task submission
- never reuse an old Jules task/workspace
- add one unittest regression proving `abort_signal={"aborted": True}`
  blocks before slot reservation and provider dispatch
- modify only `tests/relay/test_dispatcher.py`
- do not modify implementation code
- do not Merge
- do not write main
- do not force push
- do not change settings/permissions/billing/API keys
- do not start any provider/model other than the Jules implementation session

After Jules change:
1. Verify changed path/operation is exactly the allowed MODIFY.
2. Run the fixed post-change tests.
3. Require commit parent == expected_target_head.
4. Verify remote target head/tree/diff.
5. Write one terminal receipt/state.

Ambiguity => UNKNOWN. Never start Jules a second time. retry=0; fallback
disabled.

## 9. Workspace failure policy

Gate failure blocks only the affected executor mutation.

Continue:
- GitHub readback
- evidence preservation
- independent read-only validation
- independent safe work
- authorized recreation of a disposable workspace

Persistent suspect workspaces are quarantined. Never repair them automatically
with reset --hard, git clean, rebase, auto-stash, or auto-commit.

## 10. Reviewer relay boundary

`DURABLE_REVIEW_V2` and reviewer wake records may be statically/mock
validated.

No live Browser/Chat/model transport is authorized by this contract.

Browser/Direct/Manual transport is only a wake mechanism. Free-form UI output
is not a correctness source. Only a durable GitHub `review_response` may be
consumed as the reviewer result.

Wake attempts use one append-only canonical reservation per request:
`review_wake_attempts/<loop>/<request_id>.json`.

A recovered reservation never authorizes a second external wake.
