# Durable Loop Owner Authority v1 checkpoint

## Baseline

- Baseline main: `f609724f26f56441cc2c124ef859113d70b41077`.
- PR #59 was merged before this batch.
- Issue #33 remained `STOPPED` with zero comments.
- Runtime Transition Publisher exists on main, but production `OwnerAuthority` remained NOT_WIRED.

## Implemented

- New append-only authority grant ledger:
  `automation/command_bus/loop_owner_authorities/<loop_id>/<generation>.json`.
- Grant schema:
  `automation/command_bus/schema/loop_owner_authority.schema.json`.
- Grant records bind:
  - loop id
  - SEMI_AUTO/AUTO role
  - holder id
  - generation/fencing token
  - previous generation
  - event type
  - repository / target PR / target head
  - command / correlation
  - issuance / expiry
  - durable verification evidence ref
- Authority grant expiry must cover exactly the owner-event lease; issuance may not occur after the owner claim time.
- Grant/event context must match exactly.
- Generation >1 authorization requires durable state to bind either the immediately previous generation or the already-published current generation during recovery.
- The grant backend is create-only with exact readback, identical-record recovery, conflicting-record rejection and no blind retry.
- A grant record by itself is never sufficient. `DurableOwnerAuthority` also requires an independently injected `AuthorityGrantVerifier` proof whose durable source ref matches the grant.
- Missing verifier, rejected proof, mismatched proof source, stale grant, wrong role/head/generation, malformed chain frontier or mismatched state returns no authority.
- Existing executor/reviewer claims remain request-scoped and are not treated as Loop-wide authority.
- Existing workspace mutation leases remain mutation safety gates and are not treated as SEMI_AUTO/AUTO ownership truth.
- `loop_owner_authorities/` is classified as append-only LEDGER data.

## Runtime integration

Static integration tests inject `DurableOwnerAuthority` into the merged Runtime Transition Publisher.

Expected behavior:
- durable grant + no independent verifier => NOT_WIRED at authority stage, zero publisher writes;
- durable grant + matching independent proof => existing Runtime Transition Publisher flow may continue;
- conflicting authority context => NOT_WIRED before evidence/observation/owner/state mutation.

No default authority adapter is installed automatically. Production verifier/issuer remains a separate trust boundary.

## Explicitly not implemented

- No live grant issuer.
- No production AuthorityGrantVerifier.
- No automatic SEMI_AUTO/AUTO acquisition.
- No automatic handoff/takeover.
- No real owner authority record was created.
- No provider/model/Jules/Claude execution.
- No Status workflow dispatch.
- No Issue #33 mutation.

## Exact-head verification

- Exact tested code head:
  `c636b0fd8b9df09addb2abcdb06723715f2d3e2a`.
- GitHub Actions run:
  `36365441925` — **SUCCESS**.
- Focused Status/owner/authority/runtime-publisher/scope tests:
  **139/139 PASS**.
- Full command-bus suite:
  **426 tests run**.
- Exactly one known pre-existing error remained:
  `automation.command_bus.tests.test_jules_api_request.JulesApiRequestTests.test_prompt_binds_head_tree_and_allowlist`.
- CI rejects any additional/unexpected failure.
- Authority grant JSON schema parse: **PASS**.
- All command-bus schema parse: **PASS**.
- Python compileall: **PASS**.
- `git diff --check`: **PASS**.
- PR was OPEN / mergeable=true at exact-head readback.

Any commit after this tested code head must be documentation-only and must be
compared/read back before Merge.

## Remaining live blockers

1. A production issuer for authority grants.
2. A production independent `AuthorityGrantVerifier` bound to a real durable
   authorization source.
3. Production provider verification.
4. Canonical owner receipt adapter for real Jules/other provider transitions.
5. Live Status workflow dispatch/readback adapter.
6. Explicit live authorization before any real SEMI_AUTO/AUTO acquisition,
   handoff or takeover.

The existing executor/reviewer claims and mutation leases are deliberately not
promoted into Loop-wide owner authority.
