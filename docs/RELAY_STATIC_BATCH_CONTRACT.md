# Relay static batch contract

`APPLY_RELAY_STATIC_BATCH` is a prepare-only command for a future Work
executor.  It reads the current head of target PR #4 and compares it with
`expected_target_head`; the dynamic carrier PR #6 head is never a correctness
input.  The fixture is intentionally non-writing: `requires_github_write` is
false and the fake contents client exposes no target write through the batch.

Before preparation, Work must reject malformed or duplicate commands, missing
predecessors, terminal receipts, STOP/HALTED/EXPIRED state, rounds above six,
expired commands, target-head mismatch, and any path outside the allow-list.
Unknown conditions fail closed with retry `0` and fallback `disabled`.

The candidate scope is limited to `src/relay/**`, `src/providers/**`,
`tests/relay/**`, `docs/RELAY_STATIC_CHECKPOINT.md`, and
`RELAY_JULES_HANDOFF.md`.  `main`, `phase0-runs`, secrets, settings, workflow,
billing, auth, API-key, and live-provider paths are prohibited.
