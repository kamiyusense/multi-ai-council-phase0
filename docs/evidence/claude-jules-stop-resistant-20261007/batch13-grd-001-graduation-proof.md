# Batch 13 (2026-10-09 JST): GRD-001 graduation proof — real bug fix through the two-layer reviewer (slot 9)

User approvals: GRD-001 on slot 9 ("スロット9開始承認"). Slot 10 is in reserve.
PR #330 merge is deferred until after this result.

No API key. No Merge. No default-branch write. No force push.

## 1. Before the start

| Item | Value |
|---|---|
| main | `8fbbef9`. The bug is present: `"python3"` literals at lines 34 and 420 of `automation/command_bus/tests/test_claude_jules_live_adapter.py` |
| #330 | `cf3332a`, CI green; then `1f00af6`, the task change below |
| Routine | v1.5 (two-layer), enabled |
| ledger | 8/10 |

**Fix before the start:** the task's test commands were changed from
`python -m …` to `python3 -m …`. The cloud reviewer may have no bare `python`.
That would give `NOT_RUN`, and then a false NEEDS_CORRECTION on a correct fix.

The task JSON SHA-256 is
`eb95218916e359682fc36a3b0de4e2a6d8d2279ece185a6061b19ba6a1720c31`.

## 2. Start (each operation once)

| Time (UTC) | Operation | Readback |
|---|---|---|
| 17:52:49 | ledger `slot-09.json` (command `github-native-grd-001`, intent = task SHA) | data branch `7e778853f8d7eebb3fc355d3d3d1fa5cd3b67a9c`; blob `0edc03ac…` matches the local blob |
| 17:53:0x | Issue #335 reused: title and body set to the GRD-001 task | task block present, `kind: code_change` |
| 17:53:03 | `jules` label added | labels `["jules"]` |

## 3. The run

| Time (UTC) | Actor | Event |
|---|---|---|
| 17:53:10 | Jules | on it, task `5755515948434524038` |
| 18:01:00 | Jules | commit `2ce8caabb63df36c8fb7be1057344dceb7f732ab`, tree `01fb0ddf8c237d2978c169fce5abd1d59905f4f4` |
| 18:01:05 | Jules | PR #337 `jules-5755515948434524038-ead860a1` → main, non-draft, `Fixes #335` |
| 18:01:06 | GitHub → Routine | **wake** `pull_request.opened`, run `cse_01Rj1nvYRvLSPdHHLZWK6zom` |
| 18:04:30 | Routine | real UTC timestamp from `date -u` |
| 18:04:38 | Routine | receipt on #335: `CLAUDE_CLOSED_LOOP_REVIEW_V2`, verdict **PASS**, decision `ADOPT_RECORDED`, round 1, phase FINAL, `pr_head_tree` bound, `next_issue` 338, slot 9 |
| 18:04:4x | Routine | #338 "[Claude closed loop GRD-002] prepared next task (not started)", **unlabeled** |

Routine wakes for GRD-001: 1. The Routine posted no PR comment. No corrective
was needed.

## 4. Jules' change (+6/-2, one file)

* `import sys`
* `FAKE_TESTS = [sys.executable, "-c", …]`
* crash command `[sys.executable, "-c", "raise SystemExit(3)"]`
* new `test_fake_tests_command_uses_sys_executable` (asserts `FAKE_TESTS[0] == sys.executable`)
* every existing assertion unchanged

## 5. Two-layer review: what the Routine recorded

| Layer | Result |
|---|---|
| Deterministic guard | one changed path, status `modified` = allowed `MODIFY`; no scope violation; round 1; no prior receipt |
| Claude semantic review, criterion 1 (interpreter) | met: "grep python3 count is 0; FAKE_TESTS and crash command use sys.executable" |
| criterion 2 (assertions unchanged) | met: "Diff only swaps interpreter; assertions unchanged; nothing removed or skipped" |
| criterion 3 (regression test) | met: "test_fake_tests_command_uses_sys_executable asserts FAKE_TESTS[0]==sys.executable" |
| criterion 4 (no other file) | met: "Only the one allowed test file changed" |
| Tests run by the Routine on the PR head | PASS: module 18 tests OK; full discover 1912 tests OK (skipped=1) |
| Findings | none |

## 6. Independent verification (this session)

* The receipt parses with the **strict v2 parser**: one JSON object, exact
  keys, real timestamp. The CLP-002 debris problem did not recur.
* WSL clone at PR head `2ce8caa` (tree `01fb0dd`, the same as the receipt):
  * module: `Ran 18 tests`, OK;
  * full suite: `Ran 1912 tests`, `OK (skipped=1)`.

  This is exactly what the Routine reported.
* `"python3"` literals left in the file: 0.
* **The bug is really fixed.** On Windows (`py`, where `python3` is the Store
  stub):

  | Ref | Result |
  |---|---|
  | main `8fbbef9` | `Ran 17 tests`, `FAILED (failures=3)`: `test_dispatch_poll_review_inspect_adopt_on_real_git`, `test_full_pass_and_adoption_with_real_fast_forward`, `test_tests_run_on_exact_head_in_isolated_worktree` |
  | PR #337 `2ce8caa` | `Ran 18 tests`, **OK** |

* After PASS (checked 18 minutes later): PR #337 still has 1 commit and 1
  comment (the Jules greeting). Jules made no extra commit. #338 is
  unlabeled. PR #337 is OPEN, MERGEABLE, **not merged**. main is still
  `8fbbef9`.

## 7. What the live run did not exercise

The fix was right the first time, so these paths were not exercised live:

* a corrective;
* rejection of an unauthorized file;
* "tests green but criterion unmet";
* "previous fail reason still present".

They are covered by STATIC tests
(`test_claude_closed_loop_review.py`). The corrective round itself was proven
live with CLP-002 (batch 11).

## 8. Tests added

`LiveGraduationTests`, 3 tests using the real #335/#337 records:

* the strict v2 receipt parses and binds head and tree;
* the first-wake state passes the guard, and the live semantic judgement
  replayed through `combine` gives the same PASS;
* replay after PASS is a NO-OP.

Focused total: 47 OK.

## 9. Ledger

The ledger is at 9/10. Slot 10 is not used.
