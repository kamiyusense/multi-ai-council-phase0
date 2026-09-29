# Cloud Work green lane carrier v1

This file is the durable recovery note for the 💚 green lane.

## Canonical lane identity

- repository: `kamiyusense/multi-ai-council-phase0`
- carrier branch: `cloud-work/carrier-green-v1`
- carrier PR: #166
- required PR label: `cloud-green`
- command review prefix: `[CW_GREEN_V1]`
- receipt comment prefix: `[CW_GREEN_RECEIPT_V1]`
- protocol version: `1`

A ChatGPT conversation/thread/session ID is never a correctness input. A replacement chat must fresh-read this carrier PR, this file, the target PR/branch, and current GitHub state before submitting work.


## Execution environment boundary

This lane is executed by **Cloud Work**, not Local Work.

A submitting chat MUST NOT assign work that requires capabilities available only in Local Work or on the user's local machine. In particular, do not require direct access to the user's Windows/WSL filesystem, local checkout/worktree, local Docker Desktop/daemon, local terminal/process state, local desktop GUI, locally stored credentials, or other machine-local resources that Cloud Work cannot directly access.

Use this Green lane only for work that Cloud Work can complete from its own cloud execution environment and connected services such as the authorized GitHub connector/cloud browser capabilities available to that run.

If a requested task contains a Local-Work-only dependency:
- do not pretend Cloud Work can perform it;
- do not silently substitute or invent a local result;
- isolate that dependency as BLOCKED or UNKNOWN;
- complete any independent Cloud-safe work that remains within the command;
- record the capability boundary in the terminal receipt.

The submitting chat is responsible for routing Local-Work-only tasks elsewhere instead of sending them to PR #166.

## How a chat submits work

Submit exactly one GitHub pull-request review with action COMMENT to this carrier PR. Do not use PR Conversation comments, inline/diff comments, commit updates, or merges as the command trigger.

The review body must begin with the exact command prefix on line 1, followed by one JSON object:

```text
[CW_GREEN_V1]
{
  "protocol_version": 1,
  "command_id": "green-YYYYMMDDTHHMMSSZ-purpose",
  "target_repository": "kamiyusense/multi-ai-council-phase0",
  "target_pr": 0,
  "target_branch": "non-default-branch",
  "expected_target_head": "40-hex-sha",
  "expires_at": "ISO-8601 timestamp",
  "task": "bounded instruction",
  "allowed_paths": ["path/or/glob"],
  "verification": ["explicit verification step"],
  "live_provider_or_model_allowed": false,
  "retry": 0,
  "fallback": "disabled"
}
```

Required behavior:
1. Fresh-read this carrier PR and the exact triggering review.
2. Require this PR to still carry label `cloud-green`.
3. Require exact prefix `[CW_GREEN_V1]`, protocol_version=1, a unique command_id, unexpired expires_at, and complete target identity.
4. Fresh-read target PR/branch and require current target HEAD to equal expected_target_head before any target write.
5. Keep carrier PR and target PR separate.
6. Stay within task and allowed_paths. No unrelated changes.
7. After every write, read back from GitHub. Never blindly resend an ambiguous write.
8. retry=0; fallback=disabled.
9. No PR merge, direct default-branch write, force push, branch deletion, history rewrite, billing/API-key/settings/permissions change, or unapproved live provider/model start.

## Duplicate and stale-event guard

Before executing, inspect this carrier PR's Conversation comments for a terminal receipt with both prefix `[CW_GREEN_RECEIPT_V1]` and the same command_id. If one exists, the command is already terminal and must be a NO-OP.

If expected_target_head mismatches current target HEAD, expires_at is passed, required fields are missing, or identity cannot be verified, do not modify the target. Record a terminal receipt as UNKNOWN/BLOCKED/STALE as appropriate.

## Terminal receipt

Results are written to this carrier PR as a normal PR Conversation comment, not as a review, so the result does not retrigger the review-submission webhook.

Receipt format:

```text
[CW_GREEN_RECEIPT_V1]
{
  "protocol_version": 1,
  "command_id": "same command_id",
  "status": "PASS|FAIL|BLOCKED|UNKNOWN|STALE|NO_OP",
  "target_repository": "...",
  "target_pr": 0,
  "target_branch": "...",
  "target_head_before": "...",
  "target_head_after": "...",
  "verification": ["evidence/result summary"],
  "terminal": true
}
```

A terminal receipt is durable replay protection. Do not repeat the same logical command after a terminal receipt exists.

## Replacement-chat recovery

A new chat does not need the old chat history. It should:
1. fresh-read this carrier PR and this file;
2. fresh-read current target state;
3. create a new unique command_id;
4. submit one correctly prefixed COMMENT review to this carrier PR;
5. later read the matching terminal receipt from this carrier PR.

GitHub state is the durable source of truth.
