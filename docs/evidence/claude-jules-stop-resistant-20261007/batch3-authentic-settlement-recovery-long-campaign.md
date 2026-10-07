# Batch 3 (2026-10-07, STATIC): authentic settlement, reasoned recovery, long campaign

STATIC only. No LIVE Claude/provider/model turn, no Jules dispatch, no Jules status
GET, no Routine, no merge, no owner/budget change. Simulated counters in test
output are fakes.

## Starting state (fresh GitHub readback, 2026-10-07 ~09:20Z)

main `4007f0c`, branch head `c05c87f` (tree `5f5712d`), data branch `5227589`,
live target `53f2caf`, Loop A budget 6/10, owner a-003 generation 2 SEMI_AUTO.
Open Drafts #329, #328, #327, #326, #325, #324, #323, #321, #320; Jules PR #322
open (UNKNOWN, unadopted). Nothing had moved since batch 2.

## Goal and where this batch stands

Product goal: GitHub durable state is the source of truth; Claude controls, Jules
executes, results are inspected, adopted, corrected or replanned over many rounds
and tasks; it stops only at COMPLETE, a legitimate WAIT, an authority boundary or
a real unsafe boundary.

| Part | Status after batch 3 |
| --- | --- |
| Restore campaign/task/owner/budget/evidence from GitHub | STATIC proven (every wake is a fresh controller) |
| READY/dependency/blocker scheduling | STATIC proven (20-task run, blocked dependency) |
| Distinct intent, one dispatch, receipts, budget slots | STATIC proven; LIVE proven once (Loops 128-131, 137, 139) |
| Result by event or poll, duplicates, inversion | STATIC proven (batch 2, long run) |
| Exact-head inspection, append-only reinspection | STATIC proven |
| Corrective / stale replan / isolation | STATIC proven; no-progress detection new (opt-in) |
| Provider settlement from authentic evidence | STATIC proven against real log format; **LIVE unproven** |
| Reasoned bounded recovery with durable decisions | STATIC proven (opt-in policy v1) |
| Real two-controller race | STATIC proven with a two-thread barrier on the fake's CAS; **GitHub-level LIVE unproven** |
| Routine wake in production | designed, **not connected** |
| Long unattended LIVE campaign | **not run**; Loop A has 4 LIVE slots left |

## 1. Settlement authenticity hole: fixed

Problem (reproduced in the handover): a record claiming `COMPLETED` with a
matching digest was accepted while the readback job's real log said
`IN_PROGRESS`; the verifier never read the log. A digest proves the record was
not changed after writing, not where its content came from.

Also found while fixing: the real workflow prints
`Jules session readback: name=sessions/<id> state=<S> accepted_at_jst=<t> pr_url=<u>`;
the batch-2 pattern lacked `accepted_at_jst`, so real lines would never have
matched. And the same log carries Jules-authored text (`Jules latest agent
message JSON: ...`), which could contain a fake readback line.

`verify_readback` (replaces `verify_readback_run`) now:

* binds request path (added exactly once by the recorded commit), request
  content (session; command when present), the single push run of
  `jules-session-readback.yml` for that commit (`head_sha`, `run_attempt == 1`,
  completed/success), its single job (`run_attempt == 1`, success, REST times);
* reads the job log itself and extracts genuine readback lines: only lines that
  *start* with the prefix after the timestamp count (the script echo and the
  agent-message line do not); a prefixed line of another shape, zero lines or
  several lines are contradictions;
* requires the recorded line/state to equal the log's;
* orders readbacks by the job's REST `completed_at`, never by `observed_at`;
  ignores jobs that started before the dispatch; a record written before its own
  job completed is a contradiction;
* raises `ReadbackUnavailable` for read failures (classified TRANSIENT, bounded
  re-read) and `ReadbackMismatch` for disagreements (HARD, never retried).

Accepted-session path: `dispatch_observation` keeps working as before but now
tags `session_source` (`JOB_LOG` or `RECORDED_TRANSCRIPTION`).
`provider_settlement` refuses to bind a settlement to a transcribed session
(UNKNOWN → WAIT). Consequence: a settlement check must run where Actions job
logs are readable (the user's PC or an Actions job); this cloud container gets
403 on the log blob host.

Negative tests (`test_claude_jules_settlement.py`, 32 tests): valid digest but
log says IN_PROGRESS (log read once, UNKNOWN); run success with provider
IN_PROGRESS (RUNNING); log without the session; another session's terminal
line; another job/run/request/command/commit/attempt; re-run job; failed job;
missing job times; log read failure or empty log; several or conflicting lines;
script echo and agent-message spoof; old job with a new transcription time;
record written before its job finished; unsettled after settled; transcribed
accepted session.

## 2. Reasoned bounded recovery (explicit opt-in, `claude_jules_recovery_policy.py`)

Legacy default unchanged (immediate bounded read retry via
`max_transient_retries`). Passing `recovery_policy=` to `ClaudeJulesAutoLoop`
enables v1. Each decision is written as a create-only `RECOVERY_DECISION`
campaign event **before** the retry it allows.

| Cause | Operations | Attempts | Backoff | Deadline | Must change | Provider cost | Exhausted → |
| --- | --- | --- | --- | --- | --- | --- | --- |
| TRANSIENT_READ | GitHub/Actions/log/evidence reads | 3 | 0 s, 120 s, 600 s | 1 h | time only | 0 | isolate task |
| TEST_ENVIRONMENT | Claude's test run | 2 | 0, 0 | 6 h | environment digest | 0 | isolate task |
| SEMANTIC_FAILURE | Jules corrective | campaign value (2 default) | 0 | 24 h | finding fingerprint (same once → reduce scope) | 1 each | isolate task |
| STALE_TARGET | replan | 3 | 0 | 24 h | canonical head | 1 each | isolate task |
| PROVIDER_FAILURE | new distinct attempt | 1 | 0 | 24 h | attempt plan | 1 | isolate task |
| AMBIGUOUS_WRITE | create after proven absence | 1 | 0 | 1 h | absence proof (`True` only) | 0 | stop campaign |
| TASK_BLOCKER | none | 0 | | | | | isolate task |
| AUTHORITY / BUDGET / INTEGRITY | none | 0 | | | | | stop campaign |

Why these caps: see the module docstring (three spaced reads cover a short
GitHub outage without turning a real outage into polling; a test re-run needs an
environment change; a target moving more than three times is a coordination
problem; an ambiguous write is resent at most once and only after readback
proved it absent). Caps are validated (1..10 attempts, finite deadlines,
never-retryable causes cannot be made retryable).

Each record keeps: cause, operation, reason, evidence ref, why the retry is
meaningful, conditions and their digest, failure fingerprint (volatile ids
removed), decision, `not_before`, deadline, provider budget effect, reduced
scope flag, policy profile. Restart restores attempts and backoff from these
records; a second record for the same attempt (two controllers) is a
contradiction (STOP, do not resend). No-progress: the same fingerprint with
unchanged conditions is refused; for correctives it first shrinks scope, then
isolates.

## 3. Long campaign and fault injection

`test_claude_jules_long_campaign.py`: 20 tasks, max 30 rounds, every wake is a
fresh controller. The expected outcome per task is fixed in the module
docstring before the run; the run matched it: 23 simulated dispatches, 17 tasks
adopted, blocked = {long-10, long-17}, end at the real dependency boundary
(long-11 depends on long-10). Faults: semantic failure then corrective, read
outage, missing test evidence (append-only reinspection), provider RUNNING then
verified SETTLED (WAIT, then isolate), stale target after PASS (replan; the
parallel writer's file survives), duplicate and late deliveries, identical
finding three times (no-progress isolation before the legacy budget), lost
response after a receipt write. One budget slot per command, contiguous; a
final duplicate wake writes nothing. Round limit (10) and campaign provider
budget (12) end the run as real stops, not success.

Production cap vs. scheduler: the run uses a test-only gate
(`claude_jules_static_simulator.py`, requires `scope=static-simulation-only`)
because the production gate caps real dispatches at 10. A test proves the
fixed 10-slot ledger is back after the simulator and that the simulator
refuses a real authorization.

`test_claude_jules_true_concurrency.py`: two threads, each held at its first
mutating GitHub call until the other has read the same snapshot. Racing first
dispatch → one carrier command, one budget slot; racing adoption → one
fast-forward; racing waits → no writes. Repeated 5x per case. This proves the
engine relies only on create-only/CAS primitives; GitHub's own atomicity under
load stays a LIVE question.

## 4. #324 and #329

* #324 (`claude/live-tests-use-sys-executable`, head `f005dbc`) = 1 code line
  (`DEFAULT_TEST_COMMAND` uses `sys.executable`) + two files under
  `docs/evidence/claude-jules-autoloop-20261001/live-proof-3-2026-10-06/`.
  Those two files are byte-identical to #321 (blobs `b2e9e4b`, `e8062c2`).
* The code line is now ported into #329 (commit `6c83fd8`) with a test.
* Suggested order: merge nothing from #324 separately. Close #324 as
  superseded by #329 once #329 is accepted; keep #321 as the single home of the
  old policy/roadmap evidence (an old LIVE policy is history, not a new
  approval). The decision is the user's.

## 5. Approval-ready proposals (prepared, not executed)

### 5.1 Merge candidate
#329 → main, Draft, base `4007f0c`. Exact head and CI are recorded in the PR
body after this batch's exact-head validation. No conflict with main at batch
start (main unchanged). Order: #329 first. #326/#327/#328 carry campaign-policy, transient-recovery
and task-isolation work under similar names; their heads are not ancestors of
#329 (14 / 19 / 22 commits outside #329's history; content may have been
re-applied differently), so containment is UNKNOWN and needs a content diff
before closing any of them. #325's North Star/handover docs were imported into #329 in batch 1.

### 5.2 First provider read-only trial (one GET)
* Session `12043323850985900453` (Loop 139, command
  `relay-dev-loop-139-live-proof-3-note`, dispatch run 37417380878 job
  112118884171).
* Request (prepared by `prepare_status_request`, not written):
  `automation/command_bus/jules_api_status_requests/settle-dfcd5c4061f53c45-a1.json`
  with `{"command_id": ..., "include_activities": false, "purpose": ..., "session_id": ...}`
  on `feature/chat-work-command-bus`, one added file per commit.
* HTTP: exactly one `GET https://jules.googleapis.com/v1alpha/sessions/12043323850985900453`
  (activities GET skipped by `include_activities: false`; the default would add a
  second GET). No Loop A slot is consumed (read-only), but it is a provider call
  and needs the user's explicit approval.
* Afterwards, from a place that can read job logs: record the line with
  `record-settlement`, then `provider_settlement` must verify it against the log.
* Outcomes: COMPLETED/FAILED → SETTLED evidence; QUEUED..PAUSED → RUNNING;
  other → UNKNOWN; workflow failure → no record, the request is never re-added
  (attempt 2 is a new file only after backoff, max 3).

### 5.3 Routine/wake production connection
Unchanged design from `docs/CLAUDE_JULES_ROUTINE_WAKE_V1.md`: trigger
`pull_request.opened`, base starts with `jules-work/`; prompt runs only
read-only `poll`/`wake-resume`; inbox records are create-only and keyed by
PR+head so duplicate Routine runs write nothing (proven STATIC); concurrent runs
race on create-only/CAS (proven STATIC); no dispatch/adoption authority from the
wake; stop by disabling the Routine; observation = Routine history + inbox
records. Needs: the user creates/edits the Routine; the test Routine
"PR起動テスト" should be turned off first.

### 5.4 Long LIVE proof (staged)
Loop A has 4 LIVE slots left (6/10). Stages need a new budget authorization:
S = 2 independent tiny tasks, ≤3 dispatches, 2 h; M = 4 tasks incl. one
dependency, ≤6 dispatches, 6 h; L = 8 tasks, ≤12 dispatches, 24 h. Each stage:
recovery policy v1 on, one provider at a time, wake by Routine plus a fallback
poll, one planned restart, settlement via 5.2. Done means every task ends
ADOPTED or TASK_BLOCKED with evidence, no duplicate dispatch, budget slots ==
commands, no human "continue".

## 6. Requirement → test map (new in this batch)

| Requirement | Test |
| --- | --- |
| Forged state with valid digest | `VerifyReadbackTests.test_valid_digest_but_log_says_in_progress` |
| Run success ≠ provider done | `test_run_success_with_provider_in_progress_is_running_not_settled` |
| Session missing / other session | `test_log_without_the_target_session_or_with_another_session` |
| Other job/run/request/attempt | `test_each_identity_binding_is_required` |
| Log read failure | `test_log_read_failure_is_unavailable_not_settled` |
| Conflicting states | `test_several_or_malformed_readback_lines_are_contradictions` |
| Old evidence, new transcription time | `test_order_comes_from_job_times_not_from_observed_at`, `test_old_job_with_a_fresh_transcription_time_proves_nothing` |
| Unrelated log lines / echo | `test_script_echo_and_agent_message_are_not_readbacks` |
| Transcribed accepted session | `test_transcribed_accepted_session_never_binds_a_settlement` |
| Bounded backoff across restart | `test_read_outage_backs_off_durably_across_restarts_then_isolates` |
| Meaningless repeat | `test_identical_finding_shrinks_scope_then_isolates_before_the_legacy_budget`, `test_test_rerun_needs_a_changed_environment` |
| Ambiguous write | `test_ambiguous_write_reconciles_first_and_retries_once_after_proven_absence` |
| Real race | `test_racing_first_dispatch_creates_one_command_and_one_slot`, `test_racing_adoption_fast_forwards_once` |
| Long campaign | `test_twenty_task_campaign_converges_to_the_predefined_outcome` |

## 7. Remaining

Implementation gaps (STATIC, can still be built): settlement record producer
run inside an Actions job (so job logs are readable without the PC); wiring
TEST_ENVIRONMENT and PROVIDER_FAILURE causes into the controller (table and
tests exist, the controller uses TRANSIENT_READ, STALE_TARGET and
SEMANTIC_FAILURE today); a read-only CLI to print a campaign's recovery history.

LIVE-unproven: any real settlement readback; Routine firing on a real Jules PR
plus concurrency; GitHub-side atomicity under a real race; an unattended
multi-round campaign.
