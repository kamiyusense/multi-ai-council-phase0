# Phase 0 Core Static Implementation

Status: initial static/mock batch

This branch implements Relay-independent deterministic core pieces while the Relay subsystem evolves independently on `feature/relay-transport`.

## Boundary

Included:
- run/provider manifest models
- execution/participation/answer/capability state axes
- finite-timeout and Provider Response Contract validation
- deterministic fail-closed fan-out skeleton
- disposable workspace path/snapshot checks
- RAW-first evidence helpers and filesystem hash diff
- stop/no-new-dispatch control
- transport-neutral Provider Adapter protocol
- mock provider
- deterministic comparison
- Japanese report skeleton
- static/mock Case Runner skeleton
- unit/regression tests

Excluded:
- ACP/OpenHands/conduct dependency adoption
- live Codex/Claude/agy invocation
- API key or paid routes
- model fallback
- automatic retry
- permission changes/bypass
- GitHub runtime writes
- automatic Merge

## Relay synchronization point

Core depends only on the transport-neutral adapter contract. Relay PR #2 may implement its own transport internals. Integration should occur only after the Relay interface is stable enough to map to:

- prepare
- preflight
- dispatch
- collect
- abort
- classify

No Relay implementation is copied into this branch.

## Deferred before live

- provider timeout values
- exact permission profiles
- executed-model verification methods
- subscription-auth verification methods
- network restriction feasibility
- final secret/PII patterns
- agy/Antigravity transport choice

All safety-relevant UNKNOWN values remain blocking for future live execution.
