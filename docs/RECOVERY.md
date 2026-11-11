# Phase 0 Static Core Recovery

This document covers static/mock recovery only. It does not authorize live provider execution.

## Fail-closed recovery rule

If a static/mock case encounters an unexpected condition:

1. stop new dispatches for that run when continuing could overwrite or confuse evidence;
2. preserve any RAW bytes already obtained;
3. preserve provider-local state independently;
4. do not retry the failed provider automatically;
5. do not substitute another model/provider as fallback;
6. record `ERROR_UNKNOWN`, `INVALID_OUTPUT`, `TIMEOUT`, or the deterministic state supported by evidence;
7. keep unaffected provider evidence/results;
8. return the run to human review.

## Evidence priority

Prefer direct evidence in this order where available:

- raw bytes written before parse/validation
- hashes
- provider state file
- filesystem before/after/diff
- comparison outputs
- checkpoint

Do not turn absence of evidence into PASS.

## Live boundary

This static branch hard-disables `ExecutionMode.LIVE`. Recovery from a future live provider turn is intentionally deferred until provider-specific auth, permissions, timeout, model verification, abort semantics, and Relay evidence have been independently resolved and explicitly approved.
