# Jules owner receipt + Status prepare plan v1 checkpoint

## Baseline

- Baseline main: `57a87a59c54022c7121e12575a2b101d95499285`.
- PR #63 was merged before this batch.
- Issue #33 remained `STOPPED` with zero comments.

## Implemented

### Provider-neutral canonical owner receipt

`runtime_transition_receipt.py` adds a provider-neutral TERMINAL owner-receipt
builder and create-only GitHub backend.

The canonical owner receipt:
- is derived only from an already validator-approved provider terminal receipt;
- binds the owner event loop/command/correlation/receipt identity;
- carries exactly the owner generation's canonical evidence refs;
- preserves retry=0 / fallback=false / executed_once=true;
- records provider kind and source provider receipt identity/path;
- never reuses the provider receipt path as the owner receipt path;
- is create-only with exact readback;
- recovers an identical existing receipt without a new create;
- blocks a conflicting existing receipt;
- resolves ambiguous create by readback and never blindly retries.

This adapter is intentionally TERMINAL-only. Jules terminal evidence cannot be
used to fabricate ACQUIRE/RENEW/HANDOFF ownership.

### Jules terminal receipt adapter

`runtime_transition_jules.py` now includes a static
`JulesTerminalOwnerReceiptAdapter`.

It:
1. fresh-reads the durable Jules terminal receipt from its round-scoped receipt
   path;
2. validates the receipt;
3. derives the canonical TERMINAL owner receipt;
4. writes it through the provider-neutral create-only owner-receipt backend.

It does not launch Jules, infer owner authority, verify provider authority, or
dispatch Status.

### Prepare-only Status refresh adapter

`runtime_transition_status.py` converts an already verified
`StatusRefreshPlan` into the deployed Status workflow call shape.

The prepared workflow is fixed to:
- workflow: `.github/workflows/loop-status-signal.yml`
- executable code ref: `main`
- inputs: exactly `loop_id` and `state_ref`

Owner, provider state and notification event identity are not exposed as
workflow inputs.

The adapter is prepare-only. It performs no Actions dispatch, no network call,
no retry, and no Issue mutation.

## Still not wired

- Production authority-grant issuer.
- Production independent AuthorityGrantVerifier.
- Production ProviderVerifier.
- Live Status workflow dispatch/readback adapter.
- Real SEMI_AUTO/AUTO acquisition, handoff or takeover.

No runtime owner/authority/provider-observation record was created in this
batch. No Jules/Claude/provider/model execution occurred. Issue #33 was not
modified.

## Exact-head verification

- Exact tested code head:
  `8a3949b2fd9f9e7d81e3bbfebf519046669a4171`.
- GitHub Actions run:
  `36366258087` — **SUCCESS**.
- Focused Status/owner/authority/runtime-publisher/Jules-receipt tests:
  **148/148 PASS**.
- Full command-bus suite:
  **435 tests run**.
- Exactly one known pre-existing error remained:
  `automation.command_bus.tests.test_jules_api_request.JulesApiRequestTests.test_prompt_binds_head_tree_and_allowlist`.
- CI rejects any additional/unexpected failure.
- All command-bus JSON schemas parse: **PASS**.
- Python compileall: **PASS**.
- `git diff --check`: **PASS**.
- PR was OPEN / mergeable=true at exact-head readback.

Any commit after this tested code head must be documentation-only and compared/read
back before Merge.

## Remaining live blockers

1. Production authority-grant issuer.
2. Production independent AuthorityGrantVerifier.
3. Production ProviderVerifier.
4. Live Status workflow dispatch/readback adapter.
5. Explicit live authorization before real SEMI_AUTO/AUTO acquisition/handoff/takeover.

The Jules terminal receipt path is now statically bridgeable into the canonical
owner receipt contract, but the adapter still does not launch Jules or grant
ownership.
