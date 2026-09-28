# Control Tower explicit identity-state boundary v1 — checkpoint

## Baseline

Repository:
`kamiyusense/multi-ai-council-phase0`

Baseline main:

`7999d8f91d1ebed09a342977e03023699314be40`

PR #86 live-migration preflight was merged before this batch.

Issue #33 remained the deployed single-loop STOPPED display.

## Problem

The CT-1 display registry intentionally contains four human-facing candidate
identifiers:

- `chatgpt-semi-auto`
- `claude-gemini`
- `claude-claude`
- `work-gemini`

Fresh audits established that these strings are still presentation/test
identities and are not independently proven final durable runtime loop IDs.

The existing registration and live-migration gates already prevented migration
without matching durable TransitionProjectionResult values.

However, the registry field was still named `loop_id` with no machine-readable
marker saying whether the value was only a placeholder or had been deliberately
adopted as the durable runtime identity.

A future runtime could therefore accidentally begin using the same string and
make the transition look ready without an explicit identity-adoption step.

## Change

The Control Tower registry now requires:

`identity_state`

with the bounded values:

- `PLACEHOLDER`
- `DURABLE`

The repository's four current lanes are explicitly:

`identity_state = PLACEHOLDER`

This is presentation metadata describing adoption state. It is not owner,
provider, fencing, or runtime truth.

## Registration rule

An enabled PLACEHOLDER lane can never make
`assess_registration_readiness()` return READY.

This remains true even if a caller supplies a
`TransitionProjectionResult` whose loop_id happens to equal the placeholder
string.

Expected result:

```text
PLACEHOLDER
+ same-named durable transition
= NOT_WIRED
```

Only an explicitly adopted registry identity may proceed:

```text
identity_state = DURABLE
+ exact accepted TransitionProjectionResult
+ existing projection and OwnerDecision
+ exact projection.loop_id
= READY candidate
```

All other existing durable gates remain unchanged.

## Renderer behavior

The pure CT-1 renderer is still allowed to render fixture inputs using a
PLACEHOLDER registry entry.

That preserves static/mixed-state presentation testing.

The rendered machine snapshot now includes `identity_state`, so a presentation
consumer can distinguish placeholder fixture identity from deliberately adopted
durable identity.

The production-facing live migration preflight remains the authority for whether
an Issue #33 migration plan may be prepared.

## Adoption procedure for a real loop

Do not flip the registry to DURABLE merely to unblock Control Tower.

For each real runtime lane:

1. the loop implementation chooses its stable durable loop_id;
2. its actual command-bus state / owner chain / receipts / evidence / provider
   observation use that exact ID;
3. the existing transition verifier produces an accepted
   `TransitionProjectionResult` under that ID;
4. only then update the matching Control Tower registry entry:
   - change `loop_id` if the final durable ID differs from the placeholder;
   - set `identity_state=DURABLE`;
5. registration readiness must still verify the exact transition result;
6. live migration preflight must still reach READY before any Issue mutation.

A registry edit by itself is never sufficient proof.

## Why no IDs are chosen here

Fresh readback already established:

- ChatGPT Semi-Auto sequential `relay-dev-loop-NNN` identifiers are command/task
  identities, not a proven persistent owner-ledger identity;
- PR #25 Claude code accepts loop_id from its caller and does not define final
  Claude -> Gemini / Claude -> Claude IDs;
- no final Work -> Gemini durable ID has been established.

Therefore this batch does not invent or assign final IDs.

`CONTROL-TOWER-REAL-LOOP-IDS-001 = UNKNOWN`

remains correct.

## Tests added/updated

Coverage now requires:

- all four repository registry entries are explicitly PLACEHOLDER;
- unknown identity_state values fail closed;
- snapshot carries identity_state;
- a PLACEHOLDER lane with a matching transition remains NOT_WIRED;
- synthetic DURABLE lane + matching accepted transition can become READY;
- live migration remains NOT_WIRED for repository placeholders even if matching
  transitions are supplied for all four strings.

## Explicitly not performed

- no final durable loop ID assignment;
- no Issue #33 PATCH/comment;
- no workflow_dispatch;
- no owner/state/receipt/evidence/provider mutation;
- no provider/model/Jules/Claude/Gemini execution;
- no takeover;
- no CT-3 Development migration;
- no Windows executable;
- no default-branch direct write;
- no Merge in this batch.

## Evidence to fill after exact-head CI

- exact tested PR head: PENDING
- GitHub Actions run: PENDING
- focused tests: PENDING
- full command-bus tests: PENDING
- schema parse: PENDING
- compileall: PENDING
- git diff --check: PENDING
- tested head -> current head compare: PENDING
- Issue #33 live mutation: MUST REMAIN NONE
