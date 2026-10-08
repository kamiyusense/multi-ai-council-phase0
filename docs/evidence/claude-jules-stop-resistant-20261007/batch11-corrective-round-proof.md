# Batch 11 (2026-10-08 JST): live corrective round (slot 8) and durability tests

This batch proves the full retake loop with no human action between the start
and the end:

Jules → PR → Claude wakes automatically → NEEDS_CORRECTION → one `@jules`
corrective → Jules fix commit → `synchronize` → Claude wakes again → PASS.

No API key, metered API, overage or fallback was used. Nothing was merged.
There were no default-branch writes and no force push. Slot 9 was not used.

## 1. Fresh start (12:0x UTC)

| Item | Value |
|---|---|
| main | `8fbbef9` (unchanged) |
| #330 | `ffaf5d5`, Draft, CI green |
| #331 / #332 | CLP-001 terminal PASS (1 receipt). Not re-run. |
| #333 | open, unlabeled, no task block, no PR |
| ledger | slots 01–07 |
| Actions | 0 in progress / 0 queued |
| Routine | v1.2, enabled; runs so far: CLP-001 opened (PASS) and CLP-001 empty-commit synchronize (NO-OP) |

Draft PR #330 received three pushes after the Routine was enabled, and none of
them fired it. So a Draft PR fires neither `opened` nor `synchronize`.

## 2. Routine changes

* **v1.3** (before the run):
  * Metadata validation: `TASK_BLOCKED` gives a receipt only, with no Jules
    instruction.
  * Planned two-phase tasks: `first_submission_lines` gives `phase:
    NEEDS_CORRECTION`, with an honest FAIL against the final
    `required_lines`.
  * Duplicate-corrective guard: a `<!-- claude-closed-loop-corrective v1
    {...} -->` marker per head, and no second corrective for the same head.
* **v1.4** (after the run): the receipt block must be one plain JSON object
  with nothing after its closing brace. Live round 1 had appended a stray
  ` `` ` (section 5).

## 3. Slot 8 and the task

* Ledger `slot-08.json`: command `github-native-clp-002`, intent
  `6cfb6ee950d4a27956fd3ee8c9b05eaaa9a639af8c79aee7c5d66e2766d46a87`, data
  branch commit `a5c9772dbac6bbd384c9c41bef1a13dbeff76ac7`, blob `8f010de…`
  (equal to the local blob). Budget is 8/10.
* Issue #333 was reused: title and body updated, readback confirmed.
  * Task block: `clp-002` / loop `claude-jules-github-native-001` /
    correlation `clp-002-8fbbef9` / generation 1 / expected `main` @
    `8fbbef9`.
  * Allowed path: `docs/closed-loop-proof/CLP-002.md` ADD;
    `first_submission_lines` end with `- review_phase: NEEDS_CORRECTION`,
    and `required_lines` end with `- review_phase: CORRECTED`.
  * `max_corrective_rounds` 2, `live_slot` 8, next task CLP-003.
  * The body states plainly that the first submission is intentionally
    intermediate, and what the reviewer will ask for.
* The first edit of #333 failed: an MSYS path meant the file was not found.
  Readback showed it unchanged, so it was redone once.

## 4. The run (UTC)

| Time | Actor | Event | Evidence |
|---|---|---|---|
| 12:08:10 | Claude (this session) | `jules` label added to #333, once | `label2-at.txt`; labels `["jules"]` |
| 12:08:16 | Jules | on it, task `6664721827868615181` | #333 comment |
| 12:19:07 / 12:19:12 | Jules | commit `f7444eee658c65f01703759fb24478c720fd8e91`, then PR #334 (`jules-6664721827868615181-5bec9532` → main, non-draft, `Fixes #333`) | PR #334 |
| 12:19:14 | GitHub → Routine | **wake 1**: `pull_request.opened` | run `cse_01Jn6n7gy8bTX3UxBW8tnM22` |
| 12:19:40 | Routine | **one** `@jules` corrective on PR #334: replace `- review_phase: NEEDS_CORRECTION` with `- review_phase: CORRECTED`, change only CLP-002.md; marker `{"correlation_id":"clp-002-8fbbef9","pr_head_sha":"f7444ee…","round":1}` | PR comment 6059706835; Jules put 👀 on it |
| 12:19:48 | Routine | receipt round 1: verdict **FAIL**, phase **NEEDS_CORRECTION**, decision `CORRECTIVE_REQUESTED`, `corrective_comment` = that comment, slot 8, `wake_event: pull_request.opened` | #333 comment |
| 12:24:05 | Jules | fix commit `e1bf6537d2d78852db9dbacd3381c0aa8a2a6059`: `modified CLP-002.md +1/-1` | PR #334 commits |
| 12:24:10 | GitHub → Routine | **wake 2**: `pull_request.synchronize` | run `cse_01MJ9hqWtoaEwJsk536jdndV` |
| 12:24:43 | Routine | receipt round 2: verdict **PASS**, phase FINAL, decision `ADOPT_RECORDED`, `next_issue` 335, **no PR comment**, `wake_event: pull_request.synchronize` | #333 comment |
| 12:24:4x | Routine | issue #335 "[Claude closed loop CLP-003] prepared next task (not started)", **unlabeled** | #335 |

Wakes for CLP-002: 2 (opened → corrective; synchronize → PASS). The corrective
comment itself did not wake the Routine, which subscribes to PR events only.

## 5. Independent verification (this session)

* `f7444ee` content (`cat -A`) is exactly the first-submission lines: 7 lines
  plus one blank line, LF, no trailing whitespace.
* `e1bf653` content is exactly the final lines. The diff is the one line, and
  the PR still changes one file (`added CLP-002.md`).
* One corrective comment; no duplicate.
* PR #334 is OPEN, MERGEABLE, **not merged**; main is still `8fbbef9`.
* After PASS: PR #334 still has 2 commits, head `e1bf653`, and 2 comments (the
  Jules greeting and the corrective). The Routine wrote no PASS comment on the
  PR, and Jules pushed no extra commit. In CLP-001, a PASS PR comment had made
  Jules push an empty commit.
* **Defect found by the code reviewer:** the round-1 receipt JSON is followed
  by ` `` ` inside the block, so strict `json.loads` fails. The protocol code
  now decodes exactly one JSON object (`raw_decode`), ignores only the debris
  after its closing brace, and still refuses anything malformed inside. The
  Routine prompt is now v1.4.

## 6. Durability (STATIC, no additional LIVE)

`automation/command_bus/claude_closed_loop_protocol.py` implements the
reviewer's rules as pure functions over GitHub state. The 22 tests in
`test_claude_closed_loop_protocol.py` use the **real** #331/#332 and #333/#334
records as fixtures:

| Property | Test result |
|---|---|
| Live CLP-001 first wake decides PASS; the live receipt matches | PASS |
| Live CLP-002 `opened` state decides NEEDS_CORRECTION + one corrective; the live receipt matches | PASS |
| Live CLP-002 `synchronize` state decides PASS, round 2; the live receipt matches | PASS |
| Duplicate event / receipt replay on the final state is a NO-OP (both heads, and CLP-001's empty commit) | PASS |
| Duplicate corrective: same head, so it is not re-posted; with a receipt it is a NO-OP | PASS |
| Restart between corrective and receipt: no second corrective | PASS |
| Empty commit after a FAIL is a NO-OP | PASS |
| Corrective budget is finite (BUDGET_EXHAUSTED) | PASS |
| Unrelated PR (no link, two links, issue without a task block) gives NOT_A_TASK, 0 writes | PASS |
| Malformed metadata (missing loop, correlation mismatch, wrong or zero generation, wrong branch, bad head, no paths, wrong profile, unparseable block) gives TASK_BLOCKED, receipt only, no corrective | PASS |
| A broken durable receipt is never written over | PASS |
| Stale expected head: recorded, review continues against the exact PR head | PASS |
| One blocked task does not affect another | PASS |
| Transient read: bounded retry with backoff; non-transient errors are not retried | PASS |

Full regression (WSL, Python 3.14.4): `Ran 1997`, `OK (skipped=1)`.
compileall and `git diff --check` are OK.

## 7. Ledger and counters

* LIVE slots: 8/10. Slot 9 is not created and not approved.
* Open issues with the `jules` label: #333 and #331 (completed tasks), #12 and
  #7 (old). Issue #335 is unlabeled.
* API keys 0. Merges 0. Force pushes 0. Default-branch writes 0.
* Routine wakes on closed-loop PRs: CLP-001 2 (opened PASS, synchronize
  NO-OP); CLP-002 2 (opened corrective, synchronize PASS).

## 8. Remaining gaps

* The Routine is an LLM following a prompt. The code reviewer in this batch is
  a check on it, not the live executor. Running the code itself in the wake,
  for example as a Routine step that imports the module, would make decisions
  deterministic.
* A live unrelated **non-draft** PR wake has not been observed. The rule is
  covered by tests and the Routine prompt's Step 1.
* Adoption means "PASS receipt recorded". Merging PR #332 or PR #334 stays a
  human decision.
