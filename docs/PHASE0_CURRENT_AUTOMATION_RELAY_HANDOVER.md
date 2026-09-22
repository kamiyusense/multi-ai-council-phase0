# Phase 0 Current Automation + Relay Handover

Updated: 2026-09-22  
Repository: `kamiyusense/multi-ai-council-phase0`  
Purpose: new Chat / fresh Work recovery anchor  
Status: CURRENT HANDOVER — GitHub state wins over this document if newer

## 0. First principle

A fresh Chat must not depend on the old conversation, old browser session, old Work session, or one Jules task.

Canonical recovery order:

1. current GitHub PR state
2. durable command / request / claim / response-result / receipt / state records
3. this handover and the design documents
4. old Chat summaries only as supplementary context

If this file and GitHub disagree, use current GitHub and mark this file historical.

## 1. Role model

Use these logical roles:

```text
GitHub
= canonical durable state / control plane / recovery source

PR #4
= persistent Relay implementation workbench

PR #6
= command-bus / reviewer / executor implementation workbench

Work
= event-driven controller / executor manager

Reviewer
= replaceable logical role; a new Chat may take this role

Jules
= disposable implementation executor

Human
= exception / approval boundary only
```

Correctness must not depend on Chat ID, thread ID, conversation ID, browser session, or disposable Jules task ID.

Direct Work -> Chat -> Work is optional fast path only. GitHub durable state is the correctness path.

## 2. Current command-bus / automation state

Command-bus PR:

- PR: #6
- branch: `feature/chat-work-command-bus`
- current handover head: `9ee080b87383d646ef28adfefd2fdc7975ff588f`
- base: `main`
- state: OPEN / unmerged
- PR #6 is the carrier; its head is dynamic and MUST NOT be compared to a stored expected carrier SHA.

Target PR:

- PR: #4
- current handover head: `62f341b04f9d6e19dd003b42304bb896e4db45ef`
- state: OPEN / unmerged
- `expected_target_head` compares only against PR #4 current head.

Latest completed executor-contract command:

```text
loop_id: executor-contract-001
command:
automation/command_bus/commands/executor-contract-001/000001.json

action:
APPLY_PREPARE_EXECUTOR_CONTRACT

implementation commit:
ca89c9b92c1820a71aacfb0394a20aeb9ce71d0c
message:
feat: add prepare-only executor handoff contract

receipt:
automation/command_bus/receipts/executor-contract-001/000001.json
state = DONE
executed_once = true
retry_count = 0
fallback_used = false
external_send_attempted = false

final loop state:
automation/command_bus/state/executor-contract-001.json
state = COMPLETE
round = 1
last_receipt_id = 000001

final carrier head after state finalization:
9ee080b87383d646ef28adfefd2fdc7975ff588f
```

Target validation remained:

- expected repo: `kamiyusense/multi-ai-council-phase0`
- expected PR: #4
- expected target head: `62f341b04f9d6e19dd003b42304bb896e4db45ef`
- observed target head: same
- retry = 0
- fallback = disabled
- requires_live_model = false

The previously queued UI event has now been resolved by backend evidence. The event-trigger Work task ran, wrote the implementation commit, persisted a terminal DONE receipt, and finalized state to COMPLETE. Follow-up processing must treat this command as terminal and NO-OP.

Do not replay `executor-contract-001-000001`.

## 3. Event-triggered Work task

Current task:

- title: `Phase 0 PR6 Command Bus`
- task id: `6ab255548ae48191971dd6892a2e02b3`
- enabled: YES
- timing mode: condition_watch
- trigger source: GitHub PR #6 pull-request / commit-update activity
- carrier PR #6 head is dynamic
- target validation uses PR #4 `expected_target_head`

Supported bounded actions currently include:

- `ECHO_AND_RECEIPT`
- `STATIC_VALIDATE_COMMAND_BUS`
- `APPLY_PREPARE_EXECUTOR_CONTRACT`

Global rules:

- retry = 0
- fallback disabled
- no PR #4 modification from command-bus processing
- no Merge
- no main direct write
- no force push
- no branch deletion
- no Jules task creation
- no live external provider/model
- no API key
- no Billing / Credits / Overages / settings / permissions changes
- ambiguity or unverifiable write/readback => UNKNOWN and stop

Terminal receipt or COMPLETE means replay is NO-OP.

## 4. Command-bus evidence already proven

Previously proven by real GitHub / Work event execution:

```text
GitHub command commit
-> Work event wake-up
-> command processed exactly once
-> receipt persisted
-> receipt/state follow-up event
-> terminal receipt detected
-> duplicate replay prevented
-> NO-OP
```

Reviewer durable loop was also proven with real GitHub records:

```text
review request
-> event-trigger Work
-> claim
-> response = SMOKE_ACK
-> receipt = CONSUMED
-> state = COMPLETE
-> follow-up event
-> NO-OP
```

This proved fresh Work can recover reviewer state from GitHub without Chat/thread identity.

Static validation evidence later recorded:

- command-bus tests: 48 PASS at static-validation-004 checkpoint
- compileall: PASS
- deterministic Git blob/tree verification: PASS
- retry = 0
- fallback disabled

Do not replace newer evidence with older lower test counts. Always inspect current PR #6 receipt/evidence records.

## 5. Prepare-only executor contract being completed

The current goal is a provider-neutral durable executor role.

Target durable layout:

```text
execution_requests/<loop>/<request>.json
execution_claims/<loop>/<claim>.json
execution_results/<loop>/<result>.json
execution_receipts/<loop>/<receipt>.json
state/<loop>.json
```

Required properties:

- `target_role = "executor"`
- provider/executor brand is not a correctness dependency
- executor_kind may identify generic / Jules / Codex / Claude etc.
- capability
- objective
- input_refs
- evidence_refs
- allowed_actions
- prohibited_actions
- requires_user_approval
- approval_state
- PREPARE_ONLY only for current executable policy
- `live_start_permitted = false`
- `requires_live_model = false`
- retry = 0
- fallback = disabled
- request/claim/result/receipt execution-ID aliases
- exact loop / round / correlation / expected_target_head validation
- stale generation rejection
- expiry / STOP / HALTED / max6 fail-closed
- duplicate / path traversal / malformed / missing predecessor fail-closed
- no Chat/thread/conversation ID in persisted correctness data

Prepare-only result evidence must distinguish:

- artifact refs
- evidence refs
- model_executed = false
- external_send_attempted = false
- retry_count = 0
- fallback_used = false
- live_started = false

The prepare-only executor contract is now durably committed and verified by the event-trigger Work receipt.

Implementation evidence:

- implementation commit: `ca89c9b92c1820a71aacfb0394a20aeb9ce71d0c`
- changed implementation files: exactly the five approved files
- unittest: **55 PASS / 0 FAIL**
- discovered test count: 55
- compileall: PASS
- git diff --check: PASS
- approval boundary: covered
- live-start blocking: covered
- fresh-session recovery: covered
- exactly-once receipt recovery: covered
- reviewer regression: preserved
- carrier-head changes do not replace target-head validation
- no thread/chat ID correctness dependency
- PR #4 head unchanged
- live/Jules/provider execution: NO
- retry: 0
- fallback: disabled

The earlier local 54-test report is now historical; use the GitHub-backed 55-test DONE receipt as the stronger current evidence.

## 6. Relay workbench — resume point

Relay PR:

- PR: #4
- branch: `feature/relay-transport-7070955470193506982`
- current verified head: `62f341b04f9d6e19dd003b42304bb896e4db45ef`
- base: `main`
- state: OPEN / unmerged

Current verified Relay evidence at this head includes:

- deterministic canonical payload SHA-256
- duplicate/conflict guard
- transport-neutral relay protocol
- mock transport
- one-attempt mock lifecycle
- provider-specific policy descriptors
- subscription-only auth-kind allowlist
- Claude dangerous bypass forced false in policy/session metadata
- official Google Antigravity ACP candidate
- malformed/UNKNOWN non-success behavior
- retry = 0
- fallback disabled
- `live_ready = false`

Independent earlier verification from exact PR #4 blobs:

```text
PYTHONPATH=src python -m pytest -q tests
22 passed

python -m compileall -q src tests
exit 0
```

The current design direction is:

```text
Phase0 Core (Python)
  -> thin Phase0 Relay (Python)
     -> ACP Python SDK
        -> Codex ACP 1.12.0
        -> Claude Agent ACP 0.79.0
        -> Google Antigravity ACP 1.1.1
```

Preferred common dependency candidate:

`agent-client-protocol == 0.12.1`

Read before further Relay implementation:

- `docs/RELAY_STATIC_CHECKPOINT.md`
- `docs/RELAY_STATIC_BUILD_PLAN.md`
- `docs/RELAY_LIVE_BLOCKERS.md`
- `docs/RELAY_OSS_REUSE_DECISION.md`
- `docs/PIONEER_OSS_RESEARCH_HANDOVER.md`

The user refers to the previously paused Relay/Jules work as being stopped at “1.2.9”.
No exact `1.2.9` marker was found in the current GitHub repository search at this handover checkpoint.
Do not invent a mapping. Treat “1.2.9” as the user's human label and use PR #4 current GitHub head + Relay checkpoint docs as the canonical resume point.

## 7. Jules continuity

Old Jules task:

`7070955470193506982`

Its old sandbox became stale and could not prove synchronization to PR #4 current head.

Therefore:

- do not depend on that task surviving
- do not automatically retry the old stale task
- Jules is disposable
- persistent identity is repository + PR #4 branch + verified head SHA
- a future fresh Jules task must start by reading PR #4 current head and proving workspace synchronization before mutation

Whether a fresh Jules task can reliably publish back to the same PR #4 branch remains to be re-proven in the current environment.

Starting a new live Jules/provider task remains a separate explicit-authorization boundary unless the current user instruction clearly grants that bounded live run.

## 8. Relay live blockers

Live provider execution is NOT authorized by this handover.

Current high-level blockers remain:

Codex:
- provider-internal retry/replay must be proven zero
- no silent auth-recovery replay
- executed-model verification required
- subscription account route must be proven

Claude:
- SDK/provider retry/fallback must be proven disabled/prevented
- subscription `account` route must be proven
- dangerous permission bypass false
- executed-model verification required

Google Antigravity ACP:
- intended subscription/account route proof
- no API-key / Cloud Billing / overage route
- internal retry/fallback remains UNKNOWN because runtime is closed
- executed-model verification
- cancellation/teardown without restart
- quota/billing UNKNOWN must fail closed

No automatic Gemini CLI substitution.

## 9. New Chat = reviewer role

A new Chat may replace this Chat as the reviewer/planner.

On first turn the new Chat should:

1. read this document
2. read PR #6 current state directly
3. read the active command/state/receipt paths
4. read PR #4 current head directly
5. read Relay checkpoint/build/blocker docs
6. inspect the event-trigger Work task if available
7. prefer current GitHub over remembered/quoted SHA values
8. preserve retry=0 / fallback disabled / fail-closed UNKNOWN
9. continue all safe read-only/static work before asking the human
10. never Merge without explicit human approval

The new Chat should NOT assume it is automatically awakened by GitHub.

Proven:

`GitHub -> event-trigger Work`

Not proven:

`GitHub -> ordinary Chat auto-wakeup`

Therefore Work remains the automated controller. The new Chat acts as replaceable reviewer when invoked or when Work can safely obtain its response.

## 10. Immediate recovery algorithm for the new Chat

Use this exact logic:

```text
read PR #6 current head
-> read executor-contract-001 command/state/receipt
-> verify terminal DONE + COMPLETE and implementation commit ca89c9b...
-> verify 55-test receipt evidence and PR #4 target head
-> do NOT replay the completed executor-contract command
-> continue to the next safe integration step

then

read PR #4 current head
-> verify Relay docs/tests/checkpoint
-> compare against latest executor/automation state
-> continue static Relay integration/recovery work
-> treat the user's "1.2.9" as a human label unless a GitHub mapping is later found
-> stop before unapproved live Jules/provider execution
```

If PR #6 or PR #4 heads differ from this document, use the newer GitHub heads.

## 11. Safety boundary / what still requires the human

Do not automatically perform:

- PR Merge
- direct write to default branch
- force push
- branch deletion
- history rewrite
- destructive reset/clean
- irreversible important-data overwrite/delete
- API metered billing operation
- Billing / Credits / Overages changes
- API key creation/change/display
- settings / permissions changes
- admin/account-state changes
- unapproved new external-service send
- unapproved live Relay/app-server POC
- unapproved live Jules/provider/external-model start
- dangerous operation while safety is UNKNOWN

Already-authorized non-destructive development writes on the current non-default PR branches may continue with fast-forward + readback under the Project rules.

## 12. New-chat completion target

The new Chat should be able to take over without asking the user to copy old conversation history.

Success means:

```text
fresh Chat
-> reads GitHub handover/current state
-> identifies PR #6 pending/completed command correctly
-> verifies Work event/receipt state
-> acts as reviewer role
-> reads PR #4 Relay state
-> continues static Relay development plan
-> uses fresh/disposable executor when later authorized
-> preserves all safety boundaries
```

The user should not be used as a progress checker or message courier.

No Merge is authorized by this handover.


## 13. Fresh reviewer takeover readback — 2026-09-22

A fresh reviewer/planner Chat recovered from GitHub and direct task readback without relying on the old conversation.

Current verified state after recovery:

- PR #6 branch: `feature/chat-work-command-bus`
- PR #6 current head: `b71370c46fe930dfd55e96f8c3eb73d05500074b`
- PR #6 state: OPEN / unmerged
- PR #4 branch: `feature/relay-transport-7070955470193506982`
- PR #4 current head: `62f341b04f9d6e19dd003b42304bb896e4db45ef`
- PR #4 state: OPEN / unmerged
- event-trigger task `Phase 0 PR6 Command Bus`: enabled
- carrier policy: PR #6 head is dynamic; no fixed carrier SHA
- target policy: only PR #4 current head is compared with `expected_target_head`
- retry = 0
- fallback disabled

Recovered reviewer record:

`reviewer-github-smoke-001`

Its request, claim, response, and terminal CONSUMED receipt were already present and mutually matched the current PR #4 target head, but the mutable state file was still `RUNNING` with round 0 and no last receipt.

The fresh reviewer performed only the missing state finalization:

- commit: `b71370c46fe930dfd55e96f8c3eb73d05500074b`
- state: `COMPLETE`
- round: 1
- last_receipt_id: `review-resp-001`
- no replayed review response
- no PR #4 modification
- no live provider/Jules execution
- no retry/fallback
- Merge: NO

This is evidence that a fresh reviewer can recover an already-consumed durable review exchange and finish only the missing mutable state step without depending on Chat/thread identity.

Relay resume remains anchored to PR #4 head `62f341b04f9d6e19dd003b42304bb896e4db45ef`.

The repository still contains no exact `1.2.9` marker identified by the recovery inspection. Treat `1.2.9` as the user's human label, not a repository version identifier.

Next safe Relay work remains static/mock only. The current PR #4 code already contains a Core `ProviderAdapter` bridge plus three-provider mock integration and the lower-level transport/envelope/lifecycle primitives. Before mutating PR #4 further, prefer an executor/test-capable environment that can run the existing suite and preserve exact test evidence. A new live Jules/provider start is not implied by this checkpoint.


## 14. Prepared static Relay next batch

Canonical target remains PR #4 head `62f341b04f9d6e19dd003b42304bb896e4db45ef`.

The next implementation executor should start by proving it has exactly that target head and then run the existing repository tests before mutation. No live provider/model/Jules turn is required for the static batch itself.

Prioritized static gaps from direct inspection of the current PR #4 code and `docs/RELAY_STATIC_BUILD_PLAN.md`:

1. prove current suite on the exact PR #4 head before edits;
2. add deterministic cancel/abort fixture coverage so cancellation targets only the intended provider/session and never causes a second prompt or restart;
3. add one-provider-failure isolation coverage so one provider failure does not erase successful RAW/result material from another provider;
4. harden provider-policy fixtures for non-subscription routes, including Codex API-key/gateway rejection and Claude dangerous-bypass reappearance rejection;
5. preserve raw transport evidence before semantic classification and test malformed/UNKNOWN paths remain non-success;
6. keep the three-provider Core `ProviderAdapter` mock integration and add stop/no-new-dispatch coverage;
7. run full unit/fixture/regression suite, compileall, and diff check;
8. update Relay checkpoint evidence with exact command output and resulting PR #4 head.

Safety constraints for this batch:

- static/mock only
- retry = 0
- fallback disabled
- no API key route
- no Billing/Credits/Overages/settings/permission changes
- no live provider model turn
- no live Jules start implied
- no Merge
- no force push
- no branch deletion

Because this Chat does not currently have an execution workspace/test runner attached, it must not mutate PR #4 code and then guess PASS. Preserve the verified PR #4 code head until an executor can run the tests and record evidence.


## 15. Jules stale-workspace incident and recovery — 2026-09-23

### Incident

PR #4 was at verified head `62f341b04f9d6e19dd003b42304bb896e4db45ef`.
A bounded static Relay task was sent to Jules with an explicit requirement to prove workspace synchronization to that exact head before any mutation.

Jules acknowledged the instruction, then created commit:

- `abac6f5aa955167c950d9cb15753ae14ac386317`
- message: `docs: add Jules continuity probe to checkpoint`
- parent: exactly `62f341b04f9d6e19dd003b42304bb896e4db45ef`

The commit tree nevertheless removed or regressed numerous files that existed at the parent, including `AGENTS.md`, Relay safety/design documents, provider policy, deterministic envelope/duplicate/lifecycle helpers, and existing static tests. It also replaced safer Relay behavior with older/simpler behavior (for example Python `hash()` instead of deterministic SHA-256 and an outer `DELIVERED` result around malformed provider output).

The checkpoint written by that commit explicitly described reuse of existing Jules task `7070955470193506982` and the existing branch. The exact internal Jules failure mechanism is not directly observable, but the evidence is consistent with a stale/incomplete task workspace tree being committed on top of the correct current Git parent. This is therefore recorded as **likely stale workspace/task reuse**, not as a proven internal Jules bug.

### Containment

A GitHub `@jules STOP` instruction was issued. Jules explicitly acknowledged the stop and stated it would make no further commits or repairs.

No Merge, force push, branch deletion, provider execution, API-key route, billing/settings/permission change, or main write occurred.

### Recovery

The verified pre-incident commit `62f341b04f9d6e19dd003b42304bb896e4db45ef` has Git tree:

- `62e681613be4de68ee5987634a075078f6bb522a`

A normal non-destructive recovery commit was created with parent `abac6f5...` and that exact verified tree:

- recovery commit: `ffcdff208d12620d423592df78af1fd1eb88950e`
- PR #4 branch updated fast-forward only
- recovery tree: `62e681613be4de68ee5987634a075078f6bb522a`
- compare `62f341b... -> ffcdff2...`: **0 changed files**

Thus the Jules incident remains in history for evidence, while the current PR #4 content is byte/tree-equivalent to the verified pre-incident Relay state.

### Durable lesson

Do not use a long-lived Jules task/workspace as the source of truth.
Before any Jules write, require both:

1. current GitHub target head readback; and
2. proof that the actual workspace tree is synchronized to that head.

A correct commit parent alone is insufficient proof that the workspace contents were current.
