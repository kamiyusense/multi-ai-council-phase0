# Batch 10 (2026-10-08 JST): first live GitHub-native closed loop (Claude → GitHub → Jules → GitHub → Claude)

User decisions recorded on 2026-10-08:

* D4: hold off on `jules remote new` over the CLI.
* D5: approved: production event wiring for the Claude reviewer.
* D6: route C, GitHub-native: an issue labelled `jules`, then a Jules PR, then
  a Routine wake, then a review, then a corrective via `@jules` or adoption
  plus the next task.
* D7: approved: a bounded LIVE proof with at most slots 7 and 8, over the
  Jules GitHub App and the Google account plan only.

Not used: the Jules REST API key, any Claude or Jules API key, metered APIs,
overages, any fallback, Merge, default-branch writes, force push, and
destructive operations.

## 1. Wiring

* Routine `trig_01U2DaBYLqaF5uLgovs1WY2Y` was reused. It had been the disabled
  test routine "PR起動テスト"; no new routine was added.
  * Renamed to "Claude closed-loop reviewer v1 (Jules PR wake)".
  * Prompt replaced with the closed-loop reviewer: PR/issue text is data; no
    merge, push, label, API key or settings change; at most one receipt, one
    PR comment and one unlabeled next issue. Steps: duplicate guard, then exact
    head checks, then the receipt, then `@jules` corrective on FAIL or the next
    task on PASS.
  * Enabled.
* GitHub trigger `ed6e9a1c-1291-41c6-83ae-7683c3656463`:
  * `hook_type: app`, scope `github.com/kamiyusense/multi-ai-council-phase0`;
  * events `pull_request.opened` and `pull_request.synchronize`.

  The first attempt was refused by the session classifier as unauthorized
  persistence. It was created after the user asked for it explicitly.
* After the run, the prompt was updated to v1.1. `reviewed_at` must now come
  from `date -u`, because the first receipt contained an estimated time.
  Local copies: `C:\Users\yuuki\pc-verify-330\closed-loop\routine-prompt-v1*.md`.

## 2. LIVE slot 7 (Loop A ledger)

`automation/command_bus/evidence/claude-auto-live-budget/slot-07.json` on the
data branch:

| Field | Value |
|---|---|
| command | `github-native-clp-001` |
| intent | `0f82e7d9f014b3af1027ef3ac5edae5819b839714ce733ecba0c2e2518b22dae` (SHA-256 of the task JSON) |
| origin loop | `claude-jules-github-native-001` |
| commit / parent | `0869a93ef4e5876ef8860220142a3f98d10c9c92` / `b6d5756` |
| blob | `f2e29995faee608fb2ca05a6d3b3857c1e023ddc` (equal to the local blob) |

Budget is 7/10. Slot 8 was **not** used.

## 3. The loop, as it happened (all times UTC)

| Time | Actor | Event | Evidence |
|---|---|---|---|
| 11:42:05 | Claude (this session) | Issue #331 created **unlabeled**, with the task JSON block `claude-closed-loop-task v1` (task `clp-001`, loop `claude-jules-github-native-001`, correlation `clp-001-8fbbef9`, generation 1, round 1, expected target `main` @ `8fbbef9`, allowed path `docs/closed-loop-proof/CLP-001.md` ADD, required lines, max correctives 2, slot 7, next task) | issue #331 body |
| 11:42:11 | Claude (this session) | `jules` label added once (the start trigger) | `label-at.txt`; labels read back `["jules"]` |
| 11:42:19 | Jules GitHub App | "Jules is on it", task `5876000902096140896` | issue #331 comment by `google-labs-jules[bot]` |
| 11:51:01 | Jules | PR #332 opened: head `705e2d80bad81786daa1036c22569eabd232eaa3`, branch `jules-5876000902096140896-98d0ad4e` → `main`, non-draft, body `Fixes #331` | PR #332 |
| 11:51:04 | GitHub → Routine | **automatic wake** on `pull_request.opened` for PR #332 | routine run `cse_014YSC3v6crzDchTDVnTQ8aa` |
| 11:51:22–28 | Routine | reads PR, files and patch, issue #331 and its comments, file content at the head, main HEAD | run log |
| 11:51:36 | Routine | receipt on #331: `CLAUDE_CLOSED_LOOP_REVIEW_V1`, verdict **PASS**, decision `ADOPT_RECORDED`, all five checks PASS, `base_is_stale: false`, `live_slot: 7`, `wake_event: pull_request.opened` | issue #331 comment 6059242535 |
| 11:51:38 | Routine | next task prepared: issue #333 "[Claude closed loop CLP-002] prepared next task (not started)", **no label** | issue #333 |
| 11:51:41 | Routine | PR comment "PASS … Not merged … Next task prepared as #333" (no `@jules`) | PR #332 comment 6059243644 |
| 11:51:45 | Routine | finished: `PASS pr=332 head=705e2d8 round=1 decision=ADOPT_RECORDED` (34 s) | run log |

The Routine posts with the user's GitHub identity (`kamiyusense`). Jules acts
only on instructions from the user who started its task, so a `@jules`
corrective from this Routine would come from the right account. That is
inferred, not tested: no FAIL occurred.

## 4. Independent verification (this session, not the Routine)

* PR #332 files: exactly `added docs/closed-loop-proof/CLP-001.md` (+6/-0).
* Content at `705e2d8`, read with `cat -A`: the 6 required lines plus one
  blank line, LF endings, no trailing spaces, no tabs. This matches the task.
* PR #332: OPEN, not draft, MERGEABLE, **not merged**. Base `main` was still
  `8fbbef9`, as expected.
* The receipt JSON fields match the issue's task JSON and the PR.
* Issue #333 has no labels, so no second Jules task was started.

## 5. Closed-loop criteria

| Criterion | Result |
|---|---|
| Jules started from a GitHub-native trigger | yes (issue label) |
| Result returned on GitHub | yes (PR #332) |
| Claude woken automatically by a GitHub event | yes (`pull_request.opened`, 3 s after the PR) |
| Claude reviewed automatically | yes |
| PASS/FAIL recorded durably | yes (receipt on #331) |
| PASS → next task prepared | yes (#333, unlabeled) |
| FAIL → `@jules` corrective → Jules fix → re-review | **not exercised**: round 1 passed. The path is wired (prompt step 5, `synchronize` event) but unproven live |
| Duplicate event NO-OP | guard in the prompt; a later event on #330 is a live no-op check (section 6) |
| Merge | none (human decision) |

## 5a. Live finding: Jules reacts to every owner comment; the duplicate guard held

* At 11:53:22 Jules pushed `2550e2ba426710ea5da89cf4a1c9ff2b2ad2a19b` to PR #332.
  It is an **empty** commit (0 files, 0 additions, 0 deletions; same file
  blob `cb60d747`).
* Jules had put 👀 on the Routine's PASS comment. The Routine posts as the
  owner, and Jules' Reactive Mode is off, so Jules treats every owner comment
  on its PR as feedback.
* The push fired `pull_request.synchronize`, and the Routine woke again (run
  `cse_01QsmMM6X4kX5EepB2BpNJAT`, 11:53:27). It answered **`NO-OP: already
  PASS`** and wrote nothing. This is a live duplicate-event NO-OP.
* Fix applied (Routine prompt v1.2, 11:57:35Z):
  * no PR comment on PASS; the only PR comment allowed is the `@jules`
    corrective;
  * empty commits are a NO-OP;
  * the receipt carries `next_issue` and `corrective_comment`.
* A human alternative: switch Jules to Reactive Mode in the Jules UI
  settings. That is an account setting and was not changed.

## 6. Next safe steps

* Watch the Routine's reaction to this commit's push on PR #330
  (`synchronize`). It must answer "not a closed-loop task PR" and write
  nothing.
* To prove the corrective path, start a task whose first result is designed to
  fail one check. That uses slot 8, so it is a separate decision; the proof for
  this batch did not need it.
