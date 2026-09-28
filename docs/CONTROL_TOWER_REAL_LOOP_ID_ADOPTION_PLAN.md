# Control Tower real durable loop ID adoption plan

## Purpose

This document defines the final pre-live-migration adoption boundary for the
four planned Phase 0 Runtime lanes.

It does **not** choose or invent the final loop IDs.

The Control Tower display registry currently contains presentation placeholders:

1. ChatGPT Semi-Auto
2. Claude -> Gemini
3. Claude -> Claude
4. Work -> Gemini

Those entries remain `identity_state=PLACEHOLDER` until the corresponding
runtime implementation itself exposes a stable durable identity.

## Core rule

A display name or convenient command/task identifier is not enough.

Promotion requires:

```text
real runtime implementation
+ stable loop_id
+ durable state at state/<loop_id>.json
+ append-only owner chain at loop_owner_events/<loop_id>/
+ source receipt bound to latest generation
+ exact evidence refs
+ active provider observation when required
+ fresh target identity/head
+ accepted project_durable_transition()
= eligible for explicit identity_state=DURABLE
```

The registry edit is the **last** adoption step, not the proof source.

## Forbidden shortcuts

Do not promote a placeholder because:

- its name looks stable;
- a Chat/Work/Jules task number exists;
- a PR or branch uses a similar name;
- a workflow is active;
- a commit is recent;
- a provider appears alive;
- a matching file path is created without the full durable chain;
- Control Tower migration would otherwise remain blocked.

Do not use Chat silence, PR activity, commit time, ETA, or display state as
durable identity proof.

## Lane A — ChatGPT Semi-Auto

Current known operational artifacts include sequential request/task identifiers
such as `relay-dev-loop-NNN...`.

Those are not yet proven persistent owner-ledger identities.

Adoption requires the Semi-Auto runtime path to deliberately choose one stable
lane loop_id and use it consistently for:

- state;
- owner generations;
- receipts;
- canonical evidence;
- provider observations;
- fresh target verification.

Human loop numbers may continue as presentation metadata
(`loop_number`) and must remain separate from durable loop_id.

Until that exists:

`ChatGPT Semi-Auto = PLACEHOLDER / NOT_WIRED`

## Lane B — Claude -> Gemini

The current Claude loop implementation accepts `loop_id` as caller input.

Caller input alone is not an adopted stable durable identity.

Before adoption, the Claude->Gemini controller path must:

1. define the stable lane identity it will reuse across turns;
2. persist the existing durable state/owner/receipt/evidence/provider records
   under that exact ID;
3. verify the target and provider evidence through existing contracts;
4. produce an accepted `TransitionProjectionResult`;
5. only then update the Control Tower registry entry to the exact loop_id and
   set `identity_state=DURABLE`.

Until then:

`Claude -> Gemini = PLACEHOLDER / NOT_WIRED`

## Lane C — Claude -> Claude

Use a separate durable identity from Claude->Gemini even if the same controller
technology is reused.

The worker identity and durable loop identity must remain unambiguous.

The same adoption proof as Lane B is required.

Until then:

`Claude -> Claude = PLACEHOLDER / NOT_WIRED`

## Lane D — Work -> Gemini

No final durable Work->Gemini loop identity is established by current Control
Tower evidence.

Before adoption, the actual Work controller path must expose its stable loop_id
through the same durable command-bus state/owner/receipt/evidence/provider/target
chain.

A Work conversation/thread URL is never a durable loop identity and must never
be written to the public repository.

Until then:

`Work -> Gemini = PLACEHOLDER / NOT_WIRED`

## Adoption transaction

For one lane at a time:

1. implement the real runtime lane's stable loop_id;
2. produce deterministic fixture/static tests for the durable record path;
3. run non-live regression tests;
4. when live execution is explicitly authorized, obtain one verified durable
   transition under the stable ID;
5. fresh-read the exact durable transition using the read-only Control Tower
   collector;
6. require collector result `COLLECTED` and accepted
   `TransitionProjectionResult`;
7. update the matching registry entry:
   - `loop_id=<real stable id>`
   - `identity_state=DURABLE`
8. run registration readiness and live-migration preflight;
9. keep Issue #33 unchanged until every enabled lane required for first
   migration is READY.

A single lane may be adopted and tested while others remain PLACEHOLDER.
The first live multi-loop Issue migration still requires the enabled migration
set to satisfy the existing registration/live-preflight gates.

## Collision / rename rules

A durable loop_id:

- must match the existing bounded loop-id format;
- must not collide with another enabled lane;
- must not be silently renamed after durable records exist;
- must not be recycled for a different controller/worker lane.

If a durable identity must change, treat it as an explicit migration with new
durable records. Do not reinterpret old owner generations under a new identity.

## Recovery and readback

After adoption:

- the read-only collector must obtain stable readbacks;
- registration must be READY;
- machine snapshot may display `identity_state=DURABLE`;
- Windows remains presentation-only;
- registry state alone never replaces durable evidence.

If durable readback later becomes UNKNOWN/BLOCKED, the Control Tower reflects
the verified projection; it does not silently demote or rename the identity.

## Current decision

As of 2026-09-28:

`CONTROL-TOWER-REAL-LOOP-IDS-001 = UNKNOWN`

This is intentional. The remaining work is now primarily real runtime
integration, not additional presentation architecture.

## Next implementation order

Recommended dependency order:

1. ChatGPT Semi-Auto — adopt one stable durable lane ID and prove the full chain;
2. Claude -> Gemini — bind the existing Claude controller path to a stable ID;
3. Claude -> Claude — same contract, distinct durable identity;
4. Work -> Gemini — same contract once the actual Work controller path exists;
5. run multi-loop collector + registration + live-migration preflight;
6. only then perform the separately authorized Issue #33 live migration.

The order above is an implementation dependency recommendation, not runtime
priority or ownership truth.


## PR verification

Exact tested PR head:

`b6a898b636846a7c716279b709fa6e5a9e30481f`

GitHub Actions run:

`36393149222` — **SUCCESS**

Evidence:

- focused Status/runtime/validation suite: **285/285 PASS**
- full command-bus suite: **693/693 PASS**
- command-bus JSON schemas parsed: **22/22 PASS**
- Python compileall: **PASS**
- `git diff --check`: **PASS**
- full command-bus regression includes the merged migration-recovery tests
- Issue #33 was not mutated by this batch

The current branch head after this verification entry may be one
documentation-only commit ahead of the tested head.
