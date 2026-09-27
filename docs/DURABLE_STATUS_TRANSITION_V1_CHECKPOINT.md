# Durable Status transition v1 checkpoint

## Baseline

- PR #53 was merged before this batch.
- Baseline main: `aaef7bf122bd5f2e036bbb81f8ef68fc16d63f31`.
- Issue #33 remained `STOPPED` with zero comments.

## Implemented

- Owner events include an explicit `source_receipt_ref`; transition code never guesses a receipt path.
- Source receipts are restricted to `automation/command_bus/receipts/<loop_id>/<file>.json` and must belong to the same loop.
- Evidence refs are restricted to `automation/command_bus/evidence/<loop_id>/<file>.json` and must belong to the same loop.
- `loop_status_evidence.py` derives the verified evidence set from exact non-empty readbacks rather than caller declaration.
- Owner chain invariants are `loop_id`, target repository, and target PR. Target head, command/correlation, lease, source receipt, and evidence are generation-specific.
- Each generation has a unique command id and source receipt identity/path, preventing proof replay across generations.
- State `last_command_id` and `last_receipt_id` must bind the latest owner generation.
- Active ACQUIRE/RENEW/HANDOFF requires a fresh canonical provider observation for the same generation/fencing/target.
- RELEASE requires a DONE source receipt. TERMINAL binds `terminal_receipt_id` to that generation's source receipt and can close after a validator-approved terminal receipt.
- RELEASE/TERMINAL proof is verified before owner closure; active provider observation is not required after a verified close.
- A non-active state with an unclosed active owner generation is forced to BLOCKED instead of being shown as IDLE.
- `loop_status_transition.py` remains a pure adapter: no network call and no Issue write.

## Exact-head verification

- Exact tested code head: `bb26a8c6c3b6ad2e6d644e015c97745add1605e1`.
- GitHub Actions run: `36334359988` — SUCCESS.
- Focused Status/owner/writer/observation/evidence/transition/scope tests: **80/80 PASS**.
- Full command-bus suite: **367 tests run**.
- Exactly one known pre-existing error remained: `automation.command_bus.tests.test_jules_api_request.JulesApiRequestTests.test_prompt_binds_head_tree_and_allowlist`.
- The CI guard rejects any additional failure or any failure outside that exact known fixture.
- Python compileall: **PASS**.
- `git diff --check`: **PASS**.
- Changes after the exact tested code head are documentation-only.

## Still not connected

- No production workflow currently gathers these readbacks after a real state transition and updates Issue #33 from the transition result.
- No live provider-observation writer is connected.
- No runtime owner event/provider observation was created in this batch.
- AUTO takeover remains disabled.
- Issue #33 therefore remains `STOPPED` until the production caller is separately implemented and reviewed.

## Next safe step

After this PR is reviewed and merged, add a trusted workflow caller that uses code from deployed main, reads runtime records strictly as data from an explicit ref, performs exact readbacks, runs the transition adapter, and only then updates Issue #33. Keep takeover disabled until that route has mock/end-to-end coverage.
