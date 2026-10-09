# G5 Local LIVE — Issue #341 — FAIL / STARTED_UNRESOLVED

Campaign: `symphony-g5-local-20261009T024653Z-d646fcdc`.
Official Symphony pin: `be10a1b79df723d6d7612b5651c8522704dafb2e`.
Starting PR #320 HEAD: `2f6d2dcc1d9761797a19aad10263a5025ae8300b`.
Starting/final main and proof HEAD: `702497c6b464a3b1ab09441b21fc6f96bd3bb2d0`.

## Observed outcome

The one authorized G5 LIVE was launched exactly once. Official Symphony
selected new [Issue #341](https://github.com/kamiyusense/multi-ai-council-phase0/issues/341), created the isolated workspace and launched one real Codex
App Server session with ChatGPT login. The observed model was `gpt-6.1-sol`
with existing `high` reasoning. No model/configuration setting was changed.
There were three model turn starts, two normal completed turns and two
upstream-owned same-thread continuations. The third turn was interrupted by
upstream terminal-state reconciliation, not an operator model retry.

The signed STARTED passed MAC validation and durable INTENT/STARTED readback.
Worker run ID: `3a2b4fc6e701a86ca26df0b415e13b86`.
Attempt ID: `attempt-1fdd3890e399898ee905068f55b87e72`.
No real TERMINAL event or durable TERMINAL record exists (exact path 404).
The attempt remains STARTED_UNRESOLVED. Full G5 outcome is FAIL.

## Artifact and authorized Issue closure

The worker created and then verified only
`docs/evidence/symphony-g5-observation-proof/symphony-g5-local-20261009T024653Z-d646fcdc.md`.
Operator readback checked its content, unchanged branch/starting/ending HEAD,
full untracked status, zero tracked/staged changes, ordinary diff check and
new-file whitespace directly. Artifact SHA-256 before close:
`cbb3f12020870f0043b63ed522b5bd4281fc7114bcc5d4d0a31d4d568a650a8d`.

After those checks the operator closed #341 with state_reason=completed and
read it back as CLOSED. Issue closure records artifact completion; it does
not assert the G5 observation proof passed. The worker did not close the Issue.
G4 Issue #336 remained OPEN and was not reused or modified.

At `2026-10-09T02:53:18.569607Z`, the unmodified official orchestrator saw the
closed Issue during its periodic reconciliation, stopped the active agent and
removed its workspace through its existing workspace lifecycle. The model
rollout independently records turn 3 as interrupted at `02:53:18.609Z`.
The G5 hook executes after `run_codex_turns` returns; upstream task termination
did not pass through that return hook. Closing during an active continuation
therefore races the ordinary worker completion check. No terminal was invented.

Verified artifact content was preserved inside operator readback evidence
before normal upstream removal. It is not installed at its task path in
PR #320/main, and no development result was automatically adopted.

## Partial observer restart evidence

Symphony, captured App Server PID 565693 and the observer stopped; port 4000
was closed. The observer alone restarted once against the same event file.
It returned `NOOP_DUPLICATE started`; ledger HEAD before/after was
`dcbd16be97e9279911ff37611608f509fef852b6`. Event SHA-256 before/after:
`99b528c4d986df64957f319cd2475e595550e987bebbe72fcc5d39f80bff82ed`.
New workers/model dispatches during replay: zero. No TERMINAL duplicate
replay was possible, so the full restart proof remains unfulfilled.

## Safety and exact evidence

- Proof branch: `codex/symphony-g5-local-20261009T024653Z-d646fcdc`; unchanged
  at the fresh current main used to create it, separate from PR #320/G4.
- Ledger: `codex/symphony-g5-proof-ledger`; create-only INTENT and STARTED
  only. No overwrite, dispatch authorization or Git adoption from observer.
- MAC key: 32 random bytes; Linux parent directory 0700, key/event file 0600,
  outside the model workspace; no key value in GitHub/logs/child evidence.
- Actual child inspection: all nine forbidden observer/token/API selector
  names absent; parent Codex login ChatGPT, no API selector/custom provider.
  Unavailable quota telemetry was not classified as exhaustion.
- Main mutation, paid/API fallback, Git automatic adoption and verified
  unauthorized worker file changes: zero. No force push, rebase, reset, clean,
  merge, second G5 launch, G4 replay or other-provider LIVE.
- Retry/backoff/stall/stall recovery: each NOT_OBSERVED.
- Upstream content changes were exactly the approved observation patch;
  Windows-mount execution-bit differences were excluded with Git's
  core.filemode=false command option. Original Linux upstream remained clean.
- [Machine checkpoint](evidence/symphony-g5-local-live/issue-341/checkpoint.json),
  [evidence digests](evidence/symphony-g5-local-live/issue-341/manifest.json),
  [model lifecycle](evidence/symphony-g5-local-live/issue-341/model-lifecycle.json),
  [signed event](evidence/symphony-g5-local-live/issue-341/signed-events.jsonl),
  [durable readback](evidence/symphony-g5-local-live/issue-341/started-durable-readback.json),
  [workspace verification](evidence/symphony-g5-local-live/issue-341/workspace-verification-before-close.json),
  [restart evidence](evidence/symphony-g5-local-live/issue-341/observer-restart.json),
  [cleanup/readback](evidence/symphony-g5-local-live/issue-341/cleanup-readback.json).

## Validation and remaining boundary

Post-evidence STATIC validation: focused Symphony 149 PASS; full command-bus
1,908 tests PASS with one inherited skip; compileall, clean-pin patch check,
diff check and changed-evidence secret scan PASS. Local validation logs and
[STATIC record](evidence/symphony-g5-local-live/issue-341/static-validation.json)
are preserved. Final exact-head CI is recorded in the single final PR #320
checkpoint comment. CI confirms the static tree;
it cannot turn this missing real TERMINAL into LIVE PASS. No production
observer or scheduler code was changed after this run; the runbook now
documents the actual close/termination race. No second LIVE was executed.

G6 remains disconnected: durable result, fresh canonical HEAD/task validity
and mutation-class validation, then separately authorized safe Git result
adoption. This G5 run also leaves the real terminal/replay boundary unproven.
