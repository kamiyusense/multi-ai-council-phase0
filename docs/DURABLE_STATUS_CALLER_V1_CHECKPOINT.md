# Durable Status caller v1 checkpoint

## Baseline

- PR #55 was merged before this batch.
- Baseline main: `682d34334a864732c75c4cbe8446758d684ebe1b`.
- Issue #33 remained `STOPPED` with zero comments.
- No existing repository workflow caller was found for `.github/workflows/loop-status-signal.yml`.

## Implemented

- Existing `loop-status-signal.yml` is converted from caller-supplied display data to durable-record readback.
- Caller inputs are limited to `loop_id` and explicit `state_ref` data ref.
- Workflow code is always checked out from trusted `main` with persisted checkout credentials disabled.
- State and complete owner chain are fetched first; owner generations are bounded to 100.
- `loop_status_transition_cli.py plan` validates the chain before producing exact receipt/evidence/provider-observation locators.
- Per-generation evidence fanout is bounded to 32 refs in protocol code and JSON schema.
- Receipt/evidence/observation are fetched only from the exact validated locators at the explicit data ref.
- Target repository must equal the current repository; current target PR head is fresh-read from the Pull Request API.
- `loop_status_transition_cli.py render` runs deterministic transition validation and returns nonzero on UNKNOWN before any Issue mutation.
- Issue #33 retains the existing pre-write conflict check, exact readback, retry=0 and terminal-notification dedupe.
- Notification event identity comes from durable state, not workflow input.
- No model/provider/Jules/Claude/Work dispatch exists in this workflow.

## Safety

- This branch does not create owner events or provider observations.
- This branch does not run the Status workflow.
- Issue #33 was not modified by this implementation work.
- AUTO takeover remains disabled and is not implemented by the Status workflow.
- No default-branch direct write, force push, branch deletion, billing/settings/permissions mutation or credential storage occurred.
- Merge is not performed in this batch.

## Verification target

Exact-head GitHub Actions must prove:
- focused Status/owner/writer/observation/evidence/transition/CLI/scope tests PASS;
- full command-bus suite has no failures beyond the exact known expired Jules fixture;
- compileall PASS;
- git diff --check PASS.

After exact-head verification, record the tested code head, workflow run, counts and any documentation-only commits after it.
