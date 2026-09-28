# Chat -> Jules API -> GitHub -> Human semi-auto loop

Status: development route on PR #6; human-triggered only.

## Goal

When the user is awake, remove manual copy/paste between ChatGPT and Jules while
keeping the human as the final decision-maker:

```text
human asks Chat to inspect/continue
  -> Chat fresh-reads GitHub and reviews the current result
  -> Chat creates exactly one durable Jules command JSON on PR #6 branch
  -> GitHub push workflow validates command + target HEAD/tree
  -> bounded GitHub workflow submits exactly one direct Jules REST request
  -> Jules works from the exact non-default branch and creates its normal PR
  -> Chat fresh-reads workflow/Jules PR/ancestry/diff/tests
  -> Chat reports PASS / FAIL / UNKNOWN to the human
  -> human decides Merge or the next semantic direction
```

This is deliberately **not** an unattended loop. No result automatically creates
the next Jules command.

## Durable command path

Append-only commands live at:

`automation/command_bus/jules_api_requests/<command_id>.json`

A command commit must add exactly one file and change nothing else. Updating an
existing command does not dispatch.

Required profile: `JULES_CHAT_SEMIAUTO_V1`.

Each command binds:

- unique `command_id`
- exact repository
- exact non-default target branch
- exact target HEAD and tree
- explicit allowed changed paths
- bounded task prompt
- timezone-aware creation/expiry timestamps, lifetime <= 2 hours
- `retry = 0`
- `fallback = disabled`
- `merge_allowed = false`
- `force_push_allowed = false`

## Dispatch gates

The workflow `.github/workflows/jules-chat-semiauto.yml` runs only for command
JSON pushes on `feature/chat-work-command-bus`.

Before the Jules API call it requires:

1. the command commit changed exactly one file;
2. that file is a newly-added command JSON at the exact command path;
3. the strict request schema validates;
4. the request is not expired;
5. target branch is non-default and safe;
6. fresh GitHub target HEAD equals `expected_target_head`;
7. fresh GitHub target tree equals `expected_target_tree`.

Any mismatch stops before Jules submission. There is no workflow retry/fallback.

## Human-awake operating procedure

The user can say, for example, `検品して、問題なければ次へ進めて`.

Chat should then:

1. fresh-read the current target PR/branch and any Jules-created PR/result;
2. independently inspect ancestry, changed paths, diff, tests/checks, and prior
   command evidence;
3. if a bounded next implementation task is justified, generate one new command
   ID and one command JSON using the fresh target HEAD/tree;
4. write that one command file to PR #6 branch and read back the new carrier head;
5. do not resend if the write or subsequent workflow/Jules submission is
   ambiguous;
6. on the next user check-in, fresh-read GitHub rather than relying on remembered
   session state;
7. never Merge without explicit human approval.

## Mandatory task-time footer

Every Chat that uses this semi-auto loop and returns control to the human after
dispatching a Jules task must end its user-facing reply with one mandatory
task-time footer.

The footer is part of the semi-auto operating contract, not optional presentation.

Rules:

1. Confirm that Jules actually accepted the session before calling the task
   "投入済み". A command commit, queued Action, or pre-Jules validation is not
   enough.
2. Use the confirmed Jules `session accepted` timestamp converted to
   **Asia/Tokyo / JST** as the dispatch time.
3. Classify the dispatched task as exactly one of:
   - `短`
   - `中`
   - `長`
4. Estimate a completion window from the accepted-session time and the actual
   bounded task scope. The window is a human checking guide only; it is not a
   correctness claim or SLA.
5. Render the footer as an H2-sized bold line using `🟣🕒`.
6. It must be the **last line of the Chat reply**. Do not put any prose after it.
7. Do not append wording such as
   `→ この時間以降なら結果確認おすすめ`.
8. If Jules acceptance cannot be verified, do not invent an投入時刻 or completion
   estimate. Report the dispatch state as UNKNOWN in the main body instead.

Canonical display shape:

```text
## **🟣🕒 Loop 039投入：12:59 ／投入タスク目安：中／ 推定完了目安：13:15〜13:25ごろ**
```

The Loop number, accepted time, task size, and estimated window must be replaced
with the current task's verified values.

## Evidence boundary

GitHub Actions green alone is not PASS. The hardened workflow captures and validates the
Jules session ID and starting branch, but session creation still proves transport only.

After dispatch, Chat must verify as available:

- exactly one logical command file
- workflow run identity and job/log evidence
- Jules-created PR/commit
- starting-branch relationship and commit ancestry
- changed path set vs `allowed_paths`
- tests/check evidence
- no automatic Merge
- no retry/fallback

Unverifiable state is `UNKNOWN`, not PASS.

## Out of scope

- sleeping/unattended next-command generation
- Scheduled Task GitHub writes
- automatic Merge
- direct writes to `main`
- force push/history rewrite/branch deletion
- Billing/Credits/Overages or permission changes
- API-key display or mutation
- provider fallback or automatic retry
