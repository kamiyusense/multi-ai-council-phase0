# Blue Work ↔ Jules Webhook Closed-Loop Roadmap

Updated: 2026-10-01  
Status: proposed execution roadmap / documentation only  
Pilot lane: 💙 J-BLUE + 💙 Cloud Work Blue  
Source policy: PR #191 Controller Operating Guide + PR #192 Development Acceleration Playbook + PR #193 Signal roadmap pattern + PR #194 Relay minimal-reuse roadmap + PR #115 Work-event-loop static research

### PR #217 current 2026-10-02 checkpoint

Read [the review-ready checkpoint](BLUE_WORK_REVIEW_READY_20261002.md).
BWJ-1–3 and captured BWJ-5/6 are STATIC-ready. Existing Blue/Green/Red read-only
COMMENT wake/isolation were read back; Yellow woke but tree proof is UNKNOWN.
One schema-v3 global Loop125 was reserved and one Jules Session accepted.
Work independently rejected its raw PR227 semantics; Controller repairs are
tested separately. The completed Session GET failed closed; authenticated source
and automatic Actions→carrier-review transport remain UNKNOWN/NOT_WIRED.
BWJ-4 full event bridge, M3/M4 adoption/cycle and continuous operation are not complete.
Final independent repaired-code delta PASS at931697e; exact-head Actions987/skip1 passed.
LIVE9/10 used; source UNKNOWN stops new Jules/adoption. Evidence-only child commits
preserve independently reviewed code. Merge stays withheld. The following STATIC section is historical.

### PR #217 experimental STATIC checkpoint

Read [the autonomous batch handover](BLUE_WORK_AUTONOMOUS_BATCH_20261001.md)
before continuing this experiment. BWJ-1/2 now share only the necessary color
metadata; Blue compatibility remains tested. Receipt replay protection binds
command ID, target repository/PR/branch/HEAD and worker generation. Complete
GitHub GET pagination and fail-closed source capture are implemented.
BWJ-5 captured reviewer-contract consumption and BWJ-6 formal schema-v3
next-task preparation are mock/static-ready. The next claim is NOT_RESERVED.
BWJ-4 real transport proof is still NOT EXECUTED; these additions do not make
M2/M3 or any live milestone complete. No change to the four carriers is made.

## 1. Purpose

This roadmap defines the smallest path from the current human-triggered Jules semi-auto loop to a durable event-driven development loop in which:

```text
Jules = bounded implementation worker
Cloud Work = reviewer / controller / next-task planner
GitHub = durable state, event bus, evidence and replay guard
Chat = human-facing supervisor only when a real human boundary is reached
```

The first implementation target is the existing 💙 lane only.

The goal is not a literal infinite process. The target is:

> continue automatically while the next action is bounded, authorized and evidence-backed; stop at a real HUMAN / BLOCKED / UNKNOWN / terminal boundary.

Do not replace the current Jules command bus, Cloud Work carrier, global Loop claim ledger, exact-head gates, terminal receipts, generation fencing or human Merge boundary.

## 2. Read order and authority

For this work, read:

1. current `README.md`
2. current `HANDOVER_CURRENT.md`
3. current `docs/DEVELOPMENT_EXECUTION_ROUTER.md`
4. current `docs/DEVELOPMENT_ACCELERATION_PLAYBOOK.md`
5. this roadmap
6. current `docs/CLOUD_WORK_LANES_INDEX.md`
7. selected 💙 Cloud Work carrier protocol/state
8. current Jules carrier branch:
   - `docs/JULES_PARALLEL_COLOR_LANES.md`
   - `docs/CHAT_JULES_API_SEMIAUTO.md`
   - `docs/JULES_TASK_PROMPT_SPEC.md`
   - `docs/JULES_CONTROLLER_OPERATING_GUIDE.md`
   - current request/claim validators and global Loop claim ledger
9. `docs/WORK_EVENT_LOOP_RESEARCH_20260929.md` only as historical/static evidence when useful

Fresh GitHub state wins over every PR number, SHA, generation, session ID and snapshot in this file.

## 3. Current checkpoint

Fresh readback at roadmap creation:

- main = `63ae5fc8f83a6f5e24ed960c4347e59a26954fdd`;
- PR #191 and PR #192 are merged and define current Controller/reuse-first policy;
- PR #194 is merged and demonstrates the current "small named primitive first" roadmap style;
- PR #193 is still OPEN and is reference material for staged roadmap structure, not current-main authority;
- PR #115 remains OPEN historical/static evidence for GitHub event → Work → Jules feasibility;
- Jules command carrier `feature/chat-work-command-bus` = `ba7e42de6e3ee0a008600a2fede2794de4c413f2` at this snapshot;
- 💙 Cloud Work carrier PR #167 is OPEN/draft/unmerged at `5f9e210bc17ed695610e23b1c1699e11f5c8ed4b`;
- Blue worker state reports `active_generation=1` at this snapshot.

These values are navigation evidence only. Re-read before any implementation or dispatch.

## 4. Fixed architecture: do not swap components

Keep the existing pieces:

- GitHub PR/review/comment events;
- 💙 Cloud Work carrier PR and event-triggered Work;
- Jules global Loop claims;
- existing Jules command JSON and GitHub Actions single-submit route;
- Jules API / `google-labs-code/jules-action`;
- isolated Jules work branches;
- current Controller independent review;
- exact target HEAD/tree verification;
- terminal receipts;
- Cloud Work generation fencing.

Do not add, as a prerequisite:

- a custom webhook server;
- a new queue or DLQ;
- a new database;
- Temporal/Inngest/Svix deployment;
- a second orchestration service;
- a second Jules dispatcher;
- a new dashboard;
- a new generic event framework.

Use GitHub as the durable round-trip surface.

## 5. Prior-art parts to borrow, not platforms to adopt

### 5.1 HiveMind Actions — review → Jules feedback → PR update → review

Useful idea:

- PR review decides pass/fail;
- failure sends bounded feedback to the existing Jules session;
- Jules updates the PR;
- the PR update wakes the reviewer again.

Borrow the loop shape. Do not copy its retry policy; Phase 0 keeps the current retry/fallback contract.

### 5.2 OpenCara — one event maps to one stage

Useful ideas:

- `pull_request.opened` for initial review;
- `pull_request.synchronize` for follow-up review;
- review/fix stages are separate;
- cheap event pre-filter before starting expensive agent work;
- follow-up rounds can use a lighter review path;
- newer PR state can pre-empt stale review work;
- content identity can dedupe logically duplicated deliveries when transport IDs are insufficient.

Borrow only the smallest event-routing primitive actually needed.

### 5.3 PR #115 — a Work wake is a hint, not correctness evidence

Event-triggered Work may observe coalesced or delayed PR activity.

Therefore:

> wake → fresh GitHub reconciliation → decide what is unprocessed

Never assume:

> one webhook wake == one exact Jules event

The durable command/claim/receipt/HEAD state remains authoritative.

## 6. Core event loop

Target shape:

```text
💙 Cloud Work
  → verify/adopt one Jules result
  → choose one next bounded mission
  → create/read back global Loop claim
  → create isolated Jules work branch
  → append one Jules command
  → existing GitHub Actions single-submit route
  → Jules session accepted
  → Jules publishes PR/commit
  → GitHub PR event
  → tiny wake adapter
  → one [CW_BLUE_V1] COMMENT review on carrier #167
  → 💙 Cloud Work wakes
  → reconcile from GitHub
  → repeat
```

There is no continuously running controller process. Each Work/Jules turn may end. GitHub reconnects the turns.

## 7. Wake adapter contract

The wake adapter is the smallest missing webhook-side primitive.

It should:

1. receive only the selected GitHub result events;
2. reject unrelated events before Work is started;
3. fresh-read the result PR and exact current head;
4. verify that the result belongs to a current Jules command/claim/session lineage;
5. derive one deterministic Cloud Work `command_id` from stable result identity;
6. check the Blue carrier for an existing command with the same `command_id`;
7. if already present, NO-OP;
8. otherwise submit exactly one COMMENT review beginning with `[CW_BLUE_V1]`;
9. bind `expected_target_head` to the exact result head;
10. end.

Do not perform semantic review inside the adapter.

Suggested logical command identity:

```text
blue-jules-result-pr<PR>-<FULL_HEAD_SHA>
```

A genuinely new head gets a new identity. Re-delivery of the same result maps back to the same identity.

Do not add a new database only to store this mapping.

## 8. Event selection

Start narrow.

### Initial success-path event

Prefer the ordinary GitHub PR result event already produced by Jules:

- `pull_request.opened`, when Jules opens a new result PR;
- `pull_request.synchronize`, when Jules pushes a follow-up result.

The adapter must verify lineage before creating a Work command. Branch name alone is not enough.

### Do not use as the main backbone

Do not make a long `workflow_run → workflow_run → ...` chain the durable loop backbone.

Return to an ordinary GitHub PR event between turns.

### Failure/no-change gap

A Jules session can fail, need input or complete without producing a new PR head. That may produce no useful PR webhook.

Do not build a large observer subsystem in advance.

First prove the normal PR-result path. After an observed gap, add the smallest terminal observer over existing Jules Session/Activity readback needed to emit one durable wake/event.

## 9. Duplicate and stale work handling

Reuse the half-loop controls before inventing new machinery.

### Duplicate wake

Before posting a Blue command review, look for the same deterministic `command_id`.

If found: NO-OP.

### Duplicate Work execution

The Blue worker still applies its normal:

- generation fence;
- command identity;
- terminal receipt guard;
- exact target HEAD gate.

### Stale result

If the target PR has already moved past the command's `expected_target_head`, Work must not act on the stale snapshot.

### Newer head while adapter is running

The GitHub workflow/adapter may use per-target-PR concurrency so a newer result can supersede an adapter that has not yet emitted a command.

If an older command was already durably written, do not delete or rewrite it. Let exact-head validation make it terminal STALE/NO_OP as appropriate.

## 10. Work Controller responsibility

Once woken, 💙 Cloud Work performs the role currently held by the Chat Controller for this bounded loop:

1. fresh-read carrier, worker generation and exact triggering command;
2. fresh-read Jules claim/command/session/result PR;
3. verify branch/session/result lineage;
4. independently inspect changed paths, diff, semantics, tests and evidence;
5. decide PASS / FAIL / BLOCKED / UNKNOWN;
6. apply only Controller-safe small repair where current policy permits;
7. otherwise produce a bounded corrective/new mission;
8. adopt/publish only through the already-authorized non-default target route after current verification;
9. select the next worker according to the current Controller Guide;
10. for the Blue closed-loop pilot, use 💙 J-BLUE when Jules is selected;
11. create the next Jules claim/branch/command only after fresh target readback;
12. write a terminal Blue receipt/evidence and end.

Do not treat a Work self-report as proof. GitHub/test/readback evidence remains required.

## 11. Full review vs follow-up review

Borrow OpenCara's cost-saving split.

### First result for a mission

Use the normal full Controller review:

- ancestry/lineage;
- full allowed-path check;
- semantic acceptance;
- negative cases;
- required test evidence;
- exact target state.

### Follow-up result after a bounded corrective

Keep the same mandatory safety gates, but focus semantic review on:

- the previous unresolved findings;
- changed delta from the previously reviewed result;
- regressions directly affected by the corrective.

Do not reread unrelated architecture merely because another fix round occurred.

If delta review cannot establish correctness, fall back to the full review.

## 12. Execution roadmap

Only implement the next incomplete stage.

### BWJ-0 — Canonical roadmap and recovery navigation

Goal: make a fresh Chat/Work able to find this plan without remembered PRs.

Actions:

1. add this roadmap from current main;
2. link it from HANDOVER_CURRENT;
3. link it from the Development Acceleration Playbook;
4. link it from the Cloud Work lane index;
5. keep it explicitly Blue-first and not-yet-live.

Exit:

- fresh navigation reaches this roadmap;
- no Work/Jules event or live model started;
- no Cloud Work setting changed.

### BWJ-1 — Pure wake identity + event classifier

Goal: isolate the event-to-command decision before any GitHub write.

Build the smallest pure helper over fixture payloads:

- accepted event kind/action;
- repository/PR identity;
- current result head;
- deterministic Blue `command_id`;
- lineage inputs;
- IGNORE / WAKE / UNKNOWN result.

Reuse existing command/claim parsers where possible.

Minimum fixtures:

- matching Jules result opened;
- matching Jules result synchronize;
- unrelated human PR;
- wrong repository;
- missing head;
- stale/non-matching lineage;
- duplicate same result identity.

Exit:

- pure tests green;
- zero GitHub write;
- no webhook server.

### BWJ-2 — Prepare-only wake adapter

Goal: construct the exact Blue command review without posting it.

Input:

- accepted BWJ-1 result;
- current Blue carrier protocol/state;
- exact result PR/head.

Output:

- complete `[CW_BLUE_V1]` review body;
- deterministic command_id;
- current worker_generation;
- exact target identity/head;
- bounded review/controller task;
- retry=0 / fallback disabled.

The adapter must not create a second Jules command.

Exit:

- schema/fixture tests;
- duplicate existing command → NO_OP;
- stale head → STALE/BLOCKED before write;
- no GitHub write.

### BWJ-3 — Mock/static webhook round trip

Goal: prove the wiring without Work or Jules live execution.

Fixture flow:

```text
mock Jules PR event
→ classifier
→ prepare-only Blue wake command
→ mock Work receipt
→ mock Controller next-task decision
→ existing Jules command preparation
→ mock result event
→ duplicate event replay
```

Verify:

- one logical result creates at most one Blue command;
- duplicate result is NO-OP;
- new head creates a new identity;
- stale old head cannot mutate target;
- worker generation mismatch fails closed;
- terminal receipt prevents replay;
- no Merge/default write/live model.

Exit: static E2E green using existing fixtures/helpers wherever possible.

### BWJ-4 — Real GitHub event → read-only Blue Work wake proof

Goal: prove the actual event-trigger transport before giving Work controller authority.

Use a disposable/non-production result fixture.

Flow:

```text
one real GitHub PR result event
→ wake adapter
→ one Blue carrier COMMENT review
→ event-triggered Blue Work
→ read-only reconciliation
→ matching terminal receipt
```

The Work task must not publish a target change or start Jules.

Verify:

- correct Work woke;
- generation matches;
- exact event/result recovered from GitHub;
- target unchanged;
- one command / one terminal receipt;
- duplicate/re-delivery does not create a second logical command.

This is a live event-trigger proof and requires the normal authorization boundary applicable at execution time.

### BWJ-5 — Work reviews one existing Jules result

Goal: move independent Jules result review from Chat to Work without starting a new Jules task.

Use an already-existing bounded Jules result.

Work performs:

- lineage;
- paths;
- semantics;
- tests/evidence;
- exact-head;
- PASS/FAIL/UNKNOWN;
- next bounded task proposal only.

It writes durable evidence/receipt but does not dispatch the proposed Jules mission yet.

Exit:

- Work review agrees with independent readback;
- result and next-task proposal are recoverable from GitHub;
- no second Jules session.

### BWJ-6 — Prepare-only next-Jules handoff

Goal: let Work build the exact next Jules claim/branch/command package without live submission.

Reuse current:

- global schema-v3 Loop claim;
- J-BLUE lane metadata;
- Task Prompt spec;
- exact target HEAD/tree;
- isolated work branch rule;
- command validator.

Initially stop before the external Jules submit.

Exit:

- next mission can be reconstructed from GitHub;
- no claim collision/reuse;
- no ambiguous write replay;
- exact validator green.

### BWJ-7 — One live Work → Jules → Work cycle

Goal: prove one complete closed-loop turn.

After explicit live authorization:

```text
Blue Work reviews result A
→ adopts/publishes allowed target change
→ creates one next J-BLUE mission
→ existing Actions route submits once
→ Jules result B appears
→ GitHub event
→ wake adapter
→ Blue Work wakes and reviews B
→ STOP
```

Stop after the second Work review even if another safe task exists.

Evidence:

- original Work command/receipt;
- exact global Loop claim;
- one Jules submit and accepted session;
- result PR/head;
- wake identity;
- second Work command/receipt;
- no duplicate submit;
- target/canonical readback.

### BWJ-8 — Small multi-cycle soak

Goal: prove that recovery/duplication/stale handling survives more than one turn.

Start with a small explicit budget such as 2–3 cycles, not an unbounded rollout.

Inject/observe:

- duplicate result event;
- result head advances before review;
- one Work wake delayed;
- one no-op/corrective result;
- independent lane activity advances a shared target.

Exit:

- no duplicate Jules submit;
- no stale publication;
- canonical adoption remains serialized;
- terminal state remains reconstructable from GitHub.

### BWJ-9 — Autonomous-until-boundary mode

Goal: remove routine human "continue" input.

Work may continue only while:

- next mission is bounded and unambiguous;
- repository/branch/purpose remains authorized;
- exact target state is fresh;
- required evidence is available;
- Jules/Work capability remains available;
- no human-only boundary is reached.

Stop automatically on:

- Merge requirement;
- default-branch direct write;
- destructive/history-changing operation;
- billing/permission/secrets/settings boundary;
- material architecture/product decision;
- unresolved semantic ambiguity;
- repeated no-progress result;
- unavailable/unverified Work/Jules result;
- no next useful bounded mission.

"Autonomous" does not mean "ignore terminal receipts" or "invent work forever."

### BWJ-10 — Failure/no-change terminal wake only if proven necessary

Goal: close the one remaining success-path gap: Jules terminates without a useful PR head event.

Only implement after BWJ-4 through BWJ-8 show that ordinary PR events are insufficient.

Prefer the smallest adapter over existing Jules Session/Activity readback.

Do not add:

- a permanent generic polling service;
- a second queue;
- a second scheduler;
- a new state database.

If a small existing GitHub scheduled/dispatch mechanism can reconcile a known active session and emit one durable result event, prefer that.

## 13. No-progress guard

Do not let a semantically unchanged fix cycle ping-pong forever.

Before another corrective mission, compare:

- previous unresolved finding;
- new result head/diff;
- direct acceptance evidence.

If the same material finding remains and the new result provides no meaningful corrective change, classify the cause before dispatching again.

Use the existing Controller Guide's repeated-FAIL analysis.

Do not invent a large finding database. A small durable evidence record/signature may be added only if ordinary receipt/command evidence proves insufficient.

## 14. Interaction with parallel lanes

Jules lanes may work in parallel.

Cloud Work lanes are independent event-triggered workers.

For this pilot:

- controller lane = 💙 Cloud Work Blue;
- implementation lane = 💙 J-BLUE.

Do not reuse Blue Work generation as a Jules Loop generation/number.

Do not reuse Jules global Loop claim identity as a Work command identity.

When another lane advances a shared canonical target:

1. re-read canonical HEAD/tree;
2. stale candidates do not publish;
3. revalidate ancestry/diff/tests;
4. canonical adoption remains one result at a time.

## 15. What this roadmap explicitly does not authorize

This documentation does not itself authorize:

- a new live Jules session;
- changing Cloud Work settings/triggers;
- enabling an unbounded autonomous loop;
- PR Merge;
- main/default direct writes;
- force push/history rewrite;
- branch deletion;
- billing/credits/overages changes;
- API key creation/display/mutation;
- permission/admin changes.

Static implementation/mock/fixtures/docs can proceed under the normal repository rules. Live activation uses the current explicit approval boundary.

## 16. Milestones

### M1 — Webhook bridge static-ready

BWJ-0 through BWJ-3 complete.

Result:

- one stable result identity;
- one prepared Blue wake command;
- duplicate/stale behavior proven statically;
- no live Work/Jules dependency.

### M2 — Real Work wake proven

BWJ-4 complete.

Result:

- real GitHub result event wakes exactly the intended Blue Work path;
- GitHub readback proves the result;
- no target mutation.

### M3 — Work replaces Chat review for one result

BWJ-5 and BWJ-6 complete.

Result:

- Work can inspect one Jules result and prepare the next exact mission from GitHub.

### M4 — One closed-loop turn

BWJ-7 complete.

Result:

- Work → Jules → GitHub → Work is operational once, with durable evidence.

### M5 — Bounded autonomous development

BWJ-8 and BWJ-9 complete.

Result:

- routine "continue" input is no longer required while bounded work remains;
- human is reintroduced only at a defined stop boundary.

### M6 — Terminal-gap closure

BWJ-10 only if needed.

Result:

- failure/no-change Jules terminal states can also wake reconciliation without adding a general orchestration platform.

## Isolated autonomous experiment (STATIC only)

See [BLUE_WORK_AUTONOMOUS_EXPERIMENT_20261001.md](BLUE_WORK_AUTONOMOUS_EXPERIMENT_20261001.md)
for the isolated PR203-based snapshot reconciler, offline Actions replay,
verification evidence and remaining production/LIVE blockers. This does not
change BWJ-4 authorization or declare BWJ-5/6 complete.

## 17. Navigation summary

```text
README
→ HANDOVER_CURRENT
→ DEVELOPMENT_EXECUTION_ROUTER
→ DEVELOPMENT_ACCELERATION_PLAYBOOK
→ BLUE_WORK_JULES_WEBHOOK_LOOP_ROADMAP
   ├─ Cloud Work 4-lane index
   │   └─ 💙 carrier protocol + worker state
   ├─ Jules current carrier
   │   └─ Color Lane → Semi-Auto → Task Prompt → Controller Guide
   └─ historical proof/reference
       └─ WORK_EVENT_LOOP_RESEARCH_20260929
```

If this roadmap conflicts with fresh GitHub state, fresh state wins.

If it conflicts with a formal safety/authorization contract, the stricter current contract wins.
