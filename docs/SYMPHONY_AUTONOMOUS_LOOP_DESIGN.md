# Symphony / New Chinponey Autonomous Loop Design

Status: line-specific architecture for the Symphony-derived autonomous loop.
Read together with `AUTONOMOUS_DEVELOPMENT_LOOP_NORTH_STAR.md`.

## 1. Product goal

This line is not trying to make the safest possible one-shot executor.

It is trying to make an unattended development loop that can use already-paid
subscription capacity while the user is asleep or away, continue across
controller/session lifetimes, repair recoverable failures, and advance through
multiple tasks without repeated human "continue" messages.

Safety mechanisms are retained only to protect correctness, cost boundaries and
continuation.

## 2. Upstream-first strategy

Official OpenAI Symphony is the capability baseline for:

- long-running polling and reconciliation;
- per-work-item workspaces;
- multi-turn Codex continuation;
- multiple work items;
- transient retry/backoff;
- stalled-worker observation/recovery;
- tracker-driven scheduling;
- restart/reconciliation behavior.

Do not reimplement mature upstream behavior merely to preserve the historical
shape of PR #320.

Two implementation tracks are explicitly allowed:

### Track A: upstream Symphony baseline

Keep a minimally modified upstream/reference implementation that proves what the
official architecture can already do in this repository.

### Track B: New Chinponey hardened integration

Retain project-specific durable safety and evidence where it adds value.

The tracks may coexist until measured evidence justifies convergence.

## 3. Shared North Star, line-specific overrides

The shared autonomous-loop North Star from the Claude/Jules line is the common
completion philosophy.

For this Symphony line, two conservative suggestions are NOT permanent
requirements:

1. a finite `max_rounds` default is not an architectural requirement;
2. `max_concurrent_agents = 1` is not an architectural requirement.

This line may start with low values for proof convenience, but the configuration
must permit opening those valves without rewriting the controller. Since
upstream Symphony already has multi-turn/concurrency machinery, the design may
adopt it when evidence supports doing so.

The user's cost boundary, not an arbitrary round number, may become the practical
overnight stopping boundary.

## 4. Required safety additions

### Duplicate execution prevention

Use stable logical identities and durable claims/terminal results where needed
to avoid accidentally executing the same logical side effect twice.

Duplicate event delivery should be a NO-OP.

### Stale target protection with replan

Bind mutations to the target revision they were prepared against.

A changed HEAD is normally:

```text
fresh read
-> inspect intervening change
-> task still valid?
   yes: replan on new canonical HEAD
   no: mark old task stale and choose/create a new task
-> continue
```

Only loss of trustworthy canonical lineage should become campaign-hard.

### Durable execution history

Session memory is a cache. Durable state should allow a fresh controller to
reconstruct campaign/task/attempt/ownership/result/evidence/counter state.

### Ambiguous-write readback

If a side-effecting write may have succeeded, do not blindly resend it.
Read the authoritative remote state first and isolate only the ambiguous scope
when unresolved.

## 5. Retry model

Do not apply global `retry=0`.

- ambiguous duplicate-risk write: blind resend = 0;
- read/status/test/evidence/network-read: bounded retry;
- failed artifact/task: new corrective task;
- stalled/expired controller: reconcile/reclaim when safe;
- stale HEAD: replan when safe;
- blocked task: isolate, then continue independent ready tasks.

## 6. UNKNOWN model

UNKNOWN must carry a cause class.

- TRANSIENT_UNKNOWN: bounded retry/re-read;
- RECOVERABLE_UNKNOWN: alternate proof/replan path;
- TASK_BLOCKED: isolate task, continue independent work;
- HARD_UNKNOWN: no safe continuation/authority can be established.

HARD_UNKNOWN is scoped. Stop the entire campaign only if it affects campaign
authority/correctness or no independent safe work remains.

## 7. Runtime policy valves

The architecture should expose policy/config rather than compile permanent
limits:

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

Proof profiles may pin these to strict values.
Autonomous profiles may open them.

A future unbounded/null round setting is allowed by design.

## 8. Subscription-only cost boundary

Unattended work should use already-paid subscription capacity only.

Do not automatically:

- fall back to metered API billing;
- create/use an API key as fallback;
- buy credits or enable overages/auto-recharge;
- switch to another metered provider.

Stop starting new model work when quota exhaustion is explicitly confirmed.

If exact remaining allowance cannot be read, that absence alone is not
confirmed exhaustion and must not become a safety trap.

The exact authentication/quota enforcement mechanism must be verified before
unattended LIVE operation.

## 9. Wake / restart semantics

A wake is not a notification endpoint.

```text
wake / process restart
-> fresh durable restore
-> authority/owner/generation validation
-> resume current safe action
-> review / repair / corrective / adopt / next task
-> continue
```

Controller/session death is a recovery event, not campaign completion.

## 10. Current PR #320 code

The current code is a strict proof profile:

- one model start;
- one turn;
- retry zero;
- one exact proof path/content;
- one exact commit/push expectation;
- terminal UNKNOWN when the proof contract is not satisfied.

Keep it as regression evidence.

Do not generalize these constraints into the autonomous runtime.

The first real proof reached Codex, created the proof file, persisted terminal
UNKNOWN and correctly suppressed redispatch. It failed the commit/push
postcondition. That is a useful component proof, not a reason to keep one-turn
architecture.

## 11. Implementation migration shape

Prefer incremental changes:

1. introduce explicit runtime profiles/policy objects;
2. keep the strict proof profile behavior unchanged;
3. make runner budgets task/policy scoped instead of runner-lifetime hard stops;
4. add typed UNKNOWN/recovery outcomes;
5. add blocker isolation and stale-target replan;
6. add durable session/campaign recovery;
7. reuse upstream Symphony multi-turn/workspace/continuation behavior where
   practical;
8. add subscription-only gate;
9. add static multi-round/restart/fault tests;
10. then run a bounded LIVE multi-round proof only when explicitly authorized.

## 12. Completion definition

One dispatch or one round is not completion.

The line is a real autonomous loop when it can, without intermediate human
"continue":

- process multiple tasks/rounds;
- move success to the next task;
- repair/retry recoverable failure;
- resume in a fresh controller/session;
- suppress duplicate effects;
- replan stale targets;
- isolate blocked work;
- respect the subscription-only boundary;
- stop at a configured/real human boundary and report once.

The intended long-term capability is allowed to approach official Symphony
rather than remaining a permanently reduced Phase 0 proof executor.


## 13. STATIC implementation checkpoint: policy + durable campaign kernel

PR #320 now carries a Track-B pure-state foundation that does not start a model
or write GitHub by itself:

- `symphony_autonomous_policy.py` separates strict proof limits from
  configurable hardened/upstream-reference profiles;
- UNKNOWN is typed as transient, recoverable, task-blocked, or hard and maps to
  retry/replan/isolate/stop actions by scope;
- stale HEAD is modeled as replan first when canonical lineage is trustworthy;
- confirmed subscription exhaustion stops new model work, while unreadable quota
  remains UNKNOWN and is not treated as exhaustion;
- `symphony_autonomous_runtime.py` defines serializable campaign/task state,
  duplicate-result suppression, dependency-aware next-task selection,
  corrective-task identity, blocker isolation, stale replan, and guarded
  restart reclaim;
- static tests prove three consecutive rounds, fail->corrective->continue,
  transient retry exhaustion with independent-work continuation, restart restore,
  duplicate NO-OP, stale replan/isolation, scoped HARD_UNKNOWN, and quota gating.

This is deliberately a hardened coordination kernel, not a reimplementation of
upstream Symphony workspace/app-server orchestration. Track A should still reuse
upstream polling/workspace/multi-turn/retry behavior where practical. The next
integration step is to wire this policy/state layer to the existing controller
and then move the Codex proof runner's one-start counter from runner lifetime to
task/profile scope without weakening the consumed-command fence.


## 14. Strict Codex proof budget is now task-scoped

The Codex proof adapter still permits exactly one model-start attempt per strict
proof task. The counter is no longer a runner-lifetime fuse: a distinct durable
task identity gets its own proof budget, while the same task cannot be submitted
twice through one runner instance.

This changes no LIVE authorization and does not weaken durable replay
suppression. The durable claim/result ledger remains the cross-process fence;
the in-process counter is only a task-level proof budget. Autonomous profiles
can therefore grow to multiple tasks without requiring a fresh runner merely to
reset an unrelated proof counter.
