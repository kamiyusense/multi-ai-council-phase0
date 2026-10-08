# Batch 12 (2026-10-09 JST): two-layer reviewer, structured correctives, graduation task prepared

No LIVE run in this batch. Slot 9 was not started; slot 10 is in reserve. No API
key. No Merge. No default-branch write. No force push.

## 1. Fresh start

| Item | Value |
|---|---|
| main | `8fbbef9` |
| #330 | `7aa43b3`, Draft, MERGEABLE, CI green |
| #331/#332, #333/#334 | terminal PASS (1 and 2 receipts). PRs open and not merged; heads `2550e2b` / `e1bf653` |
| #335 | open, unlabeled |
| ledger | slots 01–08 (8/10) |
| Routine | v1.4, enabled, trigger `opened`+`synchronize`. Runs: 4 on closed-loop PRs, no new runs since CLP-002 PASS |
| Actions | 0 in progress / 0 queued |

## 2. Why the reviewer changed

Before this batch the reviewer judged proof files. It checked exact lines,
the path fence and whitespace. A real code task needs judgement that string
checks cannot give, and that judgement must not be able to override the
mechanical facts. Ordinary failures also have to lead to a better corrective,
not to a stop.

## 3. Architecture (`claude_closed_loop_review.py`, Routine prompt v1.5)

| Layer | Owner | What it decides |
|---|---|---|
| 1. precheck | deterministic code | closed-loop task or not, task metadata (`proof` / `code_change`), terminal PASS, same head, same tree (same content, new commit), empty commit, broken records (never written over), round number, previous findings, path fence (unauthorized or deleted files become major `scope_violation`), existing corrective, existing next issue |
| 2. semantic review | Claude | each acceptance criterion `{met, evidence}`, root cause vs. symptom, weakened tests, regressions, interface/doc drift, missing regression test, each previous finding resolved or not, exact-head test run; result is a `CLAUDE_SEMANTIC_REVIEW_V1` record (`validate_semantic_review`) |
| 3. combine | deterministic code | fixed precedence, below |

Combine rules:

* A guard finding always means NEEDS_CORRECTION; Claude cannot override it.
* PASS needs all of these:
  * no major finding;
  * every criterion met;
  * every previous finding resolved;
  * for code tasks, tests PASS. Green tests with an unmet criterion are
    NEEDS_CORRECTION.
* BLOCKED is accepted only for the reasons that a corrective cannot fix:
  external dependency, permission, contradictory requirements, outside the
  approved scope, billing/provider boundary, or a destructive operation.
  Anything else is NEEDS_CORRECTION.
* If a finding repeats from the previous round, or a previous finding is
  unresolved, the corrective is escalated: "Root-cause review requested".
* When the budget is used up, the decision is TASK_BLOCKED for this task only.

Corrective (`build_corrective`): starts with `@jules`. For each finding it
gives:

* What is wrong
* Expected behaviour
* How to reproduce
* Regression test to add or keep
* Passes when

It also states the allowed files, says "do not weaken or delete existing
tests", lists the test commands, and ends with the per-head
`claude-closed-loop-corrective v1` marker.

Receipt v2 (`render_receipt` / `parse_receipt` / `validate_receipt`):

* exact keys, including `phase`, `criteria`, `pr_head_tree` and `findings`;
* `reviewed_at` must match `YYYY-MM-DDTHH:MM:SSZ`;
* the block must be one JSON object and nothing else. The CLP-002 ` `` `
  debris is refused for v2;
* v1 records stay readable through the debris-tolerant `_block`;
* the Routine is told to build the JSON with `python3 -c 'json.dumps(...)'`
  and paste it verbatim.

Routine prompt v1.5 is live on `trig_01U2DaBYLqaF5uLgovs1WY2Y`. The local copy
is `C:\Users\yuuki\pc-verify-330\closed-loop\routine-prompt-v1.5.md`. It is not
yet exercised live; the first wake under v1.5 is the graduation proof.

## 4. Tests

`test_claude_closed_loop_review.py` has 22 tests. With the 22 protocol tests
from batch 11, the focused total is 44 OK. The new tests cover:

* unrelated PR and bad metadata
* duplicate `opened` / `synchronize`, same tree with a new commit, empty commit,
  terminal replay
* malformed review record (never written over)
* unauthorized second file
* round count and carried findings
* clean PASS
* guard finding beats a semantic PASS
* green tests with acceptance unmet
* failing or not-run tests for code tasks
* new regression introduced during a corrective (caught, not escalated)
* previous fail reason still present (escalated to root-cause review)
* semantic PASS with an unresolved previous finding (not PASS)
* ordinary "blocked" becomes a correction; real blockers stop the task only
* correction limit (task isolated)
* crash after corrective before receipt (no second corrective)
* crash after next issue before PASS receipt (issue reused)
* blocked task and independent task
* semantic record must judge every criterion and previous finding
* strict v2 receipt render/parse (debris, timestamp, phase, criteria)
* corrective text is specific, scoped and marked
* the prepared graduation task passes the guard, and touching production code
  makes a guard finding even when tests pass

The full suite result is in `checkpoint-batch12.json`.

## 5. Graduation proof GRD-001 (prepared, not started, needs slot 9)

* **Bug (real):** on `main`, `automation/command_bus/tests/test_claude_jules_live_adapter.py`
  starts subprocesses with a literal `"python3"`, in `FAKE_TESTS` (line 34)
  and the crash command (line 420).
  * On this PC that made 3 tests fail. They exit 9009 through the Windows
    Store `python3` stub.
  * This is the same class of defect that made Loop 139's first inspection
    UNKNOWN.
* **Task:** `kind: code_change`; only that test file (MODIFY). Acceptance
  criteria: use `sys.executable`, keep every assertion as strict, add a
  regression test, change no other file. Test commands: the module and the
  full suite. Corrective budget 2, slot 9.
  * Issue body: `graduation-grd-001-issue-body.md`.
  * Task JSON SHA-256: `dd35da883bd2e02c7d91c379181d97072a5c7ddd565af46636e8e1735b958ae4`.
* **What it proves beyond CLP-001/002:**
  * the Routine runs real tests on the PR head;
  * semantic review of a real diff: root cause, no weakened assertions,
    regression test present;
  * the guard catches any production-file change;
  * a structured corrective if Jules misses a criterion.
* **To start (human approval required):**
  1. record slot 9 in the ledger;
  2. create the issue with this body;
  3. add the `jules` label once;
  4. watch the Routine runs and receipts read-only;
  5. verify independently.

## 6. Remaining risks

* The live reviewer is still an LLM following v1.5. The code is the contract
  and the independent verifier, not the executor in the wake. Compliance with
  v1.5 (tree SHA, test run, exact JSON) is unproven until the first v1.5 wake.
* The Routine has to run the tests itself in its cloud sandbox. Whether its
  environment can run the full suite in time is UNKNOWN until GRD-001.
* Jules' Reactive Mode is off, so Jules acts on any owner comment. The reviewer
  only comments with `@jules` correctives.
