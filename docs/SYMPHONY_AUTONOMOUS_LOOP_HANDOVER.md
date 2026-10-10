# Symphony / New Chinponey Autonomous Loop Handover

Status: current design handover for the autonomous-loop line. Fresh GitHub
readback is authoritative; do not trust remembered SHA values.

## Current G6 STATIC boundary — 2026-10-10

Read [G6 checkpoint](SYMPHONY_G6_STATIC_CHECKPOINT.md) and its prepare-only Local
LIVE plan. Actual byte/path/identity inspection, fresh target/task validity,
create-only intents/receipts, fake atomic Git CAS and crash/restart recovery now
pass STATIC fixtures. Safe results flow automatically through this seam. G5.1
Local LIVE #342 already passed the real worker lifecycle/restart proof; read
`SYMPHONY_G51_LOCAL_LIVE_RESULT_ISSUE_342.md`. Its terminal remains UNKNOWN and
its artifact is not adopted. Historical entries below describe earlier stages.
Current batch real result adoption/model/provider LIVE 0. Production atomic ref
transport and trustworthy result readers are NOT_WIRED; separate G6 LIVE
approval is still required. Official Symphony control paths are unchanged.

## G5 Cloud STATIC observation bridge — 2026-10-09

Read `SYMPHONY_G5_PRODUCTION_OBSERVATION_BRIDGE.md`. A minimal patch for pinned
Official Symphony emits signed local worker STARTED/TERMINAL observations
without changing its scheduling, turns, retry or stall logic. An opt-in Python
sidecar verifies the signed Issue/worker envelope and uses the existing
create-only attempt ledger. Reader restart replays complete lines with duplicate
NO-OP; a conflicting terminal cannot overwrite evidence. The hook, sidecar and
workflow are STATIC preparations: **no G5 LIVE was run**. G4 remains the only
real Symphony/Codex proof. G5 does not feed worker-end UNKNOWN into campaign
result adoption and does not write Git results. Separate LIVE approval and G6
adoption proof are still required.

## Latest Local upstream boundary — 2026-10-09

Generation 4 achieved the explicitly bounded Local worker/workspace proof;
read `SYMPHONY_MINIMAL_LIVE_PROOF_LOCAL_RESULT_ISSUE_336_G4.md`. One real model
turn completed, the only allowed new evidence file was produced, and normal
same-thread continuation started. The operator stopped the second turn after
sufficient proof, confirmed process/port shutdown, and read back unchanged
main/PR/proof refs during the LIVE interval. Generations 1–3 remain FAIL.

Current workflow compatibility uses granular approval channels all false,
ASCII prompt template, and `read_timeout_ms: 60000`. A later STATIC prompt
clarification distinguishes the fixed original proof HEAD from the advancing
PR evidence HEAD. It is not a new LIVE result. Keep each historical root/log
immutable and use a new root for any separately authorized corrective generation.

Production upstream-event-to-ledger transport, authenticated durable recovery,
automatic Git adoption, completed continuation, natural stall recovery and
quota-reset recovery still require their own evidence. Existing STATIC durable
attempt and adoption guards remain the integration seams. Do not infer those
capabilities from the one-file proof or replace original Symphony continuation
with a one-turn scheduler.

## Latest implemented boundary — 2026-10-07

Read `SYMPHONY_ADOPTION_BRIDGE_STATIC_CHECKPOINT.md` for the newer STATIC
result-adoption and subscription-route seam. A late canonical HEAD advance now
discards old DONE results and replans; destructive/unknown mutation classes
isolate the task. Recovered terminals run the same guard. Upstream issue updates
can wake read-only reconciliation without a complete worker identity. The
subscription classifier is new-worker-only and does not gate Symphony's
internal turns/retries. Production transport and actual LIVE authentication
remain unverified; do not treat these STATIC checks as LIVE authorization.
The strict JSONL Codex adapter additionally strips ambient API-key/custom
endpoint selectors from its child process environment; Official Symphony's
future worker launcher still needs this boundary.
The STATIC controller now routes fake upstream STARTED/TERMINAL captures through
the existing durable attempt store. Duplicate captures are NO-OP and conflicting
captures are rejected; this adds no scheduler or production LIVE transport.
Terminal reconciliation requires an explicit task-validity reader.

Read `SYMPHONY_ATTEMPT_RECOVERY_STATIC_CHECKPOINT.md` before the older historical
next-step sections below. Attempt-to-campaign reconciliation, durable controller
integration, unstarted retirement, late-terminal BLOCKED recovery, observation
evidence, crash injection and the 30-round/five-session STATIC soak are now
implemented. Authenticated production upstream events and subscription-only
runtime admission remain NOT_WIRED/NOT_READY. Do not enable upstream automatic
stall retry blindly. Preserve the consumed-command fence and the full unattended
multi-task/multi-round North Star.

## Repository / active line

- repository: `kamiyusense/multi-ai-council-phase0`
- draft PR: #320
- branch: `codex/symphony-inspired-minimal-controller`
- do not merge without explicit human approval
- no direct default-branch write
- no force push/history rewrite/destructive cleanup
- no billing/credit/API-key/permission/secret changes without explicit approval
- do not hand this task to Work unless the user explicitly changes that request

## Read first

1. `docs/AUTONOMOUS_DEVELOPMENT_LOOP_NORTH_STAR.md`
2. `docs/SYMPHONY_AUTONOMOUS_LOOP_DESIGN.md`
3. `docs/SYMPHONY_INSPIRED_MINIMAL_ORCHESTRATOR.md`
4. current PR #320 files and exact HEAD
5. current CI/workflow results on that exact HEAD

The shared North Star is aligned byte-for-byte with the North Star on Draft PR #325 at this checkpoint. The Symphony-specific design file adds the line-level upstream-first / two-track / open-valve decisions. The North Star supersedes the old interpretation that the product goal is one command / one turn / one model start.

## User intent that must not be lost

The user wants an unattended development loop that can run while sleeping or
working and use already-paid subscription capacity productively.

Do NOT silently shrink the target into:

- one safe round;
- wake -> read -> report -> wait for human;
- UNKNOWN -> immediate campaign stop;
- stale HEAD -> immediate campaign stop;
- one blocked task -> whole campaign stop;
- retry=0 for reads/tests/evidence/corrective work.

The controlling principle is:

> **Safety protects continuation. Safety is not the goal of stopping.**

If safe work remains inside the campaign, continue.

## Runtime direction

Prefer official Symphony's proven long-running concepts for:

- polling/reconciliation;
- workspace lifecycle;
- multi-turn continuation;
- multiple work items;
- transient retry/backoff where side effects are not ambiguous;
- session-independent worker/controller operation.

Preserve project-specific safety components:

- duplicate execution prevention;
- stale-target guard with safe replan;
- durable execution ledger;
- ambiguous-write readback/no blind resend;
- subscription-only cost boundary.

Restrictions used for proof may stay conservative initially, but should be
represented as configurable policy/profiles whenever practical so they can be
opened later. The architecture should be capable of approaching upstream
Symphony behavior without a rewrite.

It is acceptable to build both:

1. a minimally modified upstream-Symphony track for capability/reference;
2. a hardened New Chinponey track using project-specific durable guards.

Do not force premature unification if two tracks produce faster, clearer
evidence.

## Retry / recovery rules

Distinguish:

- **ambiguous side-effect resend:** do not blindly retry;
- **transient read/test/evidence/status failure:** bounded retry is allowed;
- **failed semantic result:** create a new corrective task;
- **stale target:** fresh readback and replan if safe;
- **session/lease loss:** safe reclaim/resume if ownership/generation verifies;
- **blocked subtask:** isolate it and continue independent work when possible.

UNKNOWN should be classified as transient, recoverable or hard. HARD should be
reserved for conditions where safe continuation cannot be established.

## Cost policy

Target is subscription-only unattended operation.

- do not enable/use metered API fallback automatically;
- do not buy/enable credits/overages automatically;
- do not fall back to another paid provider automatically;
- confirmed quota exhaustion may stop new model work;
- inability to read a remaining-percent value by itself must NOT be treated as
  confirmed quota exhaustion.

Before unattended LIVE, verify that the selected authentication/quota route can
enforce the policy.

## Current implementation / proof state

PR #320 currently contains a strict Symphony-inspired proof implementation.

The strict profile includes one-turn/one-start and exact proof verification.
Those limits are not the final product definition.

A real Codex proof attempt already occurred:

- one controller dispatch;
- one real Codex/model start;
- requested proof file/content created locally;
- Codex did not produce the required commit/push;
- terminal result was persisted as UNKNOWN;
- second poll was NO-OP with no redispatch.

That consumed command must not be replayed. Do not claim closed-loop PASS.

## Next safe development direction

Without additional LIVE execution, the next implementation batch should favor:

1. keep the existing strict proof profile intact for regression;
2. add an autonomous policy/config layer rather than editing constants in place;
3. move start/turn budgets to task/campaign policy instead of runner-lifetime
   one-shot behavior;
4. add UNKNOWN classification and blocker isolation;
5. add safe stale-target replan state;
6. make round/turn/corrective/transient retry/concurrency/timeout values
   configurable;
7. design session/restart recovery around durable state;
8. add subscription-only policy gating without assuming an unreadable quota is
   exhausted;
9. preserve an upgrade path toward upstream Symphony or maintain a separate
   upstream-compatible track;
10. validate with static/unit/restart/fault fixtures before requesting another
    LIVE proof.

Do not call the loop complete on a one-round proof. Completion requires
multi-round unattended behavior with success->next-task, failure->recovery or
corrective work, session resume, duplicate suppression and configured stopping
conditions.



## Implemented STATIC checkpoint after the design handover

The branch now includes a pure autonomous policy/runtime layer:

- strict proof policy remains separately represented and pinned to one round /
  one turn / one model start;
- hardened and upstream-reference profiles expose openable round/turn/start/
  corrective/retry/concurrency/time valves;
- durable campaign state can serialize/restore tasks, rounds, blockers,
  decisions, processed result IDs and generation;
- three-round continuation, corrective task creation, typed UNKNOWN recovery,
  stale replan, blocker isolation, duplicate suppression, guarded restart
  reclaim and subscription-only quota behavior have STATIC tests;
- no provider/model LIVE execution is performed by these modules.

This checkpoint is not the finished loop. The next safe work is controller/runner
integration plus durable GitHub persistence for campaign state, followed by
restart/fault and exact-head CI evidence. Do not collapse these new semantics
back into the strict proof profile.



### Task-scoped strict runner budget

The strict Codex adapter now sources its one-turn/one-start constants from
`STRICT_PROOF_POLICY` and counts model-start attempts per durable command task
identity instead of for the entire runner lifetime. Repeating the same strict
task remains blocked; a distinct task can use a separate proof budget. Durable
claims/results still prevent cross-session replay.



### Durable campaign checkpoint store

`symphony_campaign_store.py` now provides create-only, hash-linked campaign
checkpoints with stale-revision fencing and ambiguous-write readback. A fresh
controller can restore the latest durable `CampaignState` and retain duplicate
result IDs, task status, blockers, counters and generation. The store never
updates default branch and does not start a provider/model.



### STATIC durable controller integration

A new `symphony_autonomous_controller.py` drives the durable Track-B kernel
through multiple tasks and checkpoints without any provider/model path. It
writes the RUNNING checkpoint before fixture dispatch, checkpoints the result,
then keeps selecting safe work. Tests include multi-round continuation,
corrective recovery, fresh-session resume, observation-only transient recovery,
stale replan, blocker isolation, quota gating and ambiguous-result checkpoint
recovery.

The next production step is not to remove the STATIC gate casually. Add a
separate reviewed adapter that binds real provider dispatch identity/result
evidence to durable task attempts, then prove restart/reconciliation before any
new LIVE run.



### Upstream reuse pin

Reuse decisions are now pinned in `docs/SYMPHONY_UPSTREAM_REUSE_MATRIX.md` and
`automation/command_bus/symphony_upstream_reference.json` against
`openai/symphony@be10a1b79df723d6d7612b5651c8522704dafb2e`.
Do not rebuild its workspace, same-session multi-turn, polling/reconciliation,
backoff or stall machinery inside the hardened kernel unless an incompatibility
is demonstrated. Track B should wrap those behaviors with durable GitHub
identity/evidence instead.



### Autonomous attempt ledger

A separate `symphony_attempt_store.py` now preserves attempt intent, observed
start and terminal evidence without changing the Phase-0 PREPARE_ONLY executor
contract. Restart classification distinguishes unstarted intent,
started-unresolved and terminal attempts. Started-unresolved work cannot be
blindly redispatched; unstarted work requires explicit stopped/fenced evidence
before reclaim.

This is STATIC evidence infrastructure only. The next safe step is to reconcile
these attempt records with campaign checkpoints so a terminal attempt can repair
a missing post-result campaign checkpoint, and a started-unresolved task can be
isolated while independent work continues.

## Stop / human boundary

Stop for genuinely human-required operations such as merge, default-branch
direct mutation, force/history rewrite, destructive deletion, billing/credit
changes, credential/permission/secret changes, irreversible scope expansion or
a genuine campaign-wide HARD_UNKNOWN.

If only one task is blocked, continue independent safe work.

## Final reminder

The user explicitly values efficiency and unattended continuation over
maximizing fail-closed behavior. Do not reintroduce Phase 0's global
`retry=0 / fallback disabled / UNKNOWN=STOP` semantics into the autonomous
loop as a blanket rule.

**Build a loop that keeps working safely, not a safety mechanism that happens to
loop once.**
