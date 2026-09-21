# Relay Transport Subsystem: Static Implementation

## 1. Boundary & Responsibilities
The Relay serves as the dispatch layer connecting the deterministic Orchestrator with the Provider Adapters (OpenAI/Codex, Anthropic/Claude, Google).

Relay **does not**:
- Implement automatic retry (retry=0).
- Allow automatic fallback to other models or paid tiers.
- Override safety warnings or decisions.

Relay **does**:
- Transport context to the provider adapters.
- Isolate execution so failures do not affect other providers.
- Maintain a duplicate conflict guard (`DuplicateConflictGuard`).
- Provide timeout wrapping (`runWithTimeout`).

## 2. Mock vs Live Execution
In this static implementation phase, there is zero live model execution.
The tests employ a `MockAdapter` that safely verifies:
- Duplicate guard checks.
- Timeout rejection and enforcement.
- Signal abort functionality.
- State machines isolation (ensuring states only transition as mock events succeed).

This separates live network execution logic entirely from the dispatcher's state machine logic.

## 3. Duplicate Guards
The `DuplicateConflictGuard` checks correlation slots and payload hashes (SHA-256).
- **Same Slot + Same Hash**: Treated as a duplicate/re-delivery of an already dispatched request. Returns the existing receipt safely.
- **Same Slot + Different Hash**: Detected as a conflict. Immediately rejected with an error to prevent silent data corruption or unintended overwrite.

## 4. Known UNKNOWNs (Deferred Items)
As detailed in `RELAY_JULES_HANDOFF.md` Section 9, several factors remain unknown and block future live execution, but do not block this static implementation:
- Actual provider timeout values.
- Minimum CLI permission profiles.
- Executed-model verification mechanisms.
- Subscription-auth verification methods.
- Google agy / Antigravity ACP compatibility.
- Feasibility of provider network restrictions.
- Exactly-once semantics behavior in live edge cases.
