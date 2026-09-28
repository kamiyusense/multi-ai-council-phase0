# Phase 0 Control Tower v2 — CT-2 prepare-only checkpoint

## Baseline

- Repository: `kamiyusense/multi-ai-council-phase0`
- Baseline main:
  `26c433afb08191a8cc1d6e0ea640889c70b8410d`
- PR #77 CT-1 static foundation: merged.
- Issue #33 at batch start:
  `🚦 Phase 0 Loop Status — ⚫ STOPPED`
- Issue #33 comments at batch start: 0.

## Boundary

This batch prepares the single-loop -> Multi-loop Control Tower migration without
performing any live Issue mutation.

It adds no GitHub network client and contains no PATCH/POST path.

## Implemented

`automation/command_bus/control_tower_issue_plan.py` adds a pure prepare-only
migration boundary.

Given:

- an already-built verified `ControlTowerModel`;
- a fresh Issue #33 readback;
- optional existing comment bodies for dedupe;

it prepares:

- exact expected aggregate title;
- exact expected Control Tower body;
- Development-block-preserving migration output;
- bounded notification plans for TURN_COMPLETE / HUMAN_NEEDED only.

## Pre-write conflict gate

The planner records the exact base Issue snapshot.

Before any future live write, `assert_issue_unchanged` requires Issue #33 to
still match the base:

- issue number;
- open state;
- title;
- body.

Any change blocks overwrite.

This preserves the existing Signal rule that an Issue edit after readback must
not be overwritten blindly.

## Post-write readback gate

`verify_issue_applied` requires exact title/body readback after a future write.

A mismatch is failure/UNKNOWN at the live adapter layer; this module never
blindly retries.

## Notification semantics

The prepare layer does not infer notification events from display state.

Only lanes whose durable event kind is explicitly:

- `TURN_COMPLETE`; or
- `HUMAN_NEEDED`

produce a notification plan.

A BLOCKED/UNKNOWN display lane without such a durable event kind does not invent
a comment.

Dedupe marker identity is:

`kind + loop_id + durable event_id`

Existing matching markers are replay NO-OP for that lane/event only.

## Private data boundary

Notification bodies use only bounded Control Tower lane fields and safe detail
refs such as `issue:33` / `pr:N`.

No private ChatGPT / Claude / Work URL is accepted by the CT-1 registry, and
this CT-2 planner introduces no new URL field.

## Tests

Coverage includes:

- single-loop legacy body -> multi-loop title/body plan;
- Development managed block preservation;
- no mutation of caller model/Issue input;
- title/body/state conflict detection before write;
- exact post-write readback requirement;
- only TURN_COMPLETE/HUMAN_NEEDED notification planning;
- loop-specific durable-event replay NO-OP;
- BLOCKED/UNKNOWN display alone does not invent notification;
- private URL absence from notification plans;
- wrong/closed Issue rejection;
- already-matching Issue -> Issue update NO-OP and comment replay NO-OP.

## Explicitly not performed

- no live Issue #33 PATCH;
- no live Issue #33 comment POST;
- no workflow_dispatch;
- no owner/runtime ledger write;
- no provider/model/Jules/Claude execution;
- no live Control Tower migration;
- no Windows executable;
- no Merge in this batch.

## Remaining CT-2 live boundary

Still required before live migration:

1. production multi-loop collection of already verified per-loop projections;
2. exact durable loop IDs for the real lanes, or an explicitly accepted
   presentation-only registry mapping to verified durable loop IDs;
3. live adapter that performs one Issue update attempt only after the conflict
   gate and exact readback;
4. live notification adapter that preserves loop_id + durable event_id dedupe;
5. explicit human approval for the first deployed Issue #33 migration.

This batch intentionally stops before those live effects.

## Exact-head verification

- exact tested PR head:
  `af2ebd5d89cc2f4a649bc8755d8cd8e556fc35a0`
- GitHub Actions run:
  `36374751234` — **SUCCESS**
- focused Status/runtime/validation suite:
  **207/207 PASS**
- full command-bus suite:
  **494/494 PASS**
- command-bus JSON schemas parsed:
  **19/19 PASS**
- Python compileall:
  **PASS**
- `git diff --check`:
  **PASS**
- representative CT-2 prepare tests were present in the exact-head CI log:
  - legacy -> multi-loop migration planning;
  - pre-write Issue conflict rejection;
  - TURN_COMPLETE/HUMAN_NEEDED-only notification planning;
  - loop/event replay NO-OP.
- tested head -> current head compare:
  to be read back after this documentation-only evidence commit.
- Issue #33 live mutation:
  **NONE required; fresh readback must remain the deployed pre-migration Status.**

## Verified per-loop input bridge

Added `automation/command_bus/control_tower_verified_input.py`.

This bridge accepts only the existing `TransitionProjectionResult` from the
durable transition path.

Rules:

- VALID / TERMINAL / BLOCKED results may be forwarded when projection and owner
  decision are present;
- UNKNOWN returns no Control Tower lane input and is therefore isolated as
  UNKNOWN by the CT-1 aggregator;
- generation comes only from the existing `OwnerDecision`, not from caller
  presentation metadata;
- target_ref remains a bounded safe presentation ref such as `pr:4`;
- durable event kind is optional and is never inferred by the bridge;
- no private/external URL is accepted as target_ref.

The bridge does not inspect state/receipt/evidence/provider/target/authority
records itself and therefore does not duplicate durable correctness logic.

Additional tests cover:

- VALID transition forwarding;
- existing BLOCKED projection preservation;
- UNKNOWN not promoted to a healthy lane;
- accepted result requiring projection + owner decision;
- generation sourced from owner decision;
- private/unbounded target-ref rejection;
- durable-event-kind boundedness and non-inference;
- input immutability.

## Retry-zero publisher boundary

Added `automation/command_bus/control_tower_issue_publisher.py`.

This is transport-neutral only. No production GitHub transport is implemented.

Behavior:

- exact Issue plan is read back before write;
- conflicting Issue snapshot stops before PATCH;
- at most one Issue PATCH attempt per exact plan in one publisher instance;
- ambiguous PATCH is resolved by exact Issue readback only;
- if the exact title/body appeared, the write is RECOVERED without resend;
- if exact readback is unavailable/mismatched, result is UNKNOWN and no retry is performed;
- each planned notification marker is checked before POST;
- at most one POST attempt per marker;
- ambiguous POST is resolved by marker readback only;
- exactly one marker proves the comment write;
- zero or duplicate marker readback is UNKNOWN;
- already-existing marker is replay NO-OP.

The in-memory replay sets are defense-in-depth for the static adapter and are
not claimed as durable production exactly-once state. Production correctness
continues to depend on fresh GitHub readback and durable loop_id + event_id
markers.

Mock tests cover:

- normal Issue PATCH + notification verification;
- ambiguous PATCH recovered by readback;
- ambiguous PATCH without applied readback -> UNKNOWN;
- pre-write conflict -> no write;
- already-matching Issue -> PATCH NO-OP;
- existing notification marker -> POST NO-OP;
- ambiguous comment recovered by marker readback;
- unresolved ambiguous comment -> UNKNOWN without resend;
- exact-plan replay guard;
- duplicate marker readback rejection;
- malformed comment readback rejection.

No live Issue write is executed by these tests.
