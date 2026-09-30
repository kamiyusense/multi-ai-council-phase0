# Claude Jules Origin Binding V1

The `CLAUDE_AUTO_ORIGIN_BINDING_V1` contract is a pure, static, and memory-only representation of the linkage between Claude AUTO origin identity (`origin_loop_id`, `origin_round`, `origin_correlation_id`, `origin_generation`) and the current live semi-auto Jules carrier request/claim schema logic.

## Scope

This module is **STATIC PREP only**. It introduces exact-key standalone validation, deterministic digest hashing, and strict cross-binding to verified carrier structures.

- It explicitly **does not** validate the current carrier request or claim beyond what is needed to verify the binding fields. It strictly relies on current carrier validation routines to run first.
- It explicitly **does not** define a durable file location, orchestrate filesystem storage, trigger workflow transitions, or activate any live integrated pipeline.
- It explicitly **does not** claim integrated Claude-verdict to Jules LIVE paths are authorized.
- Integrated runtime state remains **UNKNOWN** and not authorized.

## Cross-Binding Guarantees

This pure module enforces the following strict linkages before emitting a standalone valid binding record:
- The carrier request and claim refer to the same logical action (`command_id`, branches, target commits).
- The action maintains static `retry=0` and `fallback=disabled` boundaries.
- The binding binds the valid carrier payload to the strictly-typed Claude AUTO origin fields.

Any mismatch results in immediate fail-closed state without leaking missing keys or internal structural gaps.
