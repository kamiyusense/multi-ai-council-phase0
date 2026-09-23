# Dual Browser Transport Checkpoint

Updated: 2026-09-23
Repository: `kamiyusense/multi-ai-council-phase0`
Carrier: PR #6 / `feature/chat-work-command-bus`
Target: PR #4 / `feature/relay-transport-7070955470193506982`

Status: **STATIC IMPLEMENTED / LIVE PREFLIGHT PENDING**

## Scope completed

Implemented the static dual-browser Jules UI transport contract:
- one command binds one transport only;
- successor transport requires a fresh command/correlation/generation/expiry;
- predecessor terminal receipt/evidence proof is mandatory;
- task/model/GitHub/external-action uncertainty forbids redispatch;
- stale generation/wrong transport results are rejected;
- duplicate/terminal replay is NO-OP;
- sensitive authentication material is rejected from evidence;
- retry remains 0 and fallback remains disabled.

Implementation:
- `automation/command_bus/browser_transport.py`
- `automation/command_bus/tests/test_browser_transport.py`
- `automation/command_bus/schema/browser_transport_evidence.schema.json`
- `docs/WORK_COMMAND_BUS_RUNTIME_CONTRACT.md`
- `docs/TRANSPORT_FALLBACK_PROPOSAL.md`

## Capability state

Cloud Browser:
- actual prior durable evidence shows the Jules UI was opened through
  `WORK_CLOUD_BROWSER_JULES_UI`;
- that preflight stopped at Google account selection;
- task/model start remained false.

Computer Use / second browser:
- static protocol adapter implemented as `WORK_COMPUTER_USE_JULES_UI`;
- actual Work runtime capability: **UNKNOWN** in this batch;
- no live access was attempted.

## Live boundaries

- live browser executed in this implementation batch: NO
- Google login performed: NO
- Jules task submitted: NO
- Jules/model started: NO
- PR #4 mutation: NO
- PR #8 mutation: NO
- Merge/cherry-pick/rebase: NO

## Validation

New dual-browser unit/regression suite:
- 22 tests PASS in isolated local static validation before GitHub write.

Required full command-bus suite after remote write:
- must be independently validated against the exact resulting PR #6 head;
- until that exact-head validation is obtained, full-suite status is UNKNOWN.

## Blocker

`WORK_COMPUTER_USE_JULES_UI` actual runtime availability is UNKNOWN.
This does not block the static architecture/tests.

## Next safe action

Run exact-current-head deterministic command-bus validation. After that, a
separate fresh live preflight may be designed only under the current durable
runtime contract; it must not reuse any prior browser/Jules command.
