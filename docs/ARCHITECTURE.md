# Phase 0 Architecture and Relay Boundary

Updated: 2026-09-21

## 1. Purpose

This document defines how the **Relay** work fits inside the larger **Multi-AI Council Phase 0** implementation so that separate agents can work concurrently without mixing responsibilities.

The Relay is **not a separate product/repository at this stage**. It is one subsystem inside `multi-ai-council-phase0`.

## 2. System boundary

```text
User input
   |
   v
Council Orchestrator
   |
   +--> Safety / Fan-out Gate
   |
   +--> Relay / Dispatch Layer
   |       |
   |       +--> OpenAI provider adapter
   |       +--> Anthropic provider adapter
   |       +--> Google provider adapter
   |
   +<-- Provider RAW / structured response
   |
   +--> Evidence / Manifest / State
   |
   +--> Deterministic Comparison
   |
   +--> Japanese Report
   |
   v
Human final decision
```

## 3. Responsibility split

### Council Orchestrator

Owns overall execution order and case lifecycle.

Responsibilities:

- case lifecycle
- preflight sequencing
- fan-out gate sequencing
- provider dispatch ordering/coordination
- stop/no-new-dispatch behavior
- state-machine orchestration
- invoking deterministic comparison/reporting

It does **not** infer semantic agreement from free text.

### Relay

Owns transport between the Orchestrator and approved provider adapters.

Responsibilities:

- accept an already-approved provider packet/context
- invoke the selected adapter through a fixed interface
- carry process handle / timeout / abort signals
- return raw process/result material to the caller
- preserve provider identity and per-provider isolation

Relay must **not** decide:

- whether private/secret/PII data may be sent
- whether 2/3 is a formal Council decision
- whether a safety warning may be ignored
- whether a model mismatch is acceptable
- whether retry/fallback is allowed
- what the human should decide

Those decisions remain outside Relay.

### Provider adapters

Provider-specific invocation boundary:

- OpenAI / Codex CLI
- Anthropic / Claude CLI
- Google / agy

Each adapter is isolated by provider process/workspace/manifest/timeout.

### Safety

Owns deterministic gates and fail-closed decisions:

- fan-out gate
- secret/PII/private-code checks
- capability/auth/permission readiness
- live-gate checks
- model mismatch / verification failure handling

Relay does not bypass Safety.

### Evidence

Owns:

- RAW-first preservation
- hashes
- manifests
- filesystem before/after/diff
- checkpoint evidence

### Comparison

Owns deterministic structured-response comparison.

It uses the Provider Response Contract, not free-text semantic guessing.

## 4. Planned source layout

The implementation should keep subsystem boundaries visible in paths.

```text
src/
  orchestrator/
  relay/
  providers/
    openai/
    anthropic/
    google/
  safety/
  evidence/
  comparison/
  reporting/

schemas/
fixtures/
tests/
docs/
```

The exact filenames may evolve, but the responsibility boundary above must remain explicit.

## 5. Dependency direction

Preferred dependency direction:

```text
orchestrator
  -> safety
  -> relay
       -> providers
  -> evidence
  -> comparison
  -> reporting
```

Important rules:

- `relay` must not call `comparison` to decide agreement.
- `relay` must not weaken or override `safety`.
- `providers` must not write to GitHub.
- `providers` must not trigger retry/fallback themselves.
- `comparison` must not launch providers.
- runtime GitHub write remains prohibited.

## 6. Concurrent development / branch separation

Different agents may work in the same repository if they use separate feature branches and clear scopes.

Recommended examples:

- `feature/relay-transport`
- `feature/case-runner`
- `feature/fanout-gate`
- `feature/provider-openai`
- `feature/provider-anthropic`
- `feature/provider-google`

A handoff must record:

- repository
- branch
- base/checkpoint commit SHA
- files changed
- tests actually run
- PASS / FAIL / UNKNOWN
- blockers
- whether any live model was executed

Do not have two agents modify the same files on the same branch concurrently.

## 7. Relay-agent safe scope before live approval

A Relay-focused implementation agent may safely continue with **static implementation only**:

- relay interfaces
- adapter abstractions
- mock providers
- timeout validation plumbing
- stop/abort plumbing
- provider isolation fixtures
- deterministic tests
- documentation

It must stop before:

- any new live provider model turn
- API-key or metered API route
- Billing/Credits/Overages changes
- settings/permission changes
- GitHub Merge
- force push
- destructive branch/history operations

## 8. GitHub checkpoint model

For development, GitHub is the common save point.

```text
feature branch
  -> commit
  -> GitHub checkpoint SHA
  -> review by Chat/Jules/other agent
  -> additional commit if needed
  -> PR
  -> human-approved Merge
```

This development workflow is separate from the Phase 0 runtime rule that the runtime itself performs no GitHub writes.

## 9. Source-of-truth relationship

- Council principles/history/design decisions:
  `kamiyusense/multi-ai-council-raw-records`
- Phase 0 implementation + implementation handoff/checkpoints:
  `kamiyusense/multi-ai-council-phase0`
- AIBO application:
  `kamiyusense/AIBO-MkII`

Do not silently move responsibilities across these repository boundaries.
