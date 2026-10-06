# Claude × Jules Autonomous Loop — Current Handover

Last refreshed: 2026-10-07 JST.

This handover is subordinate to and must be read together with:

- `docs/AUTONOMOUS_DEVELOPMENT_LOOP_NORTH_STAR.md`
- `docs/CLAUDE_JULES_AUTOLOOP_INTEGRATION.md`
- `docs/CLAUDE_JULES_ROUTINE_WAKE_V1.md`

If an older document implies that one-shot safety, retry=0 everywhere, wake-and-report, or UNKNOWN-immediate-stop
is the final product goal, the North Star document wins for autonomous-loop completion semantics.

## 1. User intent that must not be lost

The loop exists to be useful, unattended, and long-running.

The user explicitly does NOT want a system that:

- succeeds once and asks "continue?";
- treats every UNKNOWN as a campaign stop;
- treats every retry as forbidden;
- requires human approval for every normal Jules round;
- wakes a controller only to report status and stop;
- lets one blocked task terminate unrelated safe work.

The desired operating principle is:

> Continue while safe work remains. Isolate blockers. Recover transient failures. Replan stale work.
> Return to the human only at a real boundary.

Phase 0 safety primitives are inputs to this loop, not the loop's global stop policy.

## 2. Fresh GitHub snapshot at this handover

Repository:
`kamiyusense/multi-ai-council-phase0`

Main:
`4007f0c334c31ee73c68e3a9becd35b2ea5f9b6d`

PR #319:
merged. It added the current Jules -> Claude Routine wake V1 design.

PR #220:
OPEN / Draft / unmerged.
Head at refresh:
`044389eb7760b80da23c2e193000bc8e019519d6`

This is the older Claude × Jules autoloop integration source PR.
Do not treat its old wording as the final autonomy policy without reconciling it with the North Star.

PR #322:
OPEN / unmerged.
Head:
`adbd5deff91b00e7fd85995c400fa759d6b9594c`
Base:
`jules-work/relay-dev-loop-139-live-proof-3-note`

PR #322 is the Loop 139 result candidate.
It remains intentionally unmerged and unadopted because the durable inspection is still UNKNOWN.

Loop A live budget ledger:
slot-01 through slot-06 exist.
Used = 6 / 10 in the historical proof budget.

Latest owner for `claude-auto-loop-a-003`:
- generation: 2
- owner_role: SEMI_AUTO
- holder_id: `chatgpt-semiauto-controller`
- event: HANDOFF / reclaim from expired AUTO
- target snapshot: `53f2caf67280ca1b4c019f325aea5fb9502f1114`

The reclaim was written and read back successfully.
Do not recreate generation 2.

## 3. What is already proven

The controller engine is not merely theoretical.

Historical live proof demonstrated:

- Claude -> Jules dispatch;
- Jules result PR;
- independent Claude inspection;
- PASS -> isolated-target adoption;
- FAIL_MAJOR detection;
- creation of a corrective Jules mission;
- corrective result;
- reinspection;
- PASS adoption;
- continuation to later tasks;
- SEMI_AUTO <-> AUTO ownership handover;
- fresh-state reconstruction from durable GitHub records.

The existing engine therefore already has much of the inner multi-round loop.

The major remaining gap is reliable unattended continuation across controller/session lifetimes.

## 4. Loop 139 lesson

Loop 139 exposed an autonomy defect:

1. the first independent inspection could not obtain test evidence;
2. it durably stored UNKNOWN / INVESTIGATE for the candidate HEAD;
3. the inspection path was effectively one record per command + HEAD;
4. later evidence could not produce a legitimate second inspection for the same HEAD;
5. the campaign became stuck even though the candidate itself was not proven bad.

Later read-only Linux comparison on the exact candidate and baseline ran 933 tests on each:
- candidate: failures 0, errors 0, skipped 1;
- baseline: failures 0, errors 0, skipped 1.

PR #322 changes only one small documentation file.
This supports "candidate likely fine" but does not rewrite the old durable inspection into PASS.

Attempts to modify the inspection validator / add a reinspection mechanism were blocked by Claude Code's safety classifier.
Do not bypass the classifier or disguise the same rejected edit.

The architectural lesson is broader:

> evidence-acquisition failure must be recoverable;
> UNKNOWN must be typed;
> append-only safety must allow a legitimate later inspection attempt without deleting history.

A future implementation should solve this cleanly, not by overwriting the old UNKNOWN.

## 5. Routine wake status and correction

The merged Routine V1 design proved that a non-draft GitHub PR can wake a fresh Claude Routine session.

However the current Routine document is intentionally only a component design.
It must not become the final architecture.

Important correction:

- Routine itself should be an alarm clock.
- Campaign authority lives in durable campaign/owner records.
- A woken controller should restore authority and state.
- If authorized, it should continue review -> repair/corrective -> adoption -> next task/dispatch.
- "wake -> read -> report -> human" is not loop completion.

Also note that the existing `poll_results()` in `claude_jules_live.py` is mutating:
it can record normalized result events.
Any future read-only `peek` can be useful for diagnostics/proofs, but the final product must not stop at read-only peek.

## 6. Autonomy changes now considered required

The next implementation must move toward these semantics:

### Campaign-scoped authority
Authorize a bounded campaign once, rather than requiring approval for each ordinary round.

### Configurable limits
Do not permanently hard-code six rounds.
Support configurable:
- max_rounds;
- max_corrective_rounds_per_task;
- max_transient_retries;
- max_consecutive_failures;
- max_concurrent_agents;
- task_timeout;
- campaign_timeout / timeout policy.

Initial concurrency should stay 1.

### Retry separation
Keep no-blind-resend for ambiguous side effects.
Allow bounded retries for reads/tests/evidence/wake/status.
Treat corrective work as a new task, not a replay.

### UNKNOWN classification
Use:
- TRANSIENT_UNKNOWN;
- RECOVERABLE_UNKNOWN;
- TASK_BLOCKED;
- HARD_UNKNOWN.

The word UNKNOWN alone must not terminate a campaign.

### Stale state recovery
Changed HEAD normally triggers fresh readback and replan.
Only corrupted/ambiguous lineage with no trustworthy canonical state is campaign-hard.

### Blocker isolation
A task that reaches its corrective limit becomes BLOCKED.
Continue independent READY work.

### Deferred decisions
If a reversible conservative default exists, record the decision and continue.
Do not return to the human for every reversible choice.

### Timeout recovery
Timeout triggers observation/recovery first.
It is not automatically terminal.

### Safe automatic owner recovery
A normal expired controller lease should be reclaimable by a fresh authorized controller when the ownership chain proves it safe.

## 7. Next safe implementation priorities

Do not implement everything in one risky rewrite.
Prefer incremental, testable changes that preserve the existing live-proven engine.

Suggested order:

1. Add a campaign policy/config layer around the existing controller.
   - Keep current default behavior compatible where practical.
   - Make round/retry/corrective/timeout limits configurable.
   - Do not add parallel agents yet.

2. Add typed outcome/recovery semantics.
   - TRANSIENT_UNKNOWN / RECOVERABLE_UNKNOWN / TASK_BLOCKED / HARD_UNKNOWN.
   - Preserve existing raw evidence/verdicts for compatibility.

3. Add campaign-level task isolation / dependency awareness.
   - One blocked task should not kill independent tasks.
   - Persist blocked/deferred state.

4. Add bounded recovery paths.
   - read retry;
   - test/evidence retry;
   - stale HEAD replan;
   - timeout reconcile;
   - safe owner reclaim.

5. Connect wake to resume.
   - Routine/event wakes a fresh controller.
   - Controller reconstructs durable campaign state.
   - It continues the next authorized action rather than only reporting.

6. Fix same-HEAD evidence reinspection with an append-only design that does not weaken legacy validators.
   - If the classifier blocks a particular implementation, redesign rather than bypass.
   - Preserve the original UNKNOWN.

7. Build STATIC/mock E2E covering:
   - multiple successful tasks;
   - one failed task -> corrective -> PASS;
   - transient test/evidence failure -> recovery;
   - stale HEAD -> replan;
   - controller session restart between rounds;
   - duplicate wake -> NO-OP;
   - blocked task -> independent task continues;
   - safe campaign completion.

8. Only after static proofs are solid, prepare a LIVE multi-round proof.
   - Minimum completion proof target: 3 consecutive autonomous rounds with no intermediate human "continue".
   - The proof count is not the permanent runtime max.
   - Any external live model/provider execution still follows current explicit authorization boundary.

## 8. What not to do

Do not:

- merge PR #322 merely because read-only tests look good;
- rewrite/delete the old UNKNOWN inspection;
- merge PR #220 without explicit approval;
- write directly to main;
- force push;
- make Phase 0's historical retry=0 a universal campaign retry policy;
- hard-code UNKNOWN -> campaign STOP;
- hard-code stale HEAD -> campaign STOP;
- hard-code one blocked task -> campaign STOP;
- hard-code six rounds as the architecture;
- call a one-shot Routine wake proof "autonomous loop complete";
- optimize the loop into a read-only status reporter.

## 9. Current docs-only design branch

This handover is being recorded on:

`docs/autonomous-loop-north-star-v2`

The branch is documentation-only at creation time.
It should remain safe to review independently from runtime code changes.

Before implementing anything from it, fresh-read main, active PRs, owner state, data branch, and current code.

## 10. Completion sentence

The target product is:

> The user starts a bounded development campaign once, can go to sleep or work,
> and the system safely executes, verifies, repairs, resumes across sessions, and advances through multiple tasks
> until completion or a true human boundary, then returns one consolidated report.
