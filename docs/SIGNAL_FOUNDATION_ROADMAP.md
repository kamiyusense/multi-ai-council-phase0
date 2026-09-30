# Signal Foundation Roadmap — post PR #192

Updated: 2026-10-01
Status: current Signal / Control Tower execution roadmap

## 1. Purpose

This is the execution roadmap for Phase 0 Signal / Control Tower work after
PR #192 (Development Acceleration Playbook) reached main.

Goal:

> Reuse proven repository/platform primitives, reach a useful observable Signal
> quickly, and keep the existing strict durable proof only where runtime mutation
> actually needs it.

This document changes implementation order, not the formal safety boundary.

## 2. Read order and authority

For Signal / Status / Control Tower work, read:

1. README.md
2. HANDOVER_CURRENT.md
3. docs/DEVELOPMENT_EXECUTION_ROUTER.md
4. docs/DEVELOPMENT_ACCELERATION_PLAYBOOK.md
5. this file
6. only the task-specific Control Tower / Status / Semi-Auto documents needed
   by the current stage

docs/PHASE0_CONTROL_TOWER_V2_ROADMAP.md remains the design source for the final
verified multi-loop Control Tower and Windows companion.

This roadmap supersedes only the old implementation ordering where read-only
presentation had to wait for complete durable runtime adoption.

Fresh GitHub state wins over old PR numbers, SHAs, sessions or checkpoint text.

## 3. Current checkpoint

Fresh readback at roadmap creation:

- main = e3f01cceeea0f01c9654c7b539923fa12f6b04cd
  - PR #192 merged;
  - Development Acceleration Playbook is canonical;
  - CT-1 static Control Tower foundation implemented;
  - CT-2 migration preparation / registration / live-preflight / collector
    foundations implemented;
  - Issue #33 live single-loop -> multi-loop migration NOT STARTED;
  - production Control Tower lanes remain PLACEHOLDER.
- historical Signal branch =
  feature/signal-semiauto-stable-id-adoption-v1
  - contains useful validated Signal work;
  - is no longer current-main based;
  - fresh compare: 10 commits ahead / 15 behind main.
- PR #189 is historical candidate evidence for the bootstrap persistence adapter.
  Repaired head e22fb9f9543c8887480597c9e947fe1a6a22e7fa passed:
  - focused: 452 tests, 1 skip;
  - full command-bus: 806 tests, 1 skip;
  - compileall: PASS;
  - git diff --check: PASS;
  - production Control Tower registry unchanged.

Therefore the old Signal branch is a parts bin / evidence source, not the new
canonical integration base.

## 4. Core split: observed Signal vs verified runtime truth

### 4.1 Observed Signal — build first

Observed Signal reports direct provider/platform facts only.

Examples:

- Jules Session state is IN_PROGRESS;
- Jules Session state is AWAITING_USER_FEEDBACK;
- Jules created a PR;
- the PR head is known;
- GitHub Actions for that exact head are running / success / failure;
- the result PR is ready for independent review.

Suggested display vocabulary:

- DISPATCHED
- IN_PROGRESS
- NEEDS_INPUT
- PR_READY
- VERIFYING
- PASS
- FAIL
- UNKNOWN

Observed Signal must not claim:

- durable loop ownership;
- verified controller authority;
- permission to mutate runtime state;
- safe takeover;
- registry DURABLE eligibility.

Silence, ETA, timestamps or PR activity must not be promoted into owner/liveness
truth.

### 4.2 Verified durable runtime — keep strict

The existing durable path remains authoritative for real runtime ownership,
AUTO/SEMI_AUTO takeover, registry promotion and the final verified Runtime
projection.

That path continues to use the existing stable loop ID, state, owner generation,
fencing, receipt, evidence, provider observation, target verification, authority
and accepted durable transition contracts where applicable.

Observed Signal never weakens or replaces that path.

## 5. Reuse rules specific to Signal

Reuse repository pieces before writing new subsystems:

- loop_status_development.py rendering / managed Issue block;
- existing Control Tower multi-loop renderer and snapshot model;
- existing Status write/readback conflict guard;
- existing Jules dispatch / session readback / same-session message workflows;
- existing GitHub PR / check / workflow readback;
- existing durable collector and transition validators when verified runtime
  truth is actually required.

Do not create a second:

- Issue renderer;
- PR creator;
- Jules scheduler;
- question protocol;
- GitHub result checker;
- owner validator;
- provider state machine;
- notification database.

Use Jules official Session / Activity facts directly.
Use same-session continuation for bounded questions.
Use Jules AUTO_CREATE_PR output instead of a custom PR publication layer.
Use GitHub PR/check/workflow state directly for result readiness.

Webhook ingress is not a Signal MVP prerequisite. If later required, follow
PR #192's minimum GitHub pattern: raw-body HMAC-SHA256, event/action filter,
X-GitHub-Delivery dedupe, small durable event, quick 2xx.

## 6. Execution roadmap

Only implement the next incomplete stage.

### SF-0 — Fresh current-main integration base

Goal: restart Signal integration from current main without destructive history
operations.

Actions:

1. create a fresh Signal integration branch from current main;
2. inspect the historical Signal branch file by file;
3. port only still-needed validated pieces;
4. prefer bounded patch/copy or small reimplementation over rebase/history
   rewrite;
5. rerun current-main tests after each bounded adoption.

Initial port candidates:

- canonical Semi-Auto runtime identity source;
- first-adoption bootstrap helper;
- PREPARED-state + source-receipt persistence adapter;
- focused tests/checkpoints;
- a short root AGENTS.md only if it still adds value beyond PR #192.

Do not blindly port the old acceleration research file where PR #192 supersedes
it.

Exit:

- branch descends from current main;
- selected Signal pieces pass current-main tests;
- registry remains PLACEHOLDER;
- no Issue #33 runtime migration.

### SF-1 — Observed Signal data model

Goal: represent real Jules/GitHub facts without claiming durable ownership.

Build the smallest pure adapter/model over:

- lane/display identity;
- Jules Session ID/ref;
- exact Jules Session state;
- optional safe latest-agent-message summary;
- result PR identity/head;
- exact-head GitHub check/workflow state.

Rules:

- official state only;
- no network inside the pure model;
- no inference from silence;
- malformed/missing source -> UNKNOWN;
- no private controller/chat URLs;
- observed state and verified durable state remain different types/fields.

Minimum tests:

- IN_PROGRESS;
- AWAITING_USER_FEEDBACK -> NEEDS_INPUT;
- PR + successful exact-head checks -> review-ready;
- failed session/check -> FAIL;
- missing/malformed input -> UNKNOWN.

Exit: pure fixtures green, zero Issue/runtime writes, no owner/authority
dependency.

### SF-2 — Reuse existing Development / Issue presentation

Goal: show Observed Signal without a new dashboard backend.

Prefer extending the existing GitHub-evidence Development presentation or the
existing Control Tower renderer with a clearly labeled Observed work section.

Keep the verified Runtime section separate.

Concept:

Observed work
- Chat -> Jules: IN_PROGRESS / NEEDS_INPUT / PR_READY / ...

Verified runtime
- existing durable Control Tower projection only

Exit:

- one fixture renders observed and verified sections side by side;
- observed data cannot alter verified runtime signal;
- malformed observed lane does not erase healthy lanes;
- no live Issue mutation yet.

### SF-3 — Same-session HUMAN NEEDED loop

Goal: keep minor Jules questions away from the user and avoid replacement
sessions.

Reuse the already-proven pattern:

Session readback
-> AWAITING_USER_FEEDBACK
-> inspect exact question
-> if small/reversible/repository-resolvable: Controller answers same session once
-> read back
-> continue same task

Escalate only for real human boundaries:

- Merge;
- default-branch write;
- destructive/history-changing operation;
- settings/permission/billing/secrets;
- new live provider execution/spend;
- material architecture/scope choice.

Loop 090 / PR #189 is historical evidence that same-session feedback can resume
the task and produce the result PR.

Exit:

- bounded Controller-answer vs human-required tests;
- same session preserved;
- no automatic resend after ambiguous message submission.

### SF-4 — Static observed end-to-end

Goal: prove the visible Signal path without a new live provider call.

Fixture:

dispatch accepted
-> Jules IN_PROGRESS
-> Jules AWAITING_USER_FEEDBACK
-> same-session answer
-> Jules PR available
-> exact PR head checks running
-> checks success
-> observed Signal becomes review-ready

Reuse existing fixtures. Do not add webhook service, DB, queue or generic
workflow engine.

Exit: one static E2E and existing regression green.

### SF-5 — One bounded live Observed Signal proof

Goal: verify usefulness before completing every durable runtime proof.

Use a normal already-authorized Jules development task as the lifecycle source.
Do not launch an extra provider merely to test Signal.

First live Issue #33 change remains a separate live-display boundary. Until that
is authorized, generate and verify the body/snapshot without publishing it.

Exit evidence:

- official Jules state readback;
- result PR/head readback;
- exact-head checks;
- generated observed Signal projection;
- no durable-owner claim.

### SF-6 — Port and finish Chat -> Jules durable seed path

Goal: return to durable correctness when real runtime ownership integration needs
it.

Port/revalidate the historical pieces onto current main:

canonical stable ID
-> first-adoption bootstrap PREPARE bundle
-> initial PREPARED state
-> canonical source receipt

Reuse RuntimeStateInitializer and CanonicalOwnerReceiptGitHubBackend. Do not
create a second writer.

Exit:

- current-main tests green;
- proof uses only intended non-default runtime-data surfaces;
- registry still PLACEHOLDER.

### SF-7 — Minimum trust proof for one real lane

Goal: satisfy the existing durable transition contract for Chat -> Jules using
the smallest trustworthy sources available.

Start from existing provider readback, provider verifier interface, owner
authority contract, target/receipt/evidence binding and collector.

Do not pre-build a general trust platform.

Wire only the minimum missing production trust source required by the current
formal contract.

Exit:

- one accepted real durable transition under the stable Chat -> Jules ID;
- exact durable readback;
- collector returns COLLECTED / accepted projection.

### SF-8 — Promote one lane to DURABLE

Only after SF-7 evidence:

1. fresh-read the accepted durable chain;
2. update the matching registry entry to the real stable loop ID;
3. set identity_state=DURABLE;
4. run registration/live-preflight;
5. keep other lanes PLACEHOLDER until independently adopted.

Registry promotion consumes evidence; it never creates evidence.

### SF-9 — Extend the same contracts to other lanes

After Chat -> Jules proves the pattern:

- Claude -> Gemini;
- Claude -> Claude;
- Work -> Gemini.

Reuse the same Observed Signal model and verified Control Tower model.
Each real runtime lane has a distinct durable ID.

Do not create provider-specific dashboards.

### SF-10 — Issue #33 verified multi-loop migration

Perform only after the required migration set passes the existing live-preflight.

Reuse existing migration/publisher/readback/rollback components.

Observed Signal work does not itself authorize this deployed Runtime migration.

### SF-11 — Windows Signal Companion

Start after the GitHub machine-readable projection is stable enough that the
client does not need command-bus internals.

Windows MVP remains read-only. It may be built before every future runtime
feature is complete, but only against a frozen projection contract.

## 7. Explicitly deferred from the Observed Signal MVP

Do not make SF-1 through SF-5 wait for:

- complete independent owner-authority platform;
- complete independent provider-attestation platform;
- Artifact Attestations / Sigstore;
- more OIDC proof architecture;
- Temporal / Inngest migration;
- new queue / DLQ;
- new event DB;
- GitHub Projects automation;
- CloudEvents SDK;
- Windows app;
- all four runtime lanes reaching DURABLE.

Bring one back only when its actual stage or an observed failure requires it.

## 8. Controller / Jules operating rule

For each Signal batch:

1. fresh-read current canonical target;
2. reuse an existing helper first;
3. define one implementation boundary;
4. use Jules for bounded implementation;
5. independently inspect session/base/diff/semantics/tests;
6. repair eligible small defects directly;
7. return substantial semantic defects to the same Jules session when safe;
8. exact-head test;
9. fast-forward only the authorized non-default integration branch;
10. remote readback;
11. continue to the next incomplete stage.

Do not return a typo, path mistake, fixture mismatch or small bounded assertion
repair to Jules merely to preserve role separation.

Do not patch a substantive semantic failure into a superficial green result.

## 9. Milestones

### Useful Signal MVP

The user can see from one bounded GitHub projection:

- whether Jules is working;
- whether Jules needs an answer;
- whether a result PR exists;
- whether exact-head checks are running/passing/failing;
- whether the user actually needs to act.

This milestone does not require all runtime lanes to be DURABLE.

### Verified Control Tower

The verified Runtime Control Tower is complete only after intended runtime lanes
are independently adopted through the durable contracts and the verified
multi-loop migration is accepted/read back.

These are intentionally separate milestones.

## 10. Navigation summary

README
-> HANDOVER_CURRENT
-> DEVELOPMENT_EXECUTION_ROUTER
-> DEVELOPMENT_ACCELERATION_PLAYBOOK
-> SIGNAL_FOUNDATION_ROADMAP
   -> observed work: existing Development / Status / Jules / GitHub helpers
   -> verified runtime: PHASE0_CONTROL_TOWER_V2_ROADMAP
                        + CONTROL_TOWER_REAL_LOOP_ID_ADOPTION_PLAN

If this roadmap conflicts with fresh repository state, fresh GitHub readback
wins.

If it conflicts with a formal safety contract for dangerous runtime mutation,
the stricter formal safety contract wins.
