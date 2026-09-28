# Runtime takeover preflight v1 — static checkpoint

## Baseline

- Baseline main: `8de95e41b7c24071df4ef58051e6ff142a016aab`.
- PR #68 (Status workflow dispatch/readback static boundary) is merged.
- PR #69 (verifier source contracts) is merged.
- Issue #33 remains `STOPPED`.
- No real ownership takeover, Status dispatch, provider/model launch, or Issue mutation is performed in this batch.

## Implemented

`runtime_takeover.py` adds a pure static preflight for a proposed
`SEMI_AUTO <-> AUTO` takeover represented as the next append-only
`HANDOFF` owner generation.

The preflight requires all of the following before returning `READY`:

1. complete valid owner chain;
2. latest owner is active, not RELEASE/TERMINAL;
3. durable state is active and bound to the latest owner generation;
4. fresh target exactly matches the latest owner target;
5. current owner receipt is DONE and exactly bound;
6. current owner evidence is present;
7. current historical provider observation is verified and generation/target-bound;
8. current owner lease has expired;
9. proposed event is exactly the next HANDOFF generation and fencing token;
10. previous owner role/holder are bound exactly;
11. takeover switches SEMI_AUTO/AUTO role and holder;
12. takeover claim does not overlap the old lease and is not from the future;
13. proposed source receipt is DONE and exactly bound;
14. explicit verified owner authority matches the proposed takeover event;
15. verified new-owner provider observation matches the new generation, target and evidence;
16. new-owner provider proof is fresh and unexpired.

Lease expiry by itself never authorizes takeover.

## Replay / stale / competing protection

The existing owner-chain validator remains authoritative for:

- monotonic generation;
- fencing token == generation;
- duplicate event rejection;
- reused command/receipt rejection;
- stale/skipped/reordered generation rejection;
- competing ACQUIRE rejection;
- owner change through RENEW rejection;
- exact previous-owner binding for HANDOFF;
- chain continuation after RELEASE/TERMINAL rejection.

The takeover preflight adds explicit checks for stop_requested, stale target,
state binding, expiry boundary, role switch and the authority/provider proofs.

## Static tests

The new tests cover:

- expired SEMI_AUTO -> AUTO READY path;
- expired AUTO -> SEMI_AUTO READY path;
- lease not expired;
- missing authority;
- missing provider verification;
- stale state and target;
- stop_requested / non-active state;
- RELEASE / TERMINAL replay prevention;
- wrong generation/fencing/previous owner;
- same-role takeover rejection;
- target-head rebinding rejection;
- overlapping/future claim;
- current receipt/evidence/provider mismatch;
- proposed receipt/evidence mismatch;
- authority mismatch;
- new-provider mismatch, pre-claim observation and expired proof.

## Explicitly not performed

- no owner event append;
- no authority grant issuance;
- no provider verification source creation;
- no RuntimeTransitionPublisher write;
- no workflow_dispatch;
- no Issue #33 mutation;
- no provider/model/Jules/Claude execution;
- no real SEMI_AUTO/AUTO handoff/takeover;
- no default-branch direct write;
- no Merge in this batch.

## Remaining live boundary

A real takeover still requires a production authority issuer/authenticator,
provider verifier source, durable takeover command/receipt/evidence, and explicit
live authorization. This PR only makes the pre-publication decision fail closed.

## Exact-head verification

- Exact tested code head:
  `8fc5048f6534c3913af040aec0589e3dabee195b`.
- GitHub Actions run:
  `36372083035` — **SUCCESS**.
- Focused Status/runtime/validation suite:
  **173/173 PASS**.
- Full command-bus suite:
  **460/460 PASS**.
- Command-bus JSON schemas parsed:
  **18/18 PASS**.
- Python compileall:
  **PASS**.
- `git diff --check`:
  **PASS**.
- PR #71 was OPEN / mergeable=true at exact-head readback.
- Any commit after this exact tested head must be documentation-only and compared
  before Merge.
