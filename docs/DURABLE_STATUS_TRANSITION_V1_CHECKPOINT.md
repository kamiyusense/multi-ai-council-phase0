# Durable Status transition v1 checkpoint

## Baseline

- PR #53 was merged before this batch.
- Baseline main: `aaef7bf122bd5f2e036bbb81f8ef68fc16d63f31`.
- Issue #33 remained `STOPPED` with zero comments.

## Implemented

- Owner events now require `source_receipt_ref` in addition to `source_receipt_id` so the trusted transition layer can fetch the exact durable receipt without repository-wide guessing.
- The receipt locator is restricted to safe JSON paths under `automation/command_bus/receipts/` or `automation/command_bus/execution_receipts/`.
- The locator is immutable across an owner generation chain, just like receipt id/evidence/target/command/correlation bindings.
- `loop_status_transition.py` statically binds state, complete owner chain, exact receipt locator/readback, target, independently verified evidence refs, canonical provider-observation locator/readback, and current time before Status projection.
- Canonical provider observation locator is deterministic from `<loop_id>/<generation>`.
- Active state only projects SEMI_AUTO/AUTO after `decide_owner` returns VALID; invalid active ownership fails closed to BLOCKED.
- Terminal/non-active state may project IDLE/STOPPED with owner NONE, while malformed/missing readbacks return UNKNOWN with no projection.

## Not yet wired

- No workflow currently gathers/verifies all evidence refs and invokes `loop_status_transition.py` after a real durable state transition.
- Evidence reference existence/authenticity needs a trusted resolver contract before production wiring. The adapter intentionally accepts only an independently verified evidence set.
- No runtime owner event/provider observation was written.
- No AUTO takeover, live Claude/Jules/provider/model execution, or Issue #33 runtime mutation occurred.

## Next safe step

Run exact-head CI. If green, review the remaining evidence-resolver boundary. After that, implement a trusted workflow caller that checks out renderer code from main, reads runtime data strictly as data from an explicit ref, verifies evidence locators, runs the transition adapter, and only then updates Issue #33.
