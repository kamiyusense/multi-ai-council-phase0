# Transport fallback proposal (read-only design conclusion)

Status: proposal only. This document does not authorize live browser use, Google sign-in, Jules task submission, provider execution, settings changes, or permissions changes.

## Conclusion

If Cloud Browser is unavailable or blocked at authentication, Work's built-in browser / Computer Use may be evaluated as a separate transport adapter. It must not be treated as provider fallback, model fallback, or an automatic retry.

## Required identity and safety rules

- A blocked Cloud Browser command reaches a terminal `BLOCKED` or `UNKNOWN` result; it is not retried through another transport.
- Any later attempt through the built-in browser / Computer Use requires a new command identity, correlation, expiry, and durable request record.
- The new command must independently validate the same repository, PR, target head/tree, permissions, and action scope before any live authorization is considered.
- `retry=0` remains unchanged. `fallback=disabled` remains unchanged. `retry_count` remains `0` and `fallback_used` remains `false` for each command.
- Browser UI output is transport material only. GitHub readback and durable receipt/evidence remain the correctness source.
- A transport adapter must not select a model, change provider routing, enable paid/API fallback, or bypass Safety gates.
- Authentication remains a user-controlled boundary; this proposal does not authorize login automation or credential handling.

This preserves the existing runtime contract: transport is replaceable, provider and model fallback remain disabled, and a new transport attempt is a new explicitly identified command rather than a retry of the old command.
