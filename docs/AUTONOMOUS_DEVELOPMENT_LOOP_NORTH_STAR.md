# Autonomous Development Loop North Star

Status: design authority for the autonomous-loop line on PR #320 and successors.

> **Safety protects continuation. Safety is not the goal of stopping.**

This document defines what counts as the finished autonomous loop. It is not a
Phase 0 runtime rule set and it must not be reduced to a one-command proof.

## 1. Purpose

The autonomous loop exists to reduce human relay work while using already-paid
subscription capacity productively during unattended periods such as sleep or
work.

The target experience is:

1. the human authorizes a bounded campaign once;
2. the controller restores current durable state;
3. it selects the next safe task;
4. an agent works;
5. results are verified;
6. failures are repaired or converted into corrective work when safe;
7. success advances to the next task;
8. a sleeping/dead controller session can be replaced and resume from durable
   state;
9. the campaign stops only at a true human boundary, confirmed quota
   exhaustion, completion, or a configured campaign limit.

A successful single dispatch, single wake, single turn, or single round is only
a component proof.

## 2. Relationship to Phase 0 and upstream Symphony

Phase 0 contributes safety components such as evidence, target binding,
duplicate suppression, durable state and readback. The autonomous loop has a
different optimization target: unattended continuation and throughput.

Official OpenAI Symphony is the functional reference for long-running polling,
workspace lifecycle, multi-turn continuation, reconciliation, retries and
multi-work-item operation.

The Phase 0 / "Chinponey" implementation MUST NOT permanently hard-code away
capabilities that may later be needed to approach upstream Symphony. A
restriction may be conservative by default, but it should be represented as
policy/config/profile whenever practical so the valve can be opened later
without replacing the architecture.

It is acceptable to keep two tracks:

- **Upstream Symphony track:** minimally modified official/reference behavior,
  used as a compatibility and capability baseline.
- **New Chinponey track:** hardened integration that reuses project-specific
  durable guards and evidence.

The two tracks may coexist. They do not need to be forced into one code path if
that would slow progress or weaken either design.

## 3. Target runtime flow

```text
campaign authorization
  -> controller wake / poll
  -> durable-state restore
  -> next bounded task
  -> workspace preparation
  -> agent execution
  -> test / evidence / review
  -> PASS: adopt safely and select next task
     or
     repair / corrective task
     or
     transient recovery
  -> durable checkpoint
  -> continue
```

Normal completion of one task MUST lead to the next safe task without a human
"continue" message.

Wake mechanisms are starters, not reporters. A wake should restore campaign
authority from durable state and continue the authorized workflow.

## 4. Continuation policy

The default question after every event is:

> **Is there a safe next action inside the campaign?**

If yes, continue.

Examples of safe continuation:

- fresh readback;
- test rerun;
- evidence reacquisition;
- transient network/read retry;
- safe local repair;
- corrective agent mission;
- stale-target replan after reading the new target;
- next-task selection;
- non-default branch commit/push within campaign scope;
- controller/session replacement and resume;
- independent work while one subtask is blocked.

A blocked subtask does not automatically block the campaign.

## 5. Retry semantics

"Do not resend an ambiguous side effect" and "do not try to solve the problem
again" are different rules.

### 5.1 Ambiguous side-effect retry

Blind resend is forbidden when the first operation may already have succeeded,
for example:

- GitHub create/update outcome unknown;
- provider dispatch/POST outcome unknown;
- adoption mutation outcome unknown.

Required behavior:

```text
ambiguous write
  -> readback
  -> confirmed success: continue
  -> confirmed absence and a new safe action is valid: proceed as a new action
  -> unverifiable duplicate risk: isolate that subtask
```

Do not automatically stop unrelated safe work.

### 5.2 Transient diagnostic retry

Bounded retry is allowed for operations without duplicate side-effect risk, for
example:

- GitHub/read-only fetch;
- tests;
- evidence acquisition;
- status checks;
- transient filesystem setup;
- temporary network reads;
- wake/read acquisition.

### 5.3 Corrective work

A failed agent result may create a **new corrective mission**. This is not a
blind resend of the original dispatch.

## 6. UNKNOWN classification

UNKNOWN is information about uncertainty, not an unconditional campaign-stop
instruction.

Suggested classes:

- **TRANSIENT_UNKNOWN:** retry/re-read is likely to resolve it.
- **RECOVERABLE_UNKNOWN:** an alternate proof/readback/replan path exists.
- **HARD_UNKNOWN:** no safe continuation can be established.

A target HEAD change is NOT automatically HARD_UNKNOWN. If another actor safely
advanced the target:

```text
HEAD changed
  -> read latest state
  -> inspect intervening changes
  -> confirm campaign objective still applies
  -> replan against the new head
  -> continue
```

Only loss of authoritative lineage/identity, unverifiable dangerous side
effects, broken authorization, or an equivalent condition should force a
campaign-wide hard stop.

## 7. Four durable safety components to preserve

### 7.1 Duplicate execution prevention

Stable task/logical identities and claims prevent the same logical work from
being executed twice accidentally. Duplicate events become NO-OP.

A failed task may still produce a distinct corrective task.

### 7.2 Stale target protection

Bind work to the target revision observed when the task is prepared. Before a
mutation/adoption, verify the current target again.

A stale target triggers readback and replan when safe. It is not inherently a
campaign stop.

### 7.3 Durable execution ledger

Important campaign state must survive Chat, Work, agent, browser and process
lifetimes.

The durable control plane should be able to reconstruct at least:

- campaign identity and authorization;
- round/generation/correlation;
- current task;
- claim/owner state;
- dispatch result;
- verification/adoption state;
- retry/corrective counters;
- terminal/blocked state;
- next safe action/checkpoint.

### 7.4 Ambiguous-write readback

When a write outcome is uncertain, do not repeat the same side effect merely
because the response was lost. Read the authoritative remote state first.

## 8. Configurable policy, not permanent hard-coded throttles

The architecture should support configuration such as:

```text
max_rounds
max_turns_per_task
max_model_starts_per_task
max_corrective_rounds_per_task
max_transient_retries
max_consecutive_failures
max_concurrent_agents
idle_observation_interval
task_timeout
campaign_timeout
```

Conservative defaults are acceptable during proof stages.

The schema/design may support a future unlimited/null campaign limit. The
runtime does not need to enable every value on day one.

Current proof-only limits such as one turn, one start, one path or one commit
must remain a **strict proof profile**, not become permanent architectural
limits.

## 9. Idle, timeout and lease behavior

Idle timeout is primarily a re-observation trigger:

```text
idle threshold
  -> fresh provider/GitHub status
  -> still running: wait/check later
  -> session disappeared: recovery/reclaim path
  -> true blocker: isolate/stop as appropriate
```

An expired controller lease should normally permit safe reclaim by a fresh
controller when generation/ownership fences verify it.

## 10. Subscription-only cost boundary

The unattended loop is intended to consume already-paid ChatGPT/Codex
subscription allowance, not metered API spend.

Policy target:

- no automatic API-key fallback;
- no automatic paid-credit/overage enablement or purchase;
- no automatic fallback to a metered third-party provider;
- do not infer quota exhaustion merely because usage balance is unreadable;
- **stop new model work when quota exhaustion is explicitly confirmed**;
- unknown remaining allowance alone is not a stop condition.

Before live unattended operation, authentication and quota observations must be
verified sufficiently to enforce this policy. Billing, credit, API key,
permission or secret changes remain human-controlled unless a future explicit
policy says otherwise.

## 11. Human boundary

Within campaign authorization, do not ask for approval for every round.

Human intervention is normally reserved for:

- PR merge;
- direct default-branch mutation;
- force push/history rewrite/destructive deletion;
- billing/credits/overage changes;
- credential/permission/secret changes;
- irreversible actions;
- campaign-scope expansion;
- architecture/product choices with no conservative reversible default;
- genuine HARD_UNKNOWN affecting campaign correctness;
- configured campaign/failure limits;
- campaign completion.

A decision that blocks only one task should be deferred when independent safe
work remains.

## 12. Current #320 interpretation

PR #320 began as a strict one-dispatch proof. Its one-turn, one-start,
retry-zero, proof-file and exact-commit constraints are evidence fixtures, not
the North Star.

The first real LIVE attempt proved useful pieces:

- controller reached a real Codex app-server run;
- exactly one model start occurred;
- Codex created the requested proof content;
- durable terminal UNKNOWN was written;
- a second poll did not redispatch.

It did not produce the required commit/push, so it is not a closed-loop PASS.
The consumed command must not be replayed.

This failure must not be used to conclude that the autonomous architecture
should remain one-turn or one-job.

## 13. Near-term architecture direction

Before more live proof, evolve the design so that:

1. strict proof limits are isolated into an explicit proof profile;
2. autonomous runtime policy is configurable;
3. model-start budgets are per task/campaign policy, not runner-lifetime traps;
4. multi-turn/continuation can be enabled without rewriting the controller;
5. stale HEAD becomes a replan path when safe;
6. UNKNOWN classification and blocker isolation exist;
7. subscription-only policy has an enforceable gate;
8. upstream Symphony behavior remains reachable either through progressive
   feature gates or a separate upstream-compatible track.

## 14. Completion standard

Do not call the autonomous loop complete because one component works.

Completion evidence should demonstrate, at minimum:

- zero human intervention across multiple rounds;
- success automatically advances;
- failure can produce safe recovery/corrective work;
- controller/session replacement can resume;
- durable duplicate suppression works;
- stale target can be replanned when safe;
- ambiguous writes do not blind-resend;
- independent work continues around isolated blockers;
- configured stopping conditions are honored;
- no unauthorized metered billing path is used.

The long-term target is simple:

> **Human starts a campaign once. The system keeps doing safe useful work until
> completion, a real human boundary, confirmed subscription exhaustion, or a
> configured campaign limit, then reports once.**
