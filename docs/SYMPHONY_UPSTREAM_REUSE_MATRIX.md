# Symphony upstream reuse matrix

Pinned upstream reference:

- repository: \`openai/symphony\`
- commit: \`be10a1b79df723d6d7612b5651c8522704dafb2e\`
- checked: 2026-10-07
- machine-readable mirror:
  \`automation/command_bus/symphony_upstream_reference.json\`

This pin is a comparison baseline, not a LIVE execution authorization.

## Principle

Track A is the official/minimally modified Symphony baseline. Track B (New
Chinponey hardened integration) adds the Phase-0 durable correctness/evidence
requirements that are intentionally stronger than upstream's current
tracker/filesystem-driven restart model.

Do not reimplement mature upstream behavior merely to keep Track B self
contained. Prefer an adapter boundary.

| Capability | Track A / upstream reference | Track B responsibility | Decision |
| --- | --- | --- | --- |
| Workflow/config loading | \`SPEC.md\`, \`workflow.ex\`, \`config.ex\` | extra policy valves only | reuse upstream semantics |
| Poll/reconciliation loop | \`orchestrator.ex\` | durable campaign overlay | reuse scheduler shape |
| Workspace lifecycle | \`workspace.ex\` | bind task/head/evidence identity | reuse, do not rewrite |
| Multi-turn Codex session | \`agent_runner.ex\` | per-task durable attempt binding | reuse same-thread turn loop |
| Continuation retry | 1 second | durable state before next task | align |
| Failure retry | 10 second exponential, capped at 300 seconds | classify retry-safe operations first | align timing, stricter side-effect gate |
| Global concurrency | default 10 | configurable valve; hardened default may remain 1 during proof | openable |
| Turns per worker | default 20 | \`max_turns_per_task\` | align/openable |
| Stall detection | default 300 seconds | durable recovery classification | reuse detector, add durable evidence |
| Restart | tracker/filesystem re-poll; live scheduler state not restored | hash-linked GitHub campaign restore | Track B intentionally stronger |
| Ambiguous writes | workflow/provider-specific | mandatory remote readback, no blind resend | Track B |
| Stale Git target | implementation/workflow-specific | fresh readback + replan/isolate | Track B |
| Subscription-only cost gate | outside core Symphony spec | no metered/API/provider fallback | Track B |
| Merge/billing/permission/secret boundary | workflow/environment policy | explicit human boundary | Track B |

Current STATIC adapter seam: an upstream issue update requests read-only
reconciliation without needing a complete worker identity. New-worker route
compatibility is classified once using sanitized Codex account evidence and
structural paid-route configuration. An attempt result is checked against fresh
canonical HEAD, task validity and mutation class immediately before campaign
adoption and again on durable terminal restore. None of these checks runs inside
upstream's same-session turn, continuation or retry loop. See
`SYMPHONY_ADOPTION_BRIDGE_STATIC_CHECKPOINT.md`.

## Integration direction

1. Keep the existing strict one-turn Codex adapter as a regression proof.
2. Keep the Track-B durable campaign kernel/store/controller independent of
   provider transport.
3. Add a separate production adapter that maps one durable campaign task attempt
   to an upstream Symphony worker/session identity.
4. Reuse upstream workspace, multi-turn, continuation, backoff, reconciliation,
   stall detection and app-server protocol behavior rather than porting them
   line-for-line into the Track-B kernel.
5. Persist task attempt identity, target HEAD, thread/turn evidence and terminal
   result around that adapter so a fresh controller can reconcile before any
   redispatch.
6. Keep the current LIVE gate closed until STATIC restart/fault/reconciliation
   tests for that adapter are green.

## Important upstream difference

The pinned upstream spec explicitly describes restart recovery as re-polling the
tracker and reusing preserved workspaces; it does not restore retry timers,
running sessions or exact in-memory scheduler state. Track B's durable GitHub
campaign checkpoints are therefore an intentional extension, not a claim about
upstream behavior.
