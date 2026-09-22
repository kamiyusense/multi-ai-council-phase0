# Chat/Work GitHub command bus

GitHub is the durable control plane. Commands and receipts are append-only; only loop state is mutable.
The processor validates the repository, the target PR, `expected_target_head` (the current head of `expected_pr`), correlation, expiry, STOP, terminal receipts, and the six-round ceiling before processing.
The carrier/implementation PR head is separate metadata and is never compared through `expected_target_head`.
Unknown or ambiguous conditions are blocked without retry or fallback.

The runtime is intentionally limited to `automation/command_bus/**`; it does not execute Jules, providers, live models, API keys, or GitHub workflows.
