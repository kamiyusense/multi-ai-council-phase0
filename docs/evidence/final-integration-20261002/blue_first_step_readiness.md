# PR #203 / Blue webhook loop: first real step readiness (prepared, NOT executed)

State read 2026-10-02 (fresh): PR #203 open draft head `66d36652`; PR #217 (stacked on it) draft head `9d2a2302`. The Blue thread's own checkpoint (`docs/BLUE_WORK_REVIEW_READY_20261002.md` on #217) records BWJ-1..3 STATIC-ready, supervised Work reviews done under its own approved budget (9 of its 10 used) and **BWJ-4 (real GitHub event -> read-only Blue Work wake) still not executed**. This batch did not start any Work or Jules run and used none of the Loop A slots.

## What the first real step (BWJ-4) would verify
One real GitHub PR result event on a disposable fixture -> wake adapter -> one Blue carrier COMMENT review -> event-triggered Blue Work -> read-only reconciliation -> one matching terminal receipt. It must not publish a target change or start Jules.
Pass criteria: correct Work woke; generation matches; exact event/result recovered from GitHub; target unchanged; one command and one terminal receipt; duplicate/redelivery creates no second logical command.

## Human approvals required before it can run
1. Explicit approval of a LIVE Work trigger (the existing user-set limit of 5 Work scheduled tasks applies; ordinary use of any LIVE slot is not covered by earlier approvals).
2. A decision whether the Actions-generated COMMENT review may be posted (the workflow today has read permission only: permission change = human).
3. A decision on the trust source for the event (webhook vs poll adapter); Loop A used the poll adapter.

## Preconditions that can be prepared without LIVE (all done or known)
- Latest #217 head passes its static suite; the contract patches in `docs/evidence/carrier-main-reconciliation-20261002/patches/` apply cleanly (the Blue E2E patch was re-verified on `9d2a2302`).
- Disposable fixture PR: not created (needs a write; prepare only when approved).
- Evidence plan: store the wake event id, the Work command/receipt ids, the before/after target head, in the existing `docs/evidence/blue-work-*` layout.

## Stop conditions (any one stops the run, nothing is retried)
Wrong Work woke; generation mismatch; target head changed; second command or second receipt; any UNKNOWN on trust source; any permission/billing prompt; budget exhausted.

## Rollback
The step is read-only on the target. Rollback = ignore the produced receipt and close the disposable fixture PR; no repository, secret or settings change is part of the step.
