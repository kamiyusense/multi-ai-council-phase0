# AGENTS.md — Phase 0 repository map

This file is intentionally short. It is a map, not the full specification.
Do not read every repository document by default.

## Start here

1. Read `HANDOVER_CURRENT.md`.
2. Read `docs/DEVELOPMENT_EXECUTION_ROUTER.md`.
3. Then read only the task-specific files named in the current prompt.

Fresh checked-out Git/GitHub state is authoritative. A SHA, PR number, branch,
session, or Loop number in an old checkpoint is historical unless the current
task explicitly binds it and fresh readback agrees.

## Development posture

- Reuse existing repository components and upstream/official primitives before
  creating a new abstraction.
- Implement the smallest bounded slice requested by the task.
- Do not add opportunistic safety layers, frameworks, databases, protocols,
  refactors, or tests merely because they might be useful later.
- Do not weaken an existing dangerous-operation gate just to make a test pass.
- Presentation/observability code must not become runtime ownership authority.
- If a minor mismatch is resolvable from an existing validated public contract,
  prefer the smallest reversible alignment instead of inventing a new schema.
- Stop and report only when resolving a mismatch would cross the task allowlist,
  materially change architecture, or require a prohibited/live boundary.

## Git / publication

- Work only from the exact task snapshot and isolated work branch.
- Respect the task allowlist exactly.
- Never mutate the canonical target branch directly.
- No Merge, direct default-branch write, force push, rebase, branch deletion,
  destructive cleanup, settings/permission changes, billing/credits changes,
  secret/API-key handling, or unrequested external service writes.
- retry=0; fallback=disabled. Never blindly repeat an ambiguous external write.

## Live boundaries

Do not start an additional live provider/model/API/OIDC proof, runtime takeover,
Issue migration, or production durable publication unless the task explicitly
authorizes that exact action.

## Validation

Use the exact validation commands in the task. Add focused tests for the direct
happy path and the realistic conflict/recovery cases required by the task, then
run the existing regression suite. Do not expand scope into exhaustive imagined
failure testing unless a real defect or explicit requirement calls for it.

## Completion

Produce concrete deliverables, not acknowledgements:
- changed paths;
- exact commit/PR result;
- focused/full test results;
- any real blocker or remaining NOT_WIRED boundary.

If the task can safely finish inside its stated bounds, finish it and publish the
normal isolated PR without asking for confirmation.
