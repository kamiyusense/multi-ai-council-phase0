# Phase 0 Core Static Implementation

Status: full mock-pipeline batch

This branch implements Relay-independent deterministic core pieces while the Relay subsystem evolves independently on `feature/relay-transport`.

## Implemented

- run/provider manifest models
- execution/participation/answer/capability state axes
- finite-timeout validation
- strict Provider Response Contract validation
- JSON Schema contract artifacts
- deterministic fail-closed fan-out skeleton
- provider snapshot creation only after fan-out PASS
- disposable workspace path/snapshot/symlink guards
- RAW-first evidence helpers
- filesystem before/after/hash diff
- stop/no-new-dispatch control
- transport-neutral Provider Adapter protocol
- configurable mock provider
- provider failure isolation
- deterministic comparison
- Japanese report generation with secret masking on errors
- complete three-provider mock Case Runner pipeline
- fixture/unit/regression tests
- recovery and known-limitations documents

## Full mock path

```text
input / packet
-> input hashes + run manifest
-> fail-closed fan-out gate
-> isolated provider snapshots
-> mock adapter preflight/dispatch/collect
-> RAW saved before parse/validation
-> Provider Response Contract validation
-> provider-local state + fs before/after/diff
-> deterministic comparison
-> Japanese summary
-> checkpoint
-> human final decision
```

One provider failure does not erase another provider result. Invalid output becomes `INVALID_OUTPUT`; timeout becomes `TIMEOUT`; unexpected adapter failures become `ERROR_UNKNOWN`. None triggers retry or fallback.

## Relay synchronization point

Core depends only on the transport-neutral adapter contract:

- prepare
- preflight
- dispatch
- collect
- abort
- classify

Relay PR #2 may implement transport internals separately. This branch does not adopt ACP/OpenHands/conduct yet and does not modify Relay-owned `src/relay/**` or `src/providers/**` paths.

## Non-negotiable static safety

- live provider execution disabled
- automatic retry = 0
- fallback disabled
- no API-key/paid route
- no permission bypass
- no runtime GitHub writes
- UNKNOWN never becomes PASS
- formal Council consensus is never auto-promoted
- final decision remains human

## Deferred before live

- provider timeout values
- exact permission profiles
- executed-model verification methods
- subscription-auth verification methods
- network restriction feasibility
- final secret/PII/private-code patterns
- final marker format/completeness rule
- agy/Antigravity transport choice

All safety-relevant UNKNOWN values remain blocking for future live execution.
