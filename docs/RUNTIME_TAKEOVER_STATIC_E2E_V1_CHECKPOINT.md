# Runtime takeover static E2E v1 — checkpoint

## Dependency

This is a stacked static test layer on top of:

- PR #71 takeover preflight — merged
- PR #74 takeover request preparation — open dependency

The stacked PR should remain based on
`feature/runtime-takeover-prepare-v1` until PR #74 is merged.

## Purpose

Prove the complete takeover code path with deterministic fakes/mocks only:

`preflight_takeover`
→ `prepare_takeover_transition`
→ source-bound AuthorityGrantVerifier
→ source-bound ProviderVerifier
→ `RuntimeTransitionPublisher`
→ Status prepare-only boundary

## Mock-only guarantees

The E2E test uses:

- in-memory fake GitHub contents client;
- fake target reader;
- fake Status prepare boundary;
- deterministic source readers;
- deterministic source authenticators;
- no network;
- no live provider;
- no live GitHub workflow dispatch;
- no real runtime ledger;
- no Issue #33 mutation.

## Positive path

The test begins with generation 1 SEMI_AUTO owner state and prepares an expired
owner HANDOFF to generation 2 AUTO.

The full mock pipeline verifies:

- current generation 1 chain/state/receipt/provider history;
- generation 2 HANDOFF/fencing;
- canonical takeover evidence;
- explicit authority grant;
- independently authenticated authority source;
- independently authenticated provider source;
- desired state binding;
- publisher evidence write;
- provider-observation write;
- owner generation append;
- state CAS;
- final deterministic validation;
- Status prepare plan with AUTO / generation 2.

## Negative paths

The static E2E also requires fail-closed behavior for:

- missing authority authenticator;
- missing provider authenticator;
- stale/moved target head.

All negative paths must stop before durable mutation in the fake client.

## Explicitly not performed

- no production source reader/authenticator;
- no authority issuer;
- no runtime GitHub mutation;
- no workflow_dispatch;
- no Issue #33 mutation;
- no real provider/model execution;
- no real takeover;
- no default-branch write;
- no Merge.
