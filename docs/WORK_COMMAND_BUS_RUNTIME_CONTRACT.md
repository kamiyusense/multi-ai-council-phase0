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

Fetch every STATIC blob through the connected GitHub transport. Do not require
the local container to clone/fetch from github.com.

For every STATIC blob:
- require the connector-returned blob SHA to match the recursive tree entry
- recompute the Git blob SHA from the returned bytes
- require byte length to match the tree entry size
- preserve supported file mode
- include zero-byte blobs
- reject path traversal, duplicate paths, symlinks, or unsupported modes

Use `automation/command_bus/connector_reconstruction.py` as the deterministic
verification helper.

Materialize only the verified STATIC paths into a new isolated local scratch
directory. A local `git init` is allowed solely for deterministic local
diff-check/write-tree style verification; it must not add a remote or contact
the network. Do not materialize the full historical ledger.

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

## 7A. JULES_BRANCH_SELECTOR_PREFLIGHT

No Jules task submission and no model execution.

Purpose:
prove that Work Cloud Browser can open the Jules web UI and explicitly select
the exact non-default Relay target before any live Jules task is attempted.

Require:
- target=work
- action=`JULES_BRANCH_SELECTOR_PREFLIGHT`
- expected repo = `kamiyusense/multi-ai-council-phase0`
- expected PR = 4
- concrete expected target head/tree
- launch_route=`WORK_CLOUD_BROWSER_JULES_UI`
- starting_branch=`feature/relay-transport-7070955470193506982`
- issue_label_launch=false
- requires_live_model=false
- requires_github_write=true
- retry=0
- fallback=disabled

Execution:
1. Fresh-read PR #4 head/tree and require exact command match.
2. Open Jules only through Work Cloud Browser.
3. Navigate to the normal Jules task creation UI.
4. Select repository `kamiyusense/multi-ai-council-phase0`.
5. Select exact branch
   `feature/relay-transport-7070955470193506982`.
6. Verify the selected repository and branch are visibly reflected in the task
   creation UI before any prompt is submitted.
7. Do **not** submit/start the task.
8. Write durable evidence with the observed repository, observed branch,
   whether the selector was explicit, whether any task was submitted, and
   whether any model/Jules task started.
9. PASS only when repo+branch are exact and no task was submitted.
10. Any auth problem, missing branch, ambiguous selector state, or UI
    uncertainty => terminal BLOCKED/UNKNOWN; no task submission.

Authentication gate rule:
- a Google account chooser / sign-in requirement is a human-auth gate, not an
  executor retry;
- close the current preflight terminal BLOCKED/UNKNOWN and never replay it;
- do not create a replacement command until the user completes sign-in;
- after sign-in, fresh-read PR #4 head/tree and create a new logical command
  identity bound to that fresh target;
- browser/session identity and remembered login state are transport context,
  never correctness inputs;
- even with a persisted login, exact repo + branch selection evidence is still
  required before task submission.

This preflight proves only UI branch-selection capability. It does not prove a
future Jules commit will have the correct parent. Final correctness still
requires the post-publication ancestry/tree checks in section 8.

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

## 7B. DUAL_BROWSER_TRANSPORT_STATIC_V1

Status: **STATIC IMPLEMENTED / LIVE PREFLIGHT PENDING**.

This section adds a transport-level dual-browser contract for Jules UI access.
It does not authorize a browser launch, Google sign-in, Jules submission, or
model execution.

Logical transport identities:
- `WORK_CLOUD_BROWSER_JULES_UI`
- `WORK_COMPUTER_USE_JULES_UI`

The second identity is a protocol identity only. Current runtime capability for
Computer Use is `UNKNOWN` until a Work runtime exposes/verifies that capability.

Invariants:
- transport replacement is not provider/model fallback;
- a command binds exactly one `transport_id`;
- the same `command_id` must never switch transport;
- a secondary transport requires a new command identity, correlation,
  generation, expiry, durable request/evidence record, and wake/attempt record;
- the new command may reference the old command only through
  `predecessor_command_id`;
- `retry=0` and `fallback=disabled` remain unchanged;
- a recovered/terminal command never authorizes a new external send;
- stale generation or wrong transport results are rejected;
- browser UI is transport evidence only, never the final correctness source;
- authentication remains a human-controlled boundary and credentials/tokens/
  cookies/password/MFA data must not be persisted.

A successor transport is eligible only when durable evidence proves all of:
- predecessor command is terminal;
- terminal receipt is present and bound to the predecessor;
- `task_submitted == false`;
- `jules_task_started == false`;
- `model_started == false`;
- `external_action_uncertainty == false`;
- `github_mutation_possible == false`;
- fresh PR #4 head/tree equal the predecessor expectations and observations.

If any external action, task start, model start, GitHub mutation, target identity,
receipt, or terminality is UNKNOWN, the result is `MUST_NOT_REDISPATCH`.

Static implementation:
- `automation/command_bus/browser_transport.py`
- `automation/command_bus/tests/test_browser_transport.py`
- `automation/command_bus/schema/browser_transport_evidence.schema.json`

The static adapters never open a browser and never submit/start Jules. A live
preflight remains a separate fresh command.


## 7C. JULES_BROWSER_TRANSPORT_PREFLIGHT

Status: **USER-AUTHORIZED NO-SUBMIT LIVE PREFLIGHT (2026-09-24)**.

Purpose:
prove browser transport capability and exact non-default branch selection before
any Jules task/model start. This authorizes browser navigation only, not task
submission, Jules/model start, credential handling, settings/permission
changes, retry, or fallback.

Supported transport identities:
- `WORK_CLOUD_BROWSER_JULES_UI`
- `WORK_COMPUTER_USE_JULES_UI`

Require:
- action=`JULES_BROWSER_TRANSPORT_PREFLIGHT`
- immutable `transport_id`
- fresh command_id/correlation_id/generation/expiry
- timezone-aware unexpired expiry
- exact PR #4 expected head/tree, repository and starting branch
- requires_live_model=false
- requires_github_write=true
- task_submit=false
- retry=0
- fallback=disabled

Execution:
1. Fresh-read PR #4 head/tree and require exact match.
2. Verify requested browser capability; UNKNOWN remains UNKNOWN.
3. Open Jules UI only through the named transport.
4. Never automate Google password/MFA/account selection or read/store
   credentials, cookies, tokens, or secrets.
5. Authentication required => terminal BLOCKED/UNKNOWN before task submission.
6. If reachable, explicitly select repository
   `kamiyusense/multi-ai-council-phase0`.
7. Explicitly select branch
   `feature/relay-transport-7070955470193506982`.
8. Verify repo/branch selection as transport evidence only.
9. Do not submit prompt/task and do not start Jules/model.
10. Fresh-read PR #4 head/tree after observation.
11. Persist append-only evidence plus terminal receipt/state.

Evidence must bind command/correlation/generation/transport and record repo/
branch expected+observed, explicit selection flags, auth/browser state,
task_submitted, jules_task_started, model_started, target head/tree,
external-action uncertainty, GitHub mutation possibility, retry_count=0,
fallback_used=false, blocker and evidence refs. Sensitive auth material is
forbidden.

Secondary transport requires a new logical command and may be created only
after predecessor terminal proof and `secondary_transport_eligibility()`
returns ALLOWED_NEW_COMMAND. UNKNOWN external action/task/model/GitHub mutation
means MUST_NOT_REDISPATCH.

## 7D. EXACT_REPOSITORY_BRANCH_SELECTION_GATE

Status: **STATIC CONTRACT IMPLEMENTED / LIVE AUTH GATE PENDING**.

Before any Jules task submit, browser automation must use exact full-string
selection for both repository and starting branch.

Required repository:
`kamiyusense/multi-ai-council-phase0`

Required starting branch:
`feature/relay-transport-7070955470193506982`

Algorithm:
1. open repository selector and obtain/search candidates;
2. choose exactly one candidate whose full repository name equals the required
   repository; never choose first(), substring, inferred, or default fallback;
3. read back the selected repository and require exact equality;
4. open branch selector and obtain/search candidates;
5. choose exactly one candidate whose full branch name equals the required
   branch; never choose first(), substring, inferred, or default fallback;
6. read back selected branch and require exact equality;
7. until both exact readbacks pass, task submission remains forbidden.

Static implementation:
- `automation/command_bus/exact_selector.py`
- `automation/command_bus/tests/test_exact_selector.py`

Transport/session identities are distinct protocol identities:
- `WORK_CLOUD_BROWSER_JULES_UI`
- `DESKTOP_BUILTIN_BROWSER_JULES_UI`
- `CHROME_EXISTING_SESSION_JULES_UI`

Existing `WORK_COMPUTER_USE_JULES_UI` records remain valid historical records.
Desktop/Chrome runtime availability is UNKNOWN until a real authorized Work
runtime proves it; UNKNOWN must never be promoted to AVAILABLE.

Google authentication remains a human boundary. No password/MFA/cookie/token/
credential extraction or persistence is authorized.

## 8A. JULES_PUBLICATION_FAST_FORWARD_V1

The preferred publication path is Jules disposable branch -> GitHub readback ->
validated fast-forward of PR #4. Work must not copy files between branches when
a valid descendant commit already exists.

Before moving PR #4, require durable/readback proof:
- resulting commit SHA is concrete;
- its only parent is the frozen `expected_target_head` for the first smoke task;
- PR/comparison base is exact PR #4 branch;
- PR #4 current head is still the frozen expected head;
- changed paths are allowlisted and operations are ADD/MODIFY only;
- no unexpected delete/rename/symlink;
- required tests, compileall and diff-check PASS;
- retry_count=0 and fallback_used=false;
- task submission/Jules/model start evidence is consistent and proven;
- no main/default direct write;
- no unresolved GitHub mutation uncertainty.

Only when all gates PASS and ancestry is fast-forward may PR #4 be moved to the
Jules resulting commit with a non-force ref update. No merge commit, rebase,
cherry-pick, or patch/file transplantation is part of the preferred route.

After ref update, remote readback must verify new head, parent ancestry, tree,
changed paths, base=main unchanged, and no unexpected mutation. Ambiguous write
must be read back, never resent.

Static implementation:
- `automation/command_bus/jules_publication.py`
- `automation/command_bus/tests/test_jules_publication.py`



## 7E. JULES_HUMAN_AUTH_BOOTSTRAP

Status: **USER-AUTHORIZED HUMAN-BOUNDARY BOOTSTRAP / NO JULES SUBMIT**.

Purpose:
create a fresh GitHub-triggered Work run whose only live browser goal is to
reach the Jules Google authentication boundary and surface ChatGPT's native
Cloud Browser sign-in/takeover flow to the human. This is a prerequisite
bootstrap, not a retry of any closed selector preflight.

Require:
- action=`JULES_HUMAN_AUTH_BOOTSTRAP`
- target=work
- exact repository `kamiyusense/multi-ai-council-phase0`
- expected PR = 4
- fresh concrete expected target head/tree
- starting_branch=`feature/relay-transport-7070955470193506982`
- transport_id=`WORK_CLOUD_BROWSER_JULES_UI`
- auth_origin=`jules.google.com`
- fresh command/loop/correlation identity
- requires_live_model=false
- requires_github_write=true
- retry=0
- fallback=disabled
- no terminal receipt for the new command

Execution:
1. Fresh-read PR #4 head/tree and require exact command match.
2. Open Jules through native Work Cloud Browser only.
3. Do not select a repository/branch, submit a Jules task, start Jules/model,
   or mutate PR #4 while authentication is unresolved.
4. If Google authentication is required, first prove that ChatGPT's native
   secure sign-in/takeover entry is actually surfaced on a user-visible
   surface. Merely naming the intended surface `VISIBLE_WORK` is not proof.
5. Only after the user-visible entry is verified visible may append-only
   non-secret auth handoff metadata be created/read back and the loop state be
   set to `WAITING_FOR_HUMAN_AUTH`.
6. Never store or echo the takeover URL, password, MFA, cookie, credential,
   browser-control token, or authentication token.
7. If a user-visible native sign-in/takeover entry is not visible to the human,
   cannot be surfaced, or its availability is unverifiable, close
   BLOCKED/UNKNOWN; do not guess which Work/browser the user should find and do
   not retry.
7. Human interaction may mark the handoff
   `HUMAN_COMPLETED_UNVERIFIED`; this is not authentication PASS.
8. After human completion, discard all pre-auth DOM/selector/page assumptions.
9. Fresh-read PR #4 again and create a NEW exact-selector preflight with a new
   logical identity.
10. Only that fresh preflight may produce `AUTHENTICATED_OBSERVED`, and only
    after it freshly reaches the Jules task-creation UI without an auth gate.
11. Repo and branch must then be selected from fresh observations using the
    exact full-string gate in section 7D; task_submit remains false.

Correctness never depends on a Work/chat/browser session identifier or on
same-run resume. Cloud Browser authentication persistence is convenience only.
A persisted authenticated session still requires a fresh target readback and
fresh exact-selector evidence.

Static implementation:
- `automation/command_bus/auth_handoff.py`
- `automation/command_bus/schema/auth_handoff.schema.json`
- `automation/command_bus/tests/test_auth_handoff.py`
- `docs/JULES_HUMAN_AUTH_BOOTSTRAP.md`
