# Autonomous Development Loop — North Star v2

Status: TARGET ARCHITECTURE / COMPLETION VISION. This document is not an implementation recipe.
It exists to prevent future controllers from shrinking the goal into a one-turn, read-only, or human-gated half-loop.

## 0. Authority of this document

For the autonomous-development-loop work, this document is the top-level completion target.
Older Phase 0 safety documents, one-shot proofs, Routine wake notes, and retry=0 records remain useful components/evidence,
but they MUST NOT be interpreted as requiring the whole autonomous campaign to stop after one task, one UNKNOWN,
one expired session, one transient failure, or one wake.

The loop is being developed inside the Phase 0 repository because Phase 0 components are useful here.
The loop itself is not a Phase 0 runtime component and does not inherit every Phase 0 operational restriction as a global policy.

Core principle:

> Safety protects continuation. Safety is not the goal of stopping.

If a safety invariant blocks one action, isolate that action and continue every independent safe action that remains.

## 1. Purpose

The system exists to provide a useful unattended development loop that can run while the user sleeps or is away.

Primary goals:

- continue for long periods without repeated human "continue" messages;
- survive Chat / Work / Claude / coding-agent session death;
- use durable state instead of session memory;
- consume already-paid subscription allowance productively;
- recover from transient failures;
- correct failed agent work and continue;
- complete multiple tasks / rounds in one campaign;
- stop only at a real human boundary, configured campaign limit, exhausted subscription allowance,
  or a condition from which no safe recovery path remains.

The target is not "one safe turn".
The target is "safe multi-round autonomous development".

## 2. Separation from Phase 0

Phase 0 emphasizes:

- correctness;
- evidence;
- fail-closed validation;
- conservative boundaries.

The Autonomous Development Loop emphasizes:

- unattended execution;
- continuation;
- recovery;
- productivity;
- bounded autonomy.

It reuses Phase 0 components such as exact HEAD/tree checks, durable records, duplicate guards, lineage checks,
create-only ledgers, safe adoption, and ownership fencing.

Those mechanisms remain strong.
Their failure result, however, is not automatically "terminate the whole campaign".

## 3. Campaign model

The top-level unit is a campaign.

A campaign contains multiple tasks and rounds:

Campaign
  -> task
     -> initial attempt
     -> inspection
     -> optional repair / corrective attempts
     -> terminal task result
  -> next task
  -> ...
  -> campaign terminal result

Human authorization should normally happen at the campaign boundary, not at every round.

A campaign authorization may bind:

- repository;
- target branch / allowed branches;
- allowed lane(s);
- allowed action classes;
- max_rounds;
- max_corrective_rounds_per_task;
- max_transient_retries;
- max_consecutive_failures;
- max_concurrent_agents;
- idle_check_interval / idle_timeout policy;
- task_timeout;
- overall_campaign_timeout;
- dispatch budget if applicable;
- subscription-only cost boundary.

Within that authorization, routine safe work continues without asking the user every round.

## 4. Target runtime loop

Human starts campaign once
  -> controller restores durable state
  -> choose next safe task
  -> prepare workspace
  -> dispatch coding agent
  -> agent works
  -> result event
  -> wake a controller session
  -> restore campaign from durable state
  -> independent inspection
  -> classify result
       PASS
         -> safe adoption
         -> next task
       SMALL_REPAIR
         -> controller repair
         -> verify
         -> next task
       CORRECTIVE
         -> create a new corrective task
         -> dispatch agent
         -> wait for next result event
       TRANSIENT_UNKNOWN
         -> bounded read/test/evidence retry
         -> reinspect
       RECOVERABLE_UNKNOWN
         -> alternate safe evidence / replanning path
       TASK_BLOCKED
         -> isolate task
         -> continue independent tasks
       HUMAN_REQUIRED
         -> stop only the affected campaign boundary
  -> repeat until campaign completion / configured limit / true blocker

A successful task MUST naturally lead to next-task selection.
A controller session ending MUST NOT mean the campaign ended.

## 5. Wake semantics

Wake infrastructure is an alarm clock, not the controller and not merely a notification system.

A wake event should start a fresh controller session.
The controller then:

1. reads fresh GitHub / durable campaign state;
2. validates campaign identity and authority;
3. validates current owner/generation where applicable;
4. restores the current task / pending result;
5. performs the next authorized safe action;
6. continues through review / repair / corrective / adoption / next dispatch when allowed.

A design that ends with:

wake -> read -> report -> human

is only a component proof, not the completed autonomous loop.

The target is:

wake -> restore -> act -> continue campaign.

## 6. Session independence

Correctness must not depend on:

- one Claude session;
- one Chat thread;
- one Work session;
- one browser session;
- one local process;
- one disposable provider task.

Durable state must be sufficient for a fresh controller to reconstruct:

- campaign_id;
- campaign authorization;
- current round;
- current task;
- task dependency status;
- current / previous attempts;
- outstanding dispatch;
- result identity;
- inspection status;
- retry counters;
- corrective counters;
- adopted target state;
- owner/generation;
- blocked tasks;
- deferred decisions;
- next_safe_action;
- campaign terminal status.

next_safe_action is advisory, not blindly trusted.
Every resumed controller revalidates fresh state before executing it.

## 7. Configurable limits

Do not hard-code "6 rounds" as the architecture.

The design must support configuration such as:

- max_rounds;
- max_corrective_rounds_per_task;
- max_transient_retries;
- max_consecutive_failures;
- max_concurrent_agents;
- task_timeout;
- campaign_timeout;
- idle_check_interval;
- dispatch / provider budget.

Examples:

- short proof: max_rounds = 3;
- normal campaign: max_rounds = 6;
- overnight campaign: max_rounds = 20 or 30.

The schema may allow "unbounded" in the future, but early production defaults should remain finite.
Increasing the limit must not require rewriting controller code.

max_concurrent_agents should initially remain 1 unless parallel ownership / target isolation is proven.
The schema should leave room for safe future expansion.

## 8. Retry semantics

Never use one global retry=0 rule for all operations.

### 8.1 Ambiguous external / mutating write

Examples:

- provider dispatch POST;
- GitHub create/update where the response is ambiguous;
- adoption ref write;
- external side-effecting request.

Do not blindly send the same logical write again.

Flow:

write
 -> ambiguous response
 -> readback
 -> confirmed success: continue
 -> confirmed absent and issuing a distinct safe action is valid: replan
 -> unverifiable with duplicate risk: isolate that subtask

This is duplicate prevention, not a ban on recovery.

### 8.2 Transient read / verification retry

Bounded retries are allowed for:

- GitHub reads;
- status reads;
- test invocation;
- evidence retrieval;
- network reads;
- temporary filesystem operations;
- wake acquisition;
- verification reads;
- other non-destructive transient failures.

Retry count/backoff are campaign configuration.

### 8.3 Corrective attempt

A failed artifact is not retried by replaying the same ambiguous write.
Create a new corrective task with a new identity.

Corrective work is a normal autonomous continuation path up to its configured limit.

## 9. UNKNOWN taxonomy

The string UNKNOWN alone is never a sufficient campaign-stop reason.

Classify the cause.

### TRANSIENT_UNKNOWN

Examples:

- test command failed to start;
- temporary GitHub read failure;
- temporary network failure;
- evidence source temporarily unavailable.

Action:
bounded retry / evidence reacquisition / reinspection.

### RECOVERABLE_UNKNOWN

Examples:

- local environment cannot run the test but an authorized cloud exact-head test can;
- cached evidence missing but fresh remote evidence can be acquired;
- stale target HEAD with an unambiguous new canonical state.

Action:
alternate safe path or replan.

### TASK_BLOCKED

One task has exhausted its safe repair/retry options, but independent tasks remain.

Action:
record blocker, isolate the task, continue the campaign with independent work.

### HARD_UNKNOWN

Reserve this for cases where correctness / authority itself cannot be established, for example:

- conflicting or corrupted durable lineage with no trustworthy source of truth;
- an ambiguous side-effecting write whose duplicate risk cannot be resolved;
- incompatible ownership records where no valid reclaim / generation path exists;
- authorization identity cannot be established and no authorized work remains.

Even HARD_UNKNOWN should first isolate its scope.
Only stop the whole campaign when the unknown affects campaign authority or all remaining safe work.

## 10. Stale HEAD is a replan trigger

A changed target HEAD is not automatically HARD_UNKNOWN.

Flow:

stale HEAD detected
 -> fresh readback
 -> inspect intervening changes
 -> is the task still valid on the new canonical state?
      yes -> replan against new HEAD without destructive history rewrite
      no  -> mark the old attempt stale and create / choose a new task
 -> continue

Stop only if there is no trustworthy canonical state or safe replan path.

## 11. Failure / corrective limit handling

A task reaching its corrective limit does not automatically terminate the campaign.

Flow:

task A reaches its limit
 -> TASK_BLOCKED
 -> persist blocker / evidence
 -> identify independent ready tasks
 -> continue B/C/D when safe

Stop the entire campaign only when:

- the blocked task is a prerequisite for every remaining task;
- campaign correctness depends on its unresolved state;
- no independent safe work remains;
- or a configured campaign-level stop condition is reached.

## 12. Deferred Decisions

Do not stop for every architectural choice.

If:

- multiple options are reversible;
- a conservative default exists;
- choosing the default does not exceed campaign authority;
- later correction is cheap and safe;

record a Deferred Decision and continue.

Recommended durable fields:

- decision_id;
- question;
- reason;
- options;
- selected_safe_default;
- reversibility;
- affected scope;
- reconsider_by condition.

Stop for a design/product decision only when the choice materially changes user intent,
cost, permissions, irreversible architecture, or correctness and no safe default exists.

## 13. Timeout semantics

Timeout is a check trigger, not automatically a terminal state.

idle timeout:
 -> read fresh status
 -> still running: schedule / await next observation
 -> stalled: attempt bounded recovery
 -> disappeared: reconcile durable records
 -> unrecoverable: isolate / stop as appropriate

task timeout:
 -> reconcile provider / result state
 -> recover if possible
 -> classify task only after evidence

campaign timeout:
 -> checkpoint all state
 -> continue non-model safe cleanup / evidence if useful
 -> stop new model work when the configured boundary truly requires it

## 14. Blocker isolation

A blocked subtask must not hold unrelated work hostage.

Durable campaign state should distinguish:

- READY;
- RUNNING;
- WAITING;
- BLOCKED;
- DEFERRED;
- COMPLETE.

The planner selects READY tasks whose dependencies are satisfied.

This allows campaign progress even when one branch of work is blocked.

## 15. Durable control plane

Important campaign state must be reconstructible from GitHub or another approved durable control plane.

At minimum preserve:

- campaign request / authorization;
- task definitions;
- claims / ownership;
- attempts / dispatches;
- result events;
- inspections;
- evidence;
- repairs / corrective relationships;
- adoption receipts;
- blocked task records;
- deferred decisions;
- current campaign state;
- round / generation / correlation;
- next_safe_action;
- terminal receipts.

Session memory is a cache, not the source of truth.

## 16. Duplicate and stale work prevention

Keep strong safety primitives:

- stable logical identities;
- create-only records where practical;
- duplicate event -> NO-OP;
- stale generation rejection;
- stale role rejection;
- exact expected target state where the action requires it;
- readback after writes;
- terminal replay prevention.

These prevent duplicate effects.
They must not prohibit new corrective tasks or safe replanning.

## 17. Ownership and recovery

Ownership fencing remains useful.

However, an expired controller lease should normally be recoverable:

controller session disappears
 -> lease expires
 -> fresh controller wakes
 -> validates no conflicting live owner
 -> safe reclaim / next generation
 -> campaign resumes

Do not require the user to manually reclaim every expired normal controller lease if campaign authorization and the ownership chain make automatic reclaim safe.

## 18. Subscription-only cost boundary

The loop should use already-paid subscription allowance where possible.

Never automatically:

- switch to usage-billed API fallback;
- create/use an API key as fallback;
- purchase credits;
- enable overages / auto-recharge;
- switch to another metered provider.

If the provider explicitly reports quota / subscription allowance exhausted,
stop starting new model work and checkpoint normally.

If exact remaining quota is not observable, lack of a percentage reading alone is not a failure.
Continue until the provider reports an actual limit or another configured boundary is reached.

## 19. Human approval boundary

Routine campaign work should continue without per-round confirmation.

Human approval remains appropriate for:

- PR Merge;
- direct default-branch write;
- force push / destructive history rewrite;
- destructive delete;
- billing / credits / overage changes;
- credentials / permissions / Secret changes under current policy;
- expanding beyond the campaign's authorized purpose/repository/targets;
- irreversible actions;
- a true product/design decision with no safe reversible default;
- campaign-level HARD_UNKNOWN;
- configured campaign completion / exhaustion.

These are boundaries, not reasons to ask after each normal task.

## 20. Completion criteria

Do NOT call the autonomous loop complete because:

- one agent dispatch worked;
- one result PR appeared;
- one Routine woke Claude;
- one review succeeded;
- one round completed;
- a wake produced a report.

Component proofs are useful but not completion proofs.

A completion proof should demonstrate, without intermediate human intervention:

- multiple distinct tasks / rounds;
- success -> adoption -> next task;
- failure -> correction -> reinspection;
- at least one fresh controller/session resume;
- duplicate event suppression;
- durable reconstruction;
- safe write/readback;
- stale-state recovery / replanning;
- blocker isolation where applicable;
- configured normal stopping behavior;
- no unapproved metered fallback.

Minimum LIVE completion proof target: at least 3 consecutive autonomous rounds after the components are statically proven.
The number is a proof target, not a permanent runtime limit.

## 21. Non-goal: safety theater

Do not optimize the system into a tool that is safe because it does almost nothing.

The following are explicitly not the target:

- "wake, read, report, stop";
- "one task completed, ask the human";
- "UNKNOWN appeared, terminate campaign";
- "one task exceeded retries, terminate unrelated tasks";
- "target HEAD moved, terminate";
- "session ended, campaign ended";
- "safe next action exists, but wait for the human anyway".

The governing rule is:

> Work possible -> continue.
> Safe recovery possible -> recover.
> Safe replan possible -> replan.
> Independent safe work remains -> continue.
> Only when safe continuation is exhausted -> stop.

