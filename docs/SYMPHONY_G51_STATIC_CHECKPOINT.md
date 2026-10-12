# G5.1 STATIC — worker lifecycle terminal observation

Outcome: STATIC PASS after the validation below; LIVE count 0. The previous
G5 Local LIVE [Issue #341](SYMPHONY_G5_LOCAL_LIVE_RESULT_ISSUE_341.md) remains
FAIL / STARTED_UNRESOLVED. No historical terminal or completed proof was added.

Fresh starting PR #320 HEAD: `10372c408ac2215c205ac7558af05a79e3f93dfd` (OPEN/Draft).
Fresh starting main: `702497c6b464a3b1ab09441b21fc6f96bd3bb2d0`.
Starting exact-head CI: Symphony `37877554899`, Blue `37877554904`, both SUCCESS.
Final published HEAD, final main and exact-head CI IDs/artifact digests are in
one final G5.1 PR checkpoint comment; a commit cannot include its own SHA.

## Confirmed failure and minimal ownership correction

Pinned Official Symphony `be10a1b79df723d6d7612b5651c8522704dafb2e` actually
performs `reconcile_issue_state -> terminate_running_issue -> stop_running_task
-> Task.Supervisor.terminate_child`, followed by
`Process.demonitor(ref, [:flush])`. It does not depend on AgentRunner returning
and its DOWN can be flushed. #341 exercised this path after two natural
continuations and an independently verified artifact. The old return-only G5
terminal hook therefore could not observe that externally stopped lifetime.

The replacement patch changes only three upstream observation files:

- `agent_runner.ex`: existing runtime-info message gains the optional full
  `g5_worker_run_id` passed in opts. Workspace creation, before/after hooks,
  AppServer work and continuation remain upstream code. No observation key,
  writer PID or file I/O is passed through these opts to model work.
- `orchestrator.ex`: holds the optional observation identity in `running_entry`,
  binds first matching runtime workspace and observes STARTED. A natural DOWN
  observes COMPLETED or FAILED. Existing explicit stop boundaries in
  `terminate_running_issue` and `stop_and_block_issue` observe STOPPED **after**
  the original stop call. Original monitor flushing, removal/claim/retry and
  workspace cleanup remain in their original order.
- `g5_observer.ex`: small opt-in unlinked per-lifetime writer. Parent callback
  sends are asynchronous; only this writer does HMAC/file I/O. First workspace
  binding is immutable. It emits one terminal then exits, or exits on discarded
  failed spawn/owner death. Missing identity/config or write failures produce
  no fabricated event and never retry/block/control Symphony work.

Orchestrator is the sole terminal observation authority; AgentRunner no longer
has competing normal-return emissions. If a normal exit races a chosen explicit
stop, STOPPED is conservative. Identical replay is NOOP_DUPLICATE; conflicting
terminal status/run ID/workspace stays CONFLICT with overwrite 0. The Python
receiver adds WORKER_STOPPED only, retaining create-only UNKNOWN /
RECOVERABLE_UNKNOWN, model_started=null, and no task-success/adoption dispatch.

Official Symphony behavior changes: **NO** to polling, issue choice, worker
selection, continuation conditions/turns, retry count/delay/backoff, stall
threshold/recovery, concurrency, Task.Supervisor semantics and workspace
lifecycle. Extra local observation metadata/writer activity is present; it is
not a second scheduler. Normal continuation retry remains 1,000 ms and the
fixture's attempt-2 failure backoff remains 20,000 ms.

## Regression proof and practical limits

Eight real OTP/ExUnit tests cover the seven requested cases, with five additional
Python receiver/cross-language tests. They use dummy Task.Supervisor children
and invoke the real pinned/patched Orchestrator callbacks. No application,
tracker poll loop, AppServer session or provider/model is started.

1. A routable simulated Issue has two dummy turn completions and two real
   AgentRunner continuation decisions, then becomes Closed. Real
   Task.Supervisor termination and demonitor flush occur, normal upstream
   workspace cleanup occurs, and signed STARTED/WORKER_STOPPED TERMINAL exists.
2. Real natural task exit generates DOWN and WORKER_COMPLETED. Failure DOWN
   generates WORKER_FAILED and retains the original attempt-2 delay.
3. Actual Elixir-produced signed STARTED/STOPPED events pass the Python MAC /
   fake create-only durable ledger. Fresh observer replay returns two
   NOOP_DUPLICATE records, create count unchanged, one attempt and dispatch 0.
4. Natural end, a repeated DOWN and a duplicate terminal notification leave
   exactly one terminal. Running-entry removal and one-shot writer own dedupe.
5. Stale runtime ID/workspace cannot rebind observation metadata (upstream
   runtime handling still proceeds). Wrong full ID with the same derived
   attempt number, wrong workspace or conflicting end status is CONFLICT;
   canonical terminal and write count are unchanged.
6. Missing/nonregular event targets and a suspended writer do not wait for
   acknowledgment. Tracker stop returns within the fixture's 500 ms bound;
   task stopped/state removed/cleanup unchanged. Resume only drains observation
   warnings; no event write and no provider invocation.
7. Baseline/patched callback state agrees in five scenarios: natural completion,
   abnormal failure, tracker terminal, non-active state, active-state capacity.
   Real retry timers are checked and cancelled in the fixture. AST comparison
   ignores location metadata and compares **every function/callback outside
   the named observation seams**, including polling/retry/stall/concurrency/
   continuation functions, against exact git-show pin sources.

These are STATIC fixtures, not a real tracker/provider observation or remote
ledger proof. The cross-language signing key is public fixture-only data.
MAC strings/digests are evidence, not production keys. Full thread/turn identity
binding is not added. A worker stopped before workspace runtime binding, parent
crash, or unavailable observation path can still leave observation missing;
never fabricate one. Normal operator cleanup must wait for actual durable
terminal readback because the writer is deliberately asynchronous.

## Validation and evidence

Clean-pin patch applicability, patched reverse check, Elixir compile with
warnings-as-errors, format and public specs check PASS. The offline validator
uses existing dev dependencies with `mix run --no-start` and ExUnit; it does
not start the Symphony application. A first test-mode invocation hit an
unrelated lazy_html test-only NIF downloader error, so the same ExUnit fixtures
were run successfully in the compiled dev environment, without downloading
that dependency. Full upstream UI/live-e2e/coverage is not claimed.

Focused controller tests: 154 PASS. Full command-bus tests: 1,913 PASS with one
inherited skip. Python compileall, diff check and changed-file secret scan PASS.
The new receiver fixtures are in focused exact-head Symphony CI and the full
regression in Symphony/Blue CI. Final jobs, logs and downloaded artifact digests
are verified at the published head in the PR checkpoint; CI does not execute LIVE.

- [Machine-readable STATIC checkpoint](evidence/symphony-g51-static/checkpoint.json)
- [Evidence manifest and SHA-256](evidence/symphony-g51-static/manifest.json)
- [Repeatable offline validator](../automation/command_bus/scripts/validate_symphony_g51.py)
- [OTP lifecycle/behavior fixtures](../automation/command_bus/tests/fixtures/symphony_g51/worker_lifecycle_test.exs)
- [Receiver/restart/conflict fixtures](../automation/command_bus/tests/test_symphony_g51_worker_lifecycle.py)
- [Fresh next single Local LIVE plan — not executed](SYMPHONY_G51_LOCAL_LIVE_PLAN.md)

No Issue/branch/campaign for a new LIVE was created. No model/provider LIVE,
paid/API fallback, automatic Git adoption, default-branch mutation, merge,
force push, rebase/history rewrite or destructive cleanup occurred. STATIC
readiness is PASS; real Local LIVE readiness must be freshly checked under a
new explicit single-run approval. G6 remains disconnected and unauthorized.
