# Batch 17 (2026-10-09 JST): Production Starter v2, autonomous planner loop, stop taxonomy

No LIVE run: no label, no Jules task, no Routine or trigger change, no change to #338. Slot 10 is unused.
No Merge, no default-branch write, no force push. Nothing touched an API key, Billing or settings.

## 1. Fresh readback (start of batch)

| Item | Value |
|---|---|
| main | `702497c6b464a3b1ab09441b21fc6f96bd3bb2d0` (#339 merged) |
| PR #340 | Draft, OPEN, MERGEABLE, head `aabe1b6`, CI `offline-validation` pass, 17 files |
| #338 | OPEN, no label, unchanged since 2026-10-08T18:04:22Z |
| ledger | 9 slots (`slot-01`…`slot-09`); slot 10 unused |
| Routine | v1.5.1, enabled; no run after GRD-001 |
| Actions | idle |

## 2. What actually stopped the loop, and what changed

| Problem | Cause in batch 16 | Change in this batch | Evidence |
|---|---|---|---|
| **A. The work runs out** | only a finite, pre-approved task list | **Planner** (`claude_jules_task_planner.py`): humans approve *objectives* (scope, operations); signals (failing tests, CI failures, issues, TODOs, limitations) become validated proposals; duplicates are never planned; `GOAL_COMPLETE` only when every signal is resolved on `main`; unreadable signals are never "done"; a used-up list is not completion | `PlannerTests`; endurance 40/100/300 adds new work mid-run |
| **B. Merge waits stop everything** | the chain needed each predecessor; no idea of independent work | independent tasks continue while a PASS PR is unmerged; `depends_on` / same-file overlap → `DEFER MERGE_WAIT` with the exact PRs a human could merge; a `pull_request.closed` (merged) wake resumes them | `MergeFreeContinuationTests`, `StarterDependencyTests`, PRD-C2 rehearsal (B starts while A is unmerged) |
| **C. Too many files forbidden** | prefix ban on `claude_jules_*` and `claude_closed_loop_*` | path **risk classes**: `execution_config` (`.github/`, `.claude/`, `.mcp.json`) needs a human; `safety_boundary` (guards, starter, planner, loop, reviewer, carrier pins, route-separation test) is allowed to fix / test / strengthen with `safety_intent` and the full suite; everything else is ordinary development | `ClassificationTests.test_loop_code_is_ordinary_development_now`, `test_safety_boundary_can_be_fixed_and_tested_but_not_widened` |
| **D. Words cause false stops** | a regex on nouns such as "billing", "API key", "credits" | **typed operations** (`SAFE_OPERATIONS` / `HUMAN_OPERATIONS`); the text is only cross-checked for *imperative, non-negated* requests ("merge the PR", "rotate the API key"), and a mismatch isolates that task only | `test_safe_tasks_that_mention_dangerous_words`, `test_real_dangerous_requests` |
| **E. Silent DEFER** | DEFER was a return value, not a record | every DEFER has a reason code, `first_seen_at` (kept across ticks), `last_checked_at`, `next_check`, `recovery_action`, `dependency`, `independent_work_remaining`, `human_required`; escalated after `defer_escalate_minutes` when no independent work is left; checkpoint (`claude-jules-loop-checkpoint v1`) on the control issue only when the state changes or a heartbeat is due | `DeferLedgerTests` |

**Also found and fixed:** repeated invisible label writes used to isolate each task after 2 attempts. In the
300-round run that threw away healthy tasks during a burst of write failures. Now:

* the default is 5 attempts;
* after that the task backs off exponentially (up to 24 h) under `DEFER WRITE_PATH_UNHEALTHY`, escalated to a
  human;
* the task is never dropped and never labeled twice. Every attempt proves first that the label was never present.

## 3. Stop taxonomy

| Class | Meaning | Examples |
|---|---|---|
| CONTINUE | work goes on | a task was started, a task is running, a proposal was created |
| CORRECTIVE | reviewer (unchanged) | the `@jules` corrective; a repeat escalates to root cause |
| DEFER | temporary, re-checked; recorded and escalated if old | quota exhausted, lease held, unknown read, merge wait, write path unhealthy |
| ISOLATE | this task only; others continue | human-boundary operation, edited task, stale base, isolated dependency, out of scope |
| HARD_STOP | provider-execution boundary: no new Jules starts | paid or API route observed, invalid policy or manifest |

## 4. Wake design: checked against the official documentation

The Routine documentation was read on 2026-10-09. GitHub triggers support **Pull request and Release only**, and
there is no issues or issue_comment trigger. Events beyond the hourly caps are dropped. The schedule minimum is
1 hour.

* **The PR event is the heartbeat.** The reviewer run continues with a loop tick (Layer 4, v1.6 draft).
* `pull_request.closed` (merged) resumes merge-dependent work. **This trigger is not configured yet** (human).
* An hourly recovery schedule re-reviews unreviewed heads (a dropped event) and ticks. **Not configured yet**
  (human). Without it a dead run waits for "Run now", as `test_without_a_recovery_wake_a_dead_run_waits_for_a_human`
  shows.
* **Billing note from the documentation:** with usage credits on, routines can continue on metered overage. A
  human must confirm usage credits are off.

## 5. Tests

| Suite | Tests |
|---|---|
| WSL full suite | 2136, OK (skipped=1) |
| `test_claude_jules_loop` | 31 |
| `test_claude_jules_production_starter` | 61 |
| `test_claude_jules_starter_e2e` | 5 |
| `test_claude_jules_starter_gh` | 3 |
| `test_jules_route_separation` | 13 |
| Windows (loop + starter + route + review) | 160 OK |

**Planner-loop endurance** (`e2e-loop-stats.json`; every invariant asserted):

| Rounds | Merged | Jules starts | Max labels per issue | Correctives | Loop crashes | Faults injected / fired | Ticks |
|---|---|---|---|---|---|---|---|
| 40 | 40/40 | 40 | 1 | 8 | 10 | 20 / 20 | 156 |
| 100 | 100/100 | 100 | 1 | 18 | 27 | 50 / 50 | 374 |
| 300 | 300/300 | 300 | 1 | 64 | 67 | 150 / 150 | 1110 |

Every endurance run also includes:

* human merges at random times;
* work discovered mid-run;
* dependencies;
* transient read failures;
* duplicate webhooks;
* one human-boundary task that stays isolated, so the final outcome is `NO_SAFE_TASK` with exactly that task in
  `human_actions`.

**Recovery cases proven in the mock:**

* Claude dies after creating the issue;
* the issue-creation response is lost;
* Claude dies after the intent and after the label;
* a PR event is dropped;
* a transient read is retried, and a persistent one gives DEFER;
* a paid route stops new starts only;
* one isolated task does not stop the others;
* duplicate webhooks plus a corrective;
* quota exhausted, then reset;
* a stale controller, response loss and duplicates (starter tests).

## 6. STATIC / mock vs. real

| Item | Status |
|---|---|
| Planner, starter, loop, recovery, classification | **STATIC / mock only** (no LIVE in this batch) |
| Jules → PR → reviewer → corrective → PASS | **proven live before** (CLP-001, CLP-002, GRD-001) |
| PASS → next task started automatically | **not proven live**; rehearsed with the real PRD-C2 manifest in the mock |
| Read-only checks against live GitHub | done: the starter on #338 with A's body overlaid; a read-only loop tick on PRD-C2 (`DEFER`, not "complete") |
| Routine running the loop tick, `gh` in Routine, label history via MCP | **UNKNOWN** |
