# Jules Task Prompt Specification

Status: MANDATORY for every new Jules task in this repository.
Updated: 2026-09-29

This document is the canonical prompt-writing contract for Chat/Work/other
controllers that dispatch implementation work to Jules.

It exists because green tests alone have repeatedly been insufficient. Several
Relay loops returned green suites while independent semantic review still found
contract gaps. The goal is therefore not "make Jules try harder"; the goal is
to make each task narrow, observable, bounded, and independently reviewable.

## 0. Loop ID uniqueness and parallel-lane reservation before prompt composition

For numbered Relay/Jules loops, the controller MUST NOT infer that "last loop + 1"
is available from memory. All Jules lanes share one global Loop-number namespace.

Before composing the task, fresh-read the durable command-bus state and obtain a
create-only claim at `automation/command_bus/loop_id_claims/<NNN>.json`.
A claimed number is never recycled. If the path exists, select a different
unused number. Ambiguous claim writes require readback, not retry.

New numbered dispatches MUST use claim schema version 3 and follow
`docs/JULES_PARALLEL_COLOR_LANES.md`. The canonical lane IDs are
`J-RED`, `J-BLUE`, `J-YELLOW`, and `J-GREEN`, displayed as
❤️, 💙, 💛, and 💚. Each lane is independent: using `J-GREEN` does not require
`J-BLUE` or `J-YELLOW` to exist or run.

The claim binds the numeric Loop to the command/work branch and exact target
snapshot, and carries `lane_id` plus `lane_display` as presentation/routing
metadata. Lane metadata must never substitute for `command_id`, `work_branch`,
Jules session, or exact HEAD/tree verification.

The order is mandatory:

1. fresh-read globally used Loop numbers;
2. create-only schema-v3 claim with state `CLAIMED`;
3. read back the exact claim;
4. create the exact isolated work branch from the claimed HEAD/tree;
5. append one matching Jules command;
6. read back workflow validation and the returned Jules session.

If two controllers race for the same Loop number, the loser reads back the
existing claim and selects another unused number. It must not blindly retry the
same create.

`HISTORICAL_BACKFILL` claims reserve already-used numbers for archival
uniqueness only and are never dispatch authority.

The eventual work branch and Jules command ID must match the durable claim.

## 1. Mandatory pre-dispatch rule

Before creating any new Jules task, the controller MUST:

1. fresh-read the current target branch/PR HEAD and tree;
2. read this document;
3. read the current task-specific handoff/specs;
4. search for existing implementation, helpers, fixtures, schemas, and tests
   that already encode the requested semantics;
5. decide one bounded mission;
6. bind an exact non-default work branch to the fresh target HEAD/tree;
7. define exact allowed changed paths;
8. define machine-checkable acceptance criteria and negative cases;
9. define explicit prohibited actions;
10. define the exact validation commands;
11. set retry=0, fallback=disabled, Merge=false unless a narrower current
    authorization explicitly says otherwise.

If any of these cannot be established, do not invent them. Mark the affected
part UNKNOWN or stop that subtask.

## 2. One task = one mission

A Jules task SHOULD implement or audit one coherent concept.

Good:
- add one deterministic validation layer;
- add one schema + tests for that layer;
- add one bounded integration audit;
- prepare one decision-support artifact.

Bad:
- "finish the Relay";
- "fix anything you find";
- "refactor the project and add tests";
- mixing unrelated features, cleanup, docs, workflow changes, and live proof.

If the job requires unrelated concepts, split them into later tasks.

## 3. Required prompt order

Every task prompt MUST use this order so the executor can find the contract
without interpreting prose structure:

1. **Task / size class**
2. **Goal**
3. **Read first**
4. **Allowed changed paths only**
5. **Hard scope / Do Not Touch**
6. **Existing implementation to reuse**
7. **Required semantics**
8. **Negative / tamper / failure cases**
9. **Acceptance criteria**
10. **Exact validation commands**
11. **Publication condition**
12. **Explicit stop conditions**

Do not bury the acceptance criteria or prohibited actions inside narrative text.

## 4. Read first

List the smallest authoritative files needed for the task.

The prompt MUST tell Jules to inspect existing implementation and tests before
writing replacements. When an accepted helper, fixture, schema, validator, or
policy already exists, reuse it unless the task explicitly requires changing
it.

Do not copy large existing fixtures or policy tables into a new test merely for
convenience. Duplicate semantics drift.

## 5. Allowed paths are a hard fence

List exact files Jules may ADD or MODIFY.

Rules:
- paths outside the list are forbidden;
- no opportunistic refactor;
- no unrelated formatting cleanup;
- no dependency/lockfile/workflow changes unless explicitly listed;
- no deletion/rename unless explicitly authorized;
- if a correct solution genuinely requires an out-of-scope file, STOP and
  report the blocker instead of silently widening scope.

The controller independently compares the final changed-path set to this list.

## 6. Reuse-first / no semantic duplication

Before implementing a new validator, fixture, enum, policy, hash rule, provider
order, or state machine, search for the accepted source of truth.

Prompt language SHOULD explicitly say:

> Reuse the existing accepted implementation/fixture/helper. Do not duplicate,
> weaken, or reinterpret its semantics.

A test that manually recreates a large production fixture is weaker than a test
that imports the existing canonical fixture.

## 7. Hard prohibitions must be explicit

State concrete forbidden actions relevant to the task, for example:

- no live provider/model/API call;
- no network/socket/HTTP;
- no filesystem I/O in production code;
- no secrets/credential lookup;
- no billing/settings/permissions changes;
- no workflow changes;
- no OIDC/attestation issuance;
- no Merge;
- no direct default-branch write;
- no force push/history rewrite;
- no rebase/automatic merge-conflict resolution;
- no automatic retry/fallback;
- no arbitrary shell construction;
- no long-running server/dev process.

"Be careful" is not a prohibition.

## 8. Semantic acceptance, not green-test acceptance

A green existing suite is evidence, not acceptance.

Each important requirement MUST have a direct observable assertion or other
machine-checkable proof. Examples:

- exact map keys, not merely map length;
- exact integer type, not bool-equivalent integer behavior;
- recomputed digest equality, not only regex shape;
- cross-field state consistency;
- exact provider order;
- exact call count;
- malformed/tampered dependency outputs fail closed;
- output does not leak raw untrusted input;
- unsafe imports/calls are absent when the task is static-only.

The independent reviewer may reject a green Jules result if semantic
requirements are not directly covered.

## 9. Vacuous tests are forbidden

Do NOT satisfy an acceptance criterion with tests such as:

- `assertTrue(True)`;
- `pass`;
- assertions unrelated to the stated requirement;
- a test name that claims a property but never observes it;
- checking that a file/string merely exists when behavior is required;
- only checking happy paths for a fail-closed contract.

Docs claims that matter to safety SHOULD be read back by a test when practical.

## 10. Negative cases are first-class requirements

For validation/safety code, the prompt MUST enumerate representative bad cases,
not just say "add edge cases".

Prefer matrices covering:
- missing/extra keys;
- wrong enum/value;
- wrong exact key set;
- bool-as-int;
- malformed/non-hex/uppercase/wrong-length hashes;
- digest mismatch after otherwise-valid mutation;
- cross-field inconsistency;
- duplicate/out-of-order values;
- path/ref traversal or control characters when applicable;
- mutation isolation;
- exception/failure of dependencies;
- untrusted-string leakage.

## 11. Do not weaken the contract to make tests green

If a new test fails:

1. determine whether implementation or test is wrong;
2. preserve the original requirement;
3. fix only the proven cause;
4. do not silently remove assertions, broaden enums, permit extra fields, or
   relax fail-closed behavior merely to reach green.

A demonstrably false-positive test may be narrowed, but the reason must be
recorded and the safety property preserved.

## 12. Exact bounded validation commands

Specify exact finite commands. Do not use open-ended commands such as a dev
server.

Typical repository validation:

```text
PYTHONPATH=src python -m unittest discover -s tests -t . -v
python -m compileall -q src tests
git diff --check
```

The task may run focused tests first. The full required suite should run exactly
as instructed before publication.

## 13. Publication condition

Jules may publish its normal isolated PR only if:

- the allowed-path fence is respected;
- required tests/checks pass;
- no hard prohibition was crossed;
- no unresolved ambiguity affects correctness.

Jules MUST NOT Merge.

The controller/reviewer then independently verifies ancestry, changed paths,
semantic diff, tests, and exact HEAD evidence. Jules saying "PASS" is not PASS.

## 14. Merge conflicts and stale bases

Do not ask Jules to repair an unrelated stale/dirty/conflicted target by
guessing.

Tasks start from an exact clean non-default HEAD/tree. If the target changed,
the controller creates a fresh bounded work branch or otherwise handles the
safe synchronization outside Jules. Jules must not rebase, create a merge
commit, force-push, discard local work, or auto-resolve unrelated conflicts
unless a later explicit task narrowly authorizes that operation.

## 15. Stop conditions

The prompt MUST tell Jules to stop and preserve/report partial work when:

- an allowed-path expansion is required;
- a formal spec conflicts with the task;
- a permission/billing/auth/live boundary is reached;
- required evidence cannot be verified;
- a destructive operation would be necessary;
- the target branch is not the expected snapshot;
- the task would require a new architecture/product decision.

Do not convert a real blocker into guessed implementation.

## 16. Standard task skeleton

Use this skeleton and replace every placeholder with concrete task-specific
content:

```text
Loop NNN — bounded <SHORT|MEDIUM|LONG> <task class>.

Goal:
<one coherent mission and explicit non-goals>

Read first:
- <authoritative existing files>

Allowed changed paths only:
- <exact path 1>
- <exact path 2>

Hard scope / Do Not Touch:
- <explicit prohibitions>
- retry=0
- fallback=disabled
- no Merge

Reuse-first:
- Search for and reuse <existing helper/fixture/policy/schema>.
- Do not duplicate or weaken accepted semantics.

Required semantics:
1. <machine-observable requirement>
2. <machine-observable requirement>

Negative/tamper cases:
- <specific invalid case>
- <specific invalid case>

Acceptance criteria:
- Each semantic requirement above has a direct assertion/proof.
- No vacuous tests (`pass`, `assertTrue(True)`, unrelated assertions).
- Changed paths are exactly within the allowlist.
- Existing green tests alone are not sufficient.

Validation:
<exact focused commands if useful>
PYTHONPATH=src python -m unittest discover -s tests -t . -v
python -m compileall -q src tests
git diff --check

Publication:
Publish the normal isolated Jules PR only if all required checks are green.
Do not Merge.

Stop and report instead of guessing if:
- <task-specific blocker>
- an out-of-scope change is required
- a safety/permission/live/architecture boundary is reached
```

## 17. Controller/reviewer checklist after Jules returns

The controller MUST independently verify:

- result branch/PR belongs to the intended session;
- base/ancestry is correct;
- changed paths are a subset of the allowlist;
- no unrelated changes;
- each semantic acceptance criterion is actually implemented;
- negative tests directly exercise the claimed failure mode;
- no vacuous tests;
- no duplicated fixture/policy semantics when reuse was required;
- exact-head validation is run against the candidate;
- only validated content is published to canonical;
- canonical is independently revalidated;
- durable evidence/checkpoint is recorded;
- retry/fallback/Merge/live boundaries were preserved.

## 18. Rule precedence

This prompt specification does not override:
- formal Phase 0 safety/specification documents;
- explicit current-task restrictions;
- system approval boundaries;
- human-only Merge/live/billing/permission decisions.

Where they conflict, the stricter applicable boundary wins.
