# Runtime takeover prepare v1 — static checkpoint

## Baseline

- Baseline main: `472f2d2ee4539581eb9c17c022d32d70330c1859`.
- PR #71 takeover preflight is merged.
- PR #73 carries the separate Chat-first / Work fallback documentation rule.
- Issue #33 is not mutated by this batch.

## Purpose

Bridge the verified takeover preflight into the existing
`RuntimeTransitionPublisher` request contract without performing any GitHub
write or live action.

## Implemented

`runtime_takeover_prepare.py`:

1. reruns `preflight_takeover`;
2. requires `READY`;
3. validates the canonical takeover evidence document;
4. binds evidence exactly to the proposed HANDOFF event;
5. requires provider state and provider proof source to match the independently
   verified provider observation;
6. forbids caller-supplied `verified=true` in publisher input;
7. requires provider input + implicit verified flag to equal the independent
   proof exactly;
8. validates the desired active state;
9. binds desired state to the HANDOFF command, receipt and exact target;
10. produces a `TransitionRequest` only after every binding passes.

The prepared request is deep-copied so later caller mutation cannot change the
request after preparation.

## Explicitly not performed

- no owner event append;
- no evidence write;
- no provider observation write;
- no state CAS;
- no authority grant issuance;
- no source authenticator implementation;
- no Status workflow dispatch;
- no Issue #33 mutation;
- no provider/model execution;
- no real takeover;
- no default-branch direct write.

## Tests added

Coverage includes:

- READY preflight -> publisher request preparation;
- blocked/not-wired preflight propagation;
- evidence/event mismatch;
- evidence/provider state mismatch;
- provider proof source mismatch;
- wrong event evidence ref;
- caller-supplied `verified=true`;
- publisher input vs independent provider proof mismatch;
- desired state command/receipt/target/state mismatch;
- caller mutation after preparation does not mutate the prepared request.

## Remaining production boundary

The next production step still requires concrete independently trustworthy
authority/provider source adapters. This batch deliberately does not invent
those sources or claim GitHub JSON self-assertions are sufficient.

## Exact-head verification

- Exact tested code head:
  `7c35941b472eeda2c91fc038f4ae4863235a14b4`.
- GitHub Actions run:
  `36373149344` — **SUCCESS**.
- Focused Status/runtime/validation suite:
  **182/182 PASS**.
- Full command-bus suite:
  **469/469 PASS**.
- Command-bus JSON schemas parsed:
  **18/18 PASS**.
- Python compileall:
  **PASS**.
- `git diff --check`:
  **PASS**.
- PR #74 was OPEN / mergeable=true at exact-head readback.
- Any commit after this exact tested head must be documentation-only and compared
  before Merge.
