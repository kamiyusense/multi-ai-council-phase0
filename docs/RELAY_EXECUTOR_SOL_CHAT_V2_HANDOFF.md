# Relay Executor Sol Chat V2 Handover


> ## 2026-09-25 current Jules route update
>
> The user has now authorized the Jules API route. The previous BrowserHook /
> Work Cloud Browser launch route is frozen. The current selected predecessor is
> `google-labs-code/jules-action`, pinned for the first smoke to
> `bff7875eaa123cac6742b7cfc51005b95ba4d566`.
>
> The updated decision, executor handoff, advisor handoff, and bounded smoke
> workflow are prepared in PR #9 (`docs/jules-api-route-20260925`). This scoped
> Jules API authorization supersedes older Jules-specific "no API-key route"
> language in this handoff, but does not authorize other provider API keys or
> Billing/Credits/Overages changes. BrowserHook retries/006+ are not the next
> step.
>
Updated: 2026-09-23
Repository: `kamiyusense/multi-ai-council-phase0`
Role: second-generation execution Sol Chat
Status: ready for handover

This document is a recovery entrypoint, not a substitute for fresh GitHub
readback. If any SHA or state written here differs from current GitHub, current
GitHub wins. Never guess; unverifiable = UNKNOWN.

# 0. Mission and role

You are the **second-generation execution Sol Chat** for Multi-AI Council
Phase 0.

Normal role split after the 2026-09-23 handover boundary:

- **Sol Chat**
  - architecture and semantic review
  - root-cause analysis
  - Jules task design
  - GitHub current-state inspection
  - safe PR #6 implementation / tests / evidence / checkpoint
  - review of Jules output
  - next durable command/task design
- **Work / Luna**
  - GitHub event relay
  - Cloud Browser operation
  - deterministic validation
  - tree/blob reconstruction
  - receipts / readback
- **Jules**
  - main implementation executor, but only through fresh tasks/workspaces
  - never reuse an old Jules task/workspace
- **GitHub**
  - durable source of truth and recovery/control plane

Do not make correctness depend on Chat ID, thread ID, browser session, Jules
task session, or any disposable UI session.

# 1. First action in every fresh Chat

Before changing anything, fresh-read:

Repository:
`kamiyusense/multi-ai-council-phase0`

PR #4:
`feature/relay-transport-7070955470193506982`

PR #6:
`feature/chat-work-command-bus`

Also read PR #8 and Issue #7 until that probationary Jules result is formally
superseded by a later durable record.

At the time this handover was written, the fresh-read state was:

## PR #4

- OPEN
- head: `2fc399ac7b415746763114c3951aa2e3b45adee7`
- tree: `9e2d22b7caf001449d1a5aa4fd374fec81a415fe`

## PR #6

- OPEN
- head: `d372a794a8b114eaef92b9f2292f43f34b6ff758`
- tree: `08cc7a2d8ca337600741fc520c57bc159245b532`

## PR #8

Title:
`test(relay): add pre-dispatch abort regression test`

At the handover point:
- OPEN
- merged: false
- base: `main`
- base SHA: `230026f53f412cd52d8e2eac45457236c916b64d`
- head: `2c768f805e31066db62adc1ded321da1ef224c40`

Never treat these SHAs as permanent. Fresh-read first.

# 2. Mandatory reading order

Read these current files from PR #6 before resuming implementation or Jules
orchestration:

1. `docs/WORK_COMMAND_BUS_RUNTIME_CONTRACT.md`
2. `docs/CURRENT_SAFE_BATCH_TERMINAL_CHECKPOINT_20260923.md`
3. `docs/JULES_PROBATIONARY_ROUNDTRIP_001_CHECKPOINT.md`
4. `docs/HYBRID_WORK_CHAT_REVIEWER_RELAY_PROPOSAL.md`
5. `docs/HYBRID_WORK_CHAT_REVIEWER_P1_CHECKPOINT.md`
6. `docs/EXECUTOR_WORKSPACE_INTEGRITY_P0_CHECKPOINT.md`
7. `automation/command_bus/evidence/current-safe-batch-isolated-validation-20260923.json`
8. `automation/command_bus/evidence/jules-probationary-roundtrip-pr8-review-20260923.json`

Then inspect the current implementations that enforce the contract:

- `automation/command_bus/workspace_integrity.py`
- `automation/command_bus/relay_static.py`
- `automation/command_bus/reviewer.py`
- `automation/command_bus/github_backend.py`
- `automation/command_bus/reviewer_transport.py`
- `automation/command_bus/reviewer_wake_backend.py`
- `automation/command_bus/validation_scope.py`
- `automation/command_bus/jules_static.py`
- `automation/command_bus/jules_launch_backend.py`

And their tests, especially:

- `automation/command_bus/tests/test_workspace_integrity.py`
- `automation/command_bus/tests/test_reviewer_transport.py`
- `automation/command_bus/tests/test_reviewer_v2_backend.py`
- `automation/command_bus/tests/test_reviewer_wake_backend.py`
- `automation/command_bus/tests/test_validation_scope.py`
- `automation/command_bus/tests/test_jules_static.py`

# 3. Current completed Relay state

The Relay target branch PR #4 has already reached a validated static/mock
checkpoint.

Current known target head at handover:
`2fc399ac7b415746763114c3951aa2e3b45adee7`

Current known tree:
`9e2d22b7caf001449d1a5aa4fd374fec81a415fe`

Independent exact-current-blob validation recorded before the Jules smoke:
- unittest: 28/28 PASS
- compileall: PASS
- staged diff check: PASS

The current Relay implementation includes regression coverage for:
- retry=0
- fallback disabled
- timeout abort/no restart
- stop/no-new-dispatch
- pre-dispatch abort
- raw evidence before classifier mutation
- provider isolation
- one provider failure preserving peer raw evidence
- malformed/UNKNOWN remaining non-success
- subscription-only/static provider policy boundaries

Do not infer a new PASS after target changes without re-running/revalidating.

# 4. TREE_IDENTITY_V1 is mandatory

Any mutable executor—including Jules—must fail closed unless all required
identities match.

At minimum, require:

`GitHub current target head/tree`
=
`command expected_target_head/tree`
=
`executor HEAD/tree`
=
`index/write-tree`
=
`tracked worktree`

Also require:
- tracked diff clean before mutation
- cached/index diff clean
- no unexpected untracked files
- no skip-worktree
- no assume-unchanged
- unsupported sparse/submodule/unmerged states fail closed
- exact path/operation policy
- short mutation lease where applicable

A workspace gate failure blocks only that executor mutation. It does not stop
independent GitHub readback, evidence preservation, safe review, or creation of
a new disposable workspace.

Never auto-repair a suspect persistent workspace with:
- reset --hard
- git clean
- rebase
- auto-stash
- auto-commit
- conflict auto-resolution

# 5. Historical Jules workspace incident

Do not repeat the earlier stale-workspace incident.

Important historical facts are recorded in:
`docs/EXECUTOR_WORKSPACE_INTEGRITY_P0_CHECKPOINT.md`

The lesson is:

HEAD equality is not enough.

A prior Jules workspace produced an invalid commit even though parent/head
checks looked superficially plausible. Recovery was performed by a forward
commit whose tree exactly restored the known safe tree. Since then,
TREE_IDENTITY_V1 is mandatory.

# 6. Work event-route state

The Work/Luna command bus exists and is useful, but the event/receipt route had
a reproducible control-plane problem during the latest safe batch.

Several commands reached UNKNOWN/terminal with no durable receipt. They must
not be replayed.

Relevant checkpoint:
`docs/CURRENT_SAFE_BATCH_TERMINAL_CHECKPOINT_20260923.md`

Relevant runtime contract:
`docs/WORK_COMMAND_BUS_RUNTIME_CONTRACT.md`

Do not blindly wake/re-send old terminal commands.

For any apparent failed external write or wake:
1. read back GitHub first;
2. determine whether it already happened;
3. if unverifiable, mark UNKNOWN;
4. retry=0.

# 7. Hybrid Work/Luna + Sol reviewer architecture

The intended correctness flow is:

`GitHub review_request`
→ Work/Luna
→ transport wake
→ Sol semantic reviewer
→ `GitHub review_response`
→ Work/Luna
→ next durable command

Correctness must never depend on semantic parsing of a Chat/browser UI answer.

Implemented static protocol:
`DURABLE_REVIEW_V2`

Durable reviewer data binds:
- request_id
- loop_id
- round
- correlation_id
- expected_target_head
- expected_target_tree
- reviewer_role
- review_kind
- evidence_refs
- allowed_decisions
- rationale_summary
- result/decision
- next command proposal
- receipt

Browser / Direct / Manual are transport choices only.

A reviewer wake uses a durable one-way reservation. A recovered reservation
never authorizes a second external send.

Live Browser reviewer POC is still a separate explicit approval boundary unless
current GitHub instructions have since changed.

# 8. Jules reintroduction policy

The old blanket "Jules stopped / never restart" rule ended after:
`docs/CURRENT_SAFE_BATCH_TERMINAL_CHECKPOINT_20260923.md`

From the next batch onward Jules is intended to become the primary
implementation executor, but only after a safe probationary round-trip.

Rules:
- fresh Jules task/session
- fresh/disposable workspace
- never reuse an old task/workspace
- TREE_IDENTITY_V1 before mutation
- one small bounded task first
- exact path/operation policy
- retry=0
- fallback disabled
- terminal replay forbidden
- remote readback mandatory
- no Merge without explicit human approval
- no main direct write
- no force push
- no branch deletion
- no API-key/billing/settings/permissions mutation

The static Jules launch contract is in:
- `automation/command_bus/jules_static.py`
- `automation/command_bus/jules_launch_backend.py`
- `automation/command_bus/tests/test_jules_static.py`

The Work runtime contract currently authorizes only the explicitly bounded
Jules probationary action defined in:
`docs/WORK_COMMAND_BUS_RUNTIME_CONTRACT.md`

Always fresh-read that file; it may be newer than this handover.

# 9. Jules probationary round-trip 001 result

Issue #7 was created as the first fresh Jules smoke task.

Requirement:
- exact target branch PR #4
- exact starting head/tree
- do not fall back to main
- modify exactly:
  `tests/relay/test_dispatcher.py`
- operation: MODIFY only
- add one unittest proving:
  `abort_signal={"aborted": True}`
  blocks before slot reservation and before provider dispatch
- no implementation change
- required tests:
  - `PYTHONPATH=src python -m unittest discover -s tests -t . -v`
  - `python -m compileall -q src tests`
  - `git diff --check`

Jules created PR #8.

The result is **BLOCKED / ISOLATED / NOT MERGED**.

Why:
- PR #8 base = `main`
- Jules commit parent = `230026f53f412cd52d8e2eac45457236c916b64d`
- expected PR #4 parent = `2fc399ac7b415746763114c3951aa2e3b45adee7`
- Issue #7 explicitly prohibited falling back to main
- durable Jules test execution evidence was not available in GitHub

Important nuance:

PR #8's UI shows many changed files because its base is `main`.

Direct tree-to-tree comparison:

`PR #4 tree -> PR #8 head tree`

showed exactly **one differing blob**:
- `tests/relay/test_dispatcher.py`
- operation: MODIFY

The actual content delta was semantically correct: one added unittest checking
pre-dispatch abort, no provider dispatch, and no slot reservation.

Therefore:
- Jules task content: semantically in scope
- Jules base/parent contract: FAIL
- durable test execution proof: UNKNOWN
- Merge PR #8: NO
- apply PR #8 to PR #4: NO
- automatic cherry-pick: NO
- automatic rebase: NO
- retry same Jules task: NO

Evidence:
`automation/command_bus/evidence/jules-probationary-roundtrip-pr8-review-20260923.json`

Checkpoint:
`docs/JULES_PROBATIONARY_ROUNDTRIP_001_CHECKPOINT.md`

# 10. What the second-generation Sol Chat should do next

Do not start by modifying Relay code.

First:
1. fresh-read PR #4, PR #6, Issue #7, PR #8;
2. verify the checkpoint/evidence above still exists and matches;
3. verify PR #8 remains unmerged unless a newer explicit human-approved
   decision exists;
4. identify why Jules created its PR from `main` despite Issue #7 explicitly
   naming the target branch/head/tree.

Treat this as a **Jules base-selection / launch-transport design problem**, not a
Relay implementation problem.

The next objective is to design/prove a method where a fresh Jules task can
actually start from the exact non-default PR #4 branch/head/tree.

Safe work before any new Jules live launch:
- inspect Jules/GitHub integration behavior
- inspect Issue/PR/task metadata
- inspect repository/task configuration
- static/mock protocol fixes
- regression fixtures
- durable launch-request/receipt design
- documentation/checkpoint
- Work Cloud Browser prepare-only design
- verify whether the Jules integration supports selecting a non-default branch
  through the route actually being used

Do not infer support from UI text alone.

If the next design still cannot prove exact non-default target selection,
report BLOCKED/UNKNOWN rather than launching another Jules task.

A new Jules live task is a new logical task. Never replay Issue #7 / PR #8.

# 11. Safe-write envelope

Within the already-authorized purpose and PR #6 branch, the execution Sol Chat
may continue without asking at ordinary checkpoints:

- fresh readback
- static analysis
- reversible code/docs/test changes
- fixtures/unit/regression tests
- prepare-only/mock work
- evidence/checkpoint creation
- normal commits to the existing non-default PR #6 branch
- fast-forward safe write
- remote readback

Before any write:
- fresh-read current head
- avoid overwriting concurrent changes
- keep changes in scope

After write:
- read back head/diff/tree
- validate
- continue safe work if any remains

If one subtask is BLOCKED, isolate it and continue independent safe work.

# 12. Operations that still require explicit human approval

Do not auto-execute:
- PR Merge
- direct write to default/main branch
- force push
- branch deletion
- history rewrite
- destructive cleanup
- irreversible important data deletion
- API Billing/Credits/Overages changes
- API key create/show/change
- settings/permissions/admin/account-state changes
- a live Browser reviewer POC if current GitHub contract still marks it as
  approval-gated
- any new external/provider live route not already explicitly authorized by
  current durable policy

For Jules specifically, the user authorized Jules reintroduction in principle,
but each new live launch must still satisfy the current durable Jules contract,
fresh target/tree proof, retry=0/no-replay semantics, and any explicit approval
boundary currently written in GitHub.

# 13. Completion/reporting rule

Do not return to the user just because:
- one commit succeeded
- one test passed
- one checkpoint was written

Continue:
safe work
→ validation
→ evidence
→ safe fix
→ revalidation
→ permitted GitHub write
→ remote readback
→ next safe work

Only stop when:
- the safe batch is exhausted, or
- a real human decision/approval is required, or
- the remaining route is genuinely UNKNOWN/BLOCKED and no independent safe work
  remains.

Do not ask "continue?" at ordinary progress boundaries.

# 14. User-facing style

Use Japanese.

The user is not a programmer and may skim long messages.

Make critical state visually obvious:
- 🟢 PASS / safe
- 🟠 user decision or meaningful blocker
- 🔴 destructive/billing/permission/irreversible warning

If the user must copy text manually, put the copyable content in a fenced code
block. Prefer durable GitHub/connector routes so the user does not become the
courier.

# 15. Recovery invariant

The most important recovery rule:

**GitHub current state is the source of truth.**

This handover is only a map to the durable records.

If this document conflicts with fresh GitHub:
1. trust fresh GitHub;
2. preserve the conflict as evidence;
3. do not guess;
4. use UNKNOWN until resolved.
