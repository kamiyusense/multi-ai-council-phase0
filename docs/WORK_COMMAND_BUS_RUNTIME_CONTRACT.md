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
- close the selector preflight terminal BLOCKED/UNKNOWN and never replay it;
- create a fresh JULES_HUMAN_AUTH_BOOTSTRAP identity for the human boundary;
- after human completion, the preferred continuation is the same associated
  Work / same still-open Cloud Browser context defined in section 7E;
- do not require authentication persistence into a different event-triggered
  Work run as a correctness condition;
- browser/session identifiers remain transport context and are never persisted
  or used as correctness inputs;
- exact repo + branch selection evidence is still mandatory before any task
  submission.

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

Status: **USER-AUTHORIZED SAME-ASSOCIATED-WORK HUMAN BOUNDARY / NO JULES SUBMIT**.

Purpose:
create a fresh GitHub-triggered associated Work run, reach the Jules Google
human-auth boundary, and—if the platform actually resumes the same associated
Work/browser after human interaction—continue fresh post-auth observation in
that same bounded flow. Cross-run authentication persistence is not a
correctness requirement.

Observed operator surface:
- Scheduled Task: `Phase 0 PR6 Command Bus`
- user-visible associated Work label: `WORK【クラウド】`
- direct user observation has shown the task result, native Cloud Browser, and
  Google/Jules auth boundary on that associated Work surface.
- this is transport/operator evidence only; GitHub remains canonical.
- never persist or depend on chat/thread/conversation/browser/session IDs.

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
- positive `generation` for newly-created commands (historical v1 records without it remain readable)
- requires_live_model=false
- requires_github_write=true
- retry=0
- fallback=disabled
- no terminal receipt for the new command

Execution:
1. Fresh-read PR #4 head/tree and require exact command match.
2. Open Jules through native Work Cloud Browser only.
3. While authentication is unresolved, do not select repo/branch, submit a
   Jules task, start Jules/model, or mutate PR #4.
4. If Google authentication is required, prove the native secure
   sign-in/takeover entry is actually visible on the associated user-visible
   Work. A configured surface name is not proof.
5. After visibility proof, write/read back non-secret handoff evidence and set
   `WAITING_FOR_HUMAN_AUTH`.
6. Human interaction may advance only to
   `HUMAN_COMPLETED_UNVERIFIED`; this is never authentication PASS.
7. Keep the associated Work/browser context open. A human-auth continuation is
   not an external-action retry and does not increment retry.
8. Continue to `VERIFYING_POST_AUTH` only after directly verifying all of:
   - the associated Work is still user-visible;
   - the same browser context is still open;
   - the executor actually resumed in that same Work;
   - fresh PR #4 head/tree still match the command.
9. Discard all pre-auth DOM/selector/page assumptions.
10. Freshly observe the current Jules page.
11. AUTHENTICATED_OBSERVED requires direct fresh proof of all:
    - auth gate absent;
    - Jules task-creation UI reached;
    - exact repository explicitly selected/read back;
    - exact branch explicitly selected/read back;
    - task_submitted=false;
    - jules_task_started=false;
    - model_started=false.
12. Do not submit/start Jules in this flow.
13. If same-Work/browser continuity or executor resume is unavailable or
    unverifiable, terminalize BLOCKED/UNKNOWN. Do not infer auth persistence
    into another event-triggered Work.
14. A later separate Work may be a new diagnostic/preflight only with fresh
    logical identity; it cannot retroactively prove the prior auth context.

State progression:
```text
WAITING_FOR_HUMAN_AUTH
  -> HUMAN_COMPLETED_UNVERIFIED
  -> VERIFYING_POST_AUTH
  -> AUTHENTICATED_OBSERVED | BLOCKED | UNKNOWN
```

Durable post-auth evidence must record, without secrets/session IDs:
- associated Work visibility observation;
- same-browser-context-open observation;
- executor-resumed-same-Work observation;
- fresh target head/tree;
- fresh-observation=true;
- auth gate present/absent;
- Jules task-creation UI reached;
- expected/observed repo and exact-selection flag;
- expected/observed branch and exact-selection flag;
- task_submitted=false;
- jules_task_started=false;
- model_started=false;
- retry_count=0;
- fallback_used=false.

Execution-stream failure classification:
- record message-stream error and call_tool interruption independently;
- record whether a terminal durable write landed;
- classify runtime timeout, human-wait runtime termination, and post-takeover
  executor-resume failure separately as proven/absent/UNKNOWN;
- do not infer a platform root cause from a stale UI spinner or missing receipt.

Bootstrap-005 currently proves a user-visible message-stream/call_tool
interruption before durable completion. It does not prove whether the
platform-level subcause was timeout, human-wait termination, or executor-resume
failure; those remain UNKNOWN.

Never store or echo takeover URL, password, MFA, cookie, credential,
browser-control token, authentication token, or session identity.

Static implementation:
- `automation/command_bus/auth_handoff.py`
- `automation/command_bus/schema/auth_handoff.schema.json`
- `automation/command_bus/schema/state.schema.json`
- `automation/command_bus/tests/test_auth_handoff.py`
- `docs/JULES_HUMAN_AUTH_BOOTSTRAP.md`


## 7F. VISIBLE_WORK_ROUTE_DISCOVERY

Status: **READ-ONLY DISCOVERY / NO CROSS-THREAD SEND / NO BROWSER**.

Purpose:
remove the requirement that a human manually searches for the hidden
GitHub-event-triggered Work execution.

Require:
- action=`VISIBLE_WORK_ROUTE_DISCOVERY`
- target=work
- expected repo `kamiyusense/multi-ai-council-phase0`
- expected PR=4
- concrete fresh expected_target_head + expected_target_tree
- requires_live_model=false
- requires_github_write=true
- retry=0
- fallback=disabled

Execution order is strict.

### Priority 1: Scheduled Task associated chat

Inspect only metadata/capabilities already exposed to the current event-triggered
Work runtime for the exact Scheduled Task `Phase 0 PR6 Command Bus`.

Classify exactly one:
- `ASSOCIATED_CHAT_USABLE`
- `ASSOCIATED_CHAT_PRESENT_BUT_UNVERIFIED`
- `ASSOCIATED_CHAT_NOT_USER_VISIBLE`
- `ASSOCIATED_CHAT_UNAVAILABLE`
- `UNKNOWN`

`ASSOCIATED_CHAT_USABLE` requires direct proof for this exact task that the
associated chat is both stable across event runs and user-visible/openable. The
generic product concept "a task has a conversation" is insufficient.

Do not persist chat/thread/conversation/session identifiers. If Priority 1 is
`ASSOCIATED_CHAT_USABLE`, record the result and STOP; lower-priority routes
must not be inspected.

### Priority 2: native existing-thread delegation capability

Only when Priority 1 is not usable, inspect the callable tool/action catalog
exposed to this current event-triggered Work runtime.

Inspect presence only for:
- `send_message_to_thread`
- `read_thread`
- `list_threads`
- `create_thread`
- `thread_resume`
- an equivalent existing-Work/thread delegation primitive

Do not call any effectful delegation tool. Do not start a target model turn.
Record `native_thread_delegation_live_tested=false` and
`external_send_attempted=false`.

Capability classification:
- `AVAILABLE`: a callable existing-thread delegation primitive is exposed and
  a stable target locator plus readback primitive are both identifiable.
- `UNAVAILABLE`: the relevant callable family is definitively absent.
- `UNKNOWN`: exposure/target/readback semantics cannot be verified.
- `SKIPPED_HIGHER_PRIORITY`: Priority 1 already passed.

An error from any future live send must never cause automatic resend. Future
live testing, if separately authorized, must first read back the target.

### Output and safety

Fresh-read PR #4 before evidence write and require exact head/tree match.
Persist one non-secret evidence record validated by
`visible_work_routing.py` and
`schema/visible_work_route_evidence.schema.json`, then one terminal receipt
and matching terminal state.

This action MUST keep all of the following false:
- native_thread_delegation_live_tested
- external_send_attempted
- browser_started
- new_work_creation_tested
- human_auth_started
- jules_started
- model_started
- credential_material_persisted

If Priority 1 is not usable and Priority 2 is AVAILABLE, route decision is
`NATIVE_DELEGATION_CANDIDATE` and stop before Cloud Browser.
If Priority 2 is UNAVAILABLE or UNKNOWN, route decision is
`NEEDS_CHATGPT_WEB_PREFLIGHT`. A separate fresh command is then required for
any read-only ChatGPT Web browser preflight.


## 7G. CHATGPT_WEB_EXISTING_WORK_PREFLIGHT

Status: **USER-AUTHORIZED READ-ONLY / NO-SEND CLOUD BROWSER PREFLIGHT**.

Purpose:
test priority-3 routing only after this exact Scheduled Task's associated chat
is not proved usable and native existing-thread delegation remains unavailable
or UNKNOWN.

Require:
- action=`CHATGPT_WEB_EXISTING_WORK_PREFLIGHT`
- target=work
- expected repo `kamiyusense/multi-ai-council-phase0`
- expected PR=4
- concrete fresh expected_target_head + expected_target_tree
- `preferred_work_title` = an exact known pre-existing user-visible Work title supplied by the command
- requires_live_model=false
- requires_github_write=true
- retry=0
- fallback=disabled

Execution:
1. Fresh-read PR #4 head/tree and require exact command match.
2. Open `https://chatgpt.com` using Work Cloud Browser.
3. Navigation/observation only. Do not type or send a message.
4. Observe whether ChatGPT Web is reachable and whether the remote browser is
   already authenticated to the same account context. If authentication is
   required, classify BLOCKED_AUTH/UNKNOWN; do not start sign-in.
5. If authenticated, inspect whether ChatGPT UI, Work UI, and the existing Work
   list are visible.
6. Look only for the exact command-provided `preferred_work_title`. The first probe may use an already-known existing visible Work such as `WORK【クラウド】`; do not persist unrelated conversation titles.
7. If the preferred Work exists, open it read-only and verify that the Work
   surface is openable. Do not type, send, submit, or trigger a model turn.
8. Do not create a new Work.
9. Do not start human auth or Jules.
10. Persist no chat/thread/conversation/session/browser-control identifier.
11. Fresh-read PR #4 head/tree again and require unchanged exact identity.
12. Persist one non-secret evidence record, one terminal receipt and matching
    terminal state; read back all writes.

PASS requires all of:
- chatgpt_web_reachable=true
- chatgpt_auth_state=AUTHENTICATED
- chatgpt_ui_visible=true
- work_ui_visible=true
- existing_work_list_visible=true
- preferred_work_title_found=true
- existing_work_openable=true
- same_account_context_verified=true
- message_sent=false
- target_model_turn_started=false
- new_work_created=false
- human_auth_started=false
- jules_started=false
- credential_material_persisted=false
- chat_or_session_identifier_persisted=false

If the list is visible but the exact preferred fixed Work does not exist,
classify `NO_SUITABLE_EXISTING_WORK` and route decision
`NEEDS_FIXED_WORK_PREPARE`. This does not authorize creating the Work.

A PASS proves only UI reachability. It does not authorize a future UI relay
send; any such send is a separately authorized live POC.
