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

## Mandatory Jules prompt contract

Before Chat writes any new `jules_api_requests/<command_id>.json`, it MUST fresh-read and follow `docs/JULES_TASK_PROMPT_SPEC.md`.

The command prompt must be a bounded execution contract, not an open-ended request. It must include one mission, exact allowed paths, reuse-first instructions, explicit Do Not Touch rules, machine-checkable semantic acceptance criteria, concrete negative/tamper cases, vacuous-test prohibition, exact finite validation commands, publication conditions, and explicit stop conditions.

A green Jules suite is evidence only. Chat must independently review semantics after the result returns.

## Durable command path

Append-only commands live at:

`automation/command_bus/jules_api_requests/<command_id>.json`

A command commit must add exactly one file and change nothing else. Updating an
existing command does not dispatch.

Required profile: `JULES_CHAT_SEMIAUTO_V2`.

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
3. if a bounded next implementation task is justified, read `docs/JULES_TASK_PROMPT_SPEC.md`, construct the task with its mandatory prompt structure, then generate one new command ID and one command JSON using the fresh target HEAD/tree;
4. write that one command file to PR #6 branch and read back the new carrier head;
5. do not resend if the write or subsequent workflow/Jules submission is
   ambiguous;
6. on the next user check-in, fresh-read GitHub rather than relying on remembered
   session state;
7. never Merge without explicit human approval.

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
