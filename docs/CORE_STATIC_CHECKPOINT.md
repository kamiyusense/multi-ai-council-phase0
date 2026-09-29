# Phase 0 Core Static Checkpoint

Checkpoint date: 2026-09-21
Scope: Relay-independent static/mock Core only
Base Git checkpoint: `9ae950997941070e9b07e9dca764049b2052cb64`

## Verification performed before GitHub update

Commands:

```text
PYTHONPATH=src python -m compileall -q src tests
PYTHONPATH=src python -m unittest discover -s tests -v
```

Result:

- compileall: PASS
- expanded local unit / fixture / regression / static-policy suite: 62 PASS, 0 FAIL
- exact new full-pipeline + static-policy files intended for this commit: 16 PASS, 0 FAIL
- live provider turn: NO
- API-key route used: NO
- paid route used: NO
- permission bypass used: NO
- automatic retry added/executed: NO
- model fallback added/executed: NO

## Full mock run readback

A three-provider mock run completed through:

```text
input
-> fail-closed fan-out PASS
-> isolated provider snapshots
-> mock dispatch/collect
-> RAW persistence before validation
-> Provider Response validation
-> provider-local manifest/state/fs diff
-> deterministic comparison
-> Japanese report
-> checkpoint
```

Observed comparison:

- participant_count: 3
- agreement_count: 3
- conclusion_match_state: EXACT
- evidence_match_state: EXACT
- safety_block: false
- formal_consensus: false
- human_required: true

Selected generated evidence SHA-256 values:

- `comparison/differences.json`: `61699d9623e579792fa4dfe64499d0ddc88e3a64b689c917ddb8cbb3dc84a0b0`
- `comparison/parsed.json`: `5b9ef44cb4941d9dcdc2123fcb15ebea72f38bbf58fd9ed20ea6f7b7ce193627`
- `comparison/summary_ja.md`: `0ec0856c447de8490412d6d99ffc3f5e84a495f719d706ebbb97bb7de25a2523`
- `evidence/checkpoint.json`: `361d5c6843fbc3cedd8976b0b12dc22eb89c8b9312bad81863140a16ab52cba6`
- provider fixture `response.raw`: `dcee48ed45f63f16a3640b4cb68ae389448533441a94207a831cbcbb434d19ae`

The generated run directory itself is intentionally not committed because `phase0-runs/`-style evidence is sensitive/local by policy.

## PASS

- three-provider mock E2E path
- RAW-before-parse behavior
- malformed JSON -> INVALID_OUTPUT with RAW retained
- missing/unknown response fields -> INVALID_OUTPUT
- one-provider failure isolation
- TIMEOUT classified distinctly without retry
- checkpoint records provider PASS / FAIL / UNKNOWN separately
- failure -> no automatic retry
- no fallback path
- fan-out UNKNOWN -> no provider snapshot / no dispatch
- safety UNKNOWN -> human-required safety block
- 2/3 agreement -> not formal Council consensus
- known secret masking in user-facing error report
- workspace escape rejection
- symlink rejection
- static Core contains no provider API-key env route, provider process/network runtime import, or permission-bypass flag

## UNKNOWN / deferred before live

- actual timeout per provider
- minimum provider permission profile
- subscription-auth verification method
- executed-model verification method
- provider network restriction feasibility
- final secret/PII/private-code detection rules
- final marker completeness policy
- agy / Antigravity transport choice
- Relay/provider real process and backend evidence semantics

These UNKNOWN items block future live execution where safety-relevant; they do not invalidate this static/mock checkpoint.
