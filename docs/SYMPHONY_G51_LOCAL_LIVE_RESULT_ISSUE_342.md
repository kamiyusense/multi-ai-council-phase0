# G5.1 Local LIVE — Issue #342: PASS

One newly authorized Official Symphony process produced a real worker lifetime,
one Codex App Server session, two model turn starts, one completed turn and one
natural same-thread continuation. The operator verified the approved artifact,
closed Issue #342, and the official tracker reconciliation stopped active turn 2.
The Orchestrator emitted a real signed **WORKER_STOPPED** TERMINAL, matching the
STARTED worker/workspace. Both records were independently read back from the
create-only non-default durable ledger. The ledger remains
**UNKNOWN / RECOVERABLE_UNKNOWN**: worker end does not mean task/Git adoption.

## Fresh binding and actual sequence

- Starting PR #320 HEAD: `d567ea71c89ce44f6db442fa37f4f4ce3a9cc32c`; OPEN / Draft.
- Main / proof starting and ending HEAD: `702497c6b464a3b1ab09441b21fc6f96bd3bb2d0` (unchanged).
- Official pin: `be10a1b79df723d6d7612b5651c8522704dafb2e`; observation-only patch SHA-256:
  `404b4001d279351c8b800816142862ee47dfd209615b0f9211fbe6ccc5170f3b`. Clean-pin apply check, patch, reverse check, format/build PASS.
- Campaign: `symphony-g51-local-20261009T225229Z-41fddcf6`; task `issue-342`, generation/runner generation 1.
- Proof Issue: [#342](https://github.com/kamiyusense/multi-ai-council-phase0/issues/342),
  newly created once, required label read back, operator CLOSED at `2026-10-09T23:00:42Z`.
- Dedicated proof branch: `codex/symphony-g51-local-20261009T225229Z-41fddcf6`; separate from main/#320/G4/ledger.
- Ledger branch: `codex/symphony-g5-proof-ledger`;
  `dcbd16be97e9279911ff37611608f509fef852b6` → `1e7333caf91c556a48f423a802c48678962e1cbc`.
  All historical blob identities preserved; this campaign added only INTENT,
  STARTED and TERMINAL. INTENT does not authorize dispatch.
- Worker lifetime: `b8f1a7db6c6358a76555365062d8a776`; durable attempt `attempt-14219f5ac8d71a5ea86ceecfe24f4f02`.
- Workspace fingerprint: `347d3be319dd7ce9b2d0e1ed972428fee6469052b66f3c1b053b15caa1384f38`.
- Observer readiness preceded sole LIVE launch; STARTED/TERMINAL MAC verification PASS.
- Official log: `Issue moved to terminal state: issue_id=342 issue_identifier=GH-342
  state=closed; stopping active agent`. No synthetic terminal or operator worker kill.
- Actual model counts: starts 2, completed 1, interrupted 1; continuation 1.
  Artifact self-report describes turn 1 only; later continuation is proved by
  operator-side session lifecycle and official logs. Retry/backoff/stall: NOT_OBSERVED.

## Artifact verification and restart

Only `docs/evidence/symphony-g5-observation-proof/symphony-g51-local-20261009T225229Z-41fddcf6.md` was permitted and present as an untracked file.
Artifact SHA-256: `23103a65dd4320fbd2d67ca470713175a8f3396dc90f7f4b6da3a0a2ec33faf7`. Independent operator readback:
correct branch, starting/ending HEAD unchanged, tracked/staged diff empty, one
untracked approved artifact, diff/whitespace checks PASS, unauthorized mutations 0.
Its content is preserved inside verification evidence only, not adopted at the
worker's task path into PR #320 or main. Official terminal reconciliation later
removed the model workspace through its normal cleanup; operator deletion 0.

After durable TERMINAL, only the observer sidecar was stopped/restarted once.
Replaying the same two real signed events yielded STARTED and TERMINAL
`NOOP_DUPLICATE`. Ledger HEAD/event SHA unchanged; new worker/model dispatch 0;
overwrite/conflict 0. Official Symphony was not relaunched. Only after this
readback were campaign processes stopped normally. Proof App Server ended through
official tracker stop, port 4000 closed, observer stopped; unrelated desktop
App Server preserved. Issue/proof/main/ledger/#320 refs independently read back.

## Safety and validation

ChatGPT subscription login PASS; API/base-URL selectors absent, no custom/paid
provider fallback. Actual proof child selector inspection found all nine excluded
observer/token/API selector names absent. No secret values were logged or saved.
Quota telemetry UNKNOWN was not interpreted as EXHAUSTED. Existing model/effort
settings remained unchanged. Paid/API fallback, automatic Git adoption, main
mutation, unauthorized worker mutation and G6 execution are all 0. No merge,
force/rebase/reset/clean/branch deletion or login/Billing/Secrets changes.

No polling, scheduling, selection, retry/backoff, continuation, stall recovery,
concurrency, workspace cleanup or Task.Supervisor termination changes were made.
The already-validated G5.1 patch succeeded without a new implementation change.
Post-LIVE STATIC: focused 154 tests PASS; full command bus 1,913 tests PASS
(existing skip 1); no-start OTP fixtures 8 PASS; compileall, Elixir
format/compile/specs, patch/reverse checks PASS. Final diff/secret scan and
exact-head Symphony/Blue CI are recorded in the final PR checkpoint.
The dummy OTP fixtures are STATIC and do not consume another model launch.

[Evidence checkpoint](evidence/symphony-g51-local-live/issue-342/checkpoint.json),
[manifest](evidence/symphony-g51-local-live/issue-342/manifest.json) and
[artifact verification](evidence/symphony-g51-local-live/issue-342/workspace-verification-before-close.json)
retain the measured evidence and hashes. Final commit SHA/CI artifact digests are
published in the single final PR checkpoint to avoid a self-referential commit.
Historical [G5 #341 FAIL](SYMPHONY_G5_LOCAL_LIVE_RESULT_ISSUE_341.md) is unchanged.

G5.1 proof PASS is not a task-success/adoption assertion. G6 still requires fresh
canonical HEAD validation and separately authorized safe result adoption; no
G6 LIVE or second G5.1 LIVE was performed.
