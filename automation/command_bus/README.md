# Chat/Work GitHub command bus

GitHub is the durable control plane. Commands and receipts are append-only; only loop state is mutable. The processor validates repository, PR, expected head, correlation, expiry, STOP, terminal receipts, and the six-round ceiling before processing. Unknown or ambiguous conditions are blocked without retry or fallback.

The runtime is intentionally limited to `automation/command_bus/**`; it does not execute Jules, providers, live models, API keys, or GitHub workflows.
