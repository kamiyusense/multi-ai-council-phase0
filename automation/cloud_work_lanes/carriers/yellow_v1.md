# Cloud Work yellow lane carrier v1

This file is the durable recovery note for the 💛 yellow lane.

## Canonical lane identity

- repository: `kamiyusense/multi-ai-council-phase0`
- carrier branch: `cloud-work/carrier-yellow-v1`
- carrier PR: #165
- required PR label: `cloud-yellow`
- command review prefix: `[CW_YELLOW_V1]`
- receipt comment prefix: `[CW_YELLOW_RECEIPT_V1]`
- protocol version: `1`
- worker state: `automation/cloud_work_lanes/carriers/yellow_worker_state_v1.json`
- replacement runbook: `automation/cloud_work_lanes/WORK_REPLACEMENT_HANDOVER_V1.md`
- current worker generation: `1` (authoritative active value is always read from worker-state JSON)

A ChatGPT conversation/thread/session ID is never a correctness input. A replacement chat must fresh-read this carrier PR, this file, the target PR/branch, and current GitHub state before submitting work.

## Worker generation fencing

This lane uses the worker-state JSON as a fencing authority. The current Cloud Work instance is generation `1`.

Before any command processing, the worker must fresh-read `automation/cloud_work_lanes/carriers/yellow_worker_state_v1.json`.

- If this worker's fixed WORKER_GENERATION does not equal the file's `active_generation`, this worker is stale and must silently NO-OP. It must not modify the target and must not write a terminal receipt.
- The command review must contain `worker_generation`.
- If the worker is active but `command.worker_generation != active_generation`, do not modify the target; return one terminal STALE receipt.
- Only when WORKER_GENERATION, active_generation, and command.worker_generation all match may normal validation/execution continue.
- Worker replacement must follow `automation/cloud_work_lanes/WORK_REPLACEMENT_HANDOVER_V1.md`.

This prevents an old Cloud Work from acting if it wakes after a replacement.


## Execution environment boundary

This lane is executed by **Cloud Work**, not Local Work.

Do not assign tasks that require direct access to the user's Windows/WSL filesystem, local checkout/worktree, local Docker Desktop/daemon, local terminal/process state, local desktop GUI, locally stored credentials, or other machine-local resources unavailable to Cloud Work.

If a Local-Work-only dependency is discovered, do not fabricate a result. Isolate it as BLOCKED/UNKNOWN, continue only independent Cloud-safe work within scope, and record the boundary in the terminal receipt.

## How a chat submits work

Submit exactly one GitHub pull-request review with action COMMENT to this carrier PR. Do not use PR Conversation comments, inline/diff comments, commit updates, or merges as the command trigger.

The review body must begin with the exact command prefix on line 1, followed by one JSON object:

```text
[CW_YELLOW_V1]
{
  "protocol_version": 1,
  "command_id": "yellow-YYYYMMDDTHHMMSSZ-purpose",
  "worker_generation": 1,
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
1. Fresh-read this carrier PR, the worker-state JSON, and the exact triggering review.
2. Apply worker generation fencing before any target action. A stale worker silently NO-OPs with no receipt.
3. Require command.worker_generation to equal the fresh active_generation; otherwise the active worker returns terminal STALE without target changes.
4. Require this PR to still carry label `cloud-yellow`.
5. Require exact prefix `[CW_YELLOW_V1]`, protocol_version=1, a unique command_id, unexpired expires_at, and complete target identity.
6. Fresh-read target PR/branch and require current target HEAD to equal expected_target_head before any target write.
7. Keep carrier PR and target PR separate.
8. Stay within task and allowed_paths. No unrelated changes.
9. After every write, read back from GitHub. Never blindly resend an ambiguous write.
10. retry=0; fallback=disabled.
11. No PR merge, direct default-branch write, force push, branch deletion, history rewrite, billing/API-key/settings/permissions change, or unapproved live provider/model start.

## Duplicate and stale-event guard

Before executing, inspect this carrier PR's Conversation comments for a terminal receipt with both prefix `[CW_YELLOW_RECEIPT_V1]` and the same command_id. If one exists, the command is already terminal and must be a NO-OP.

If expected_target_head mismatches current target HEAD, expires_at is passed, required fields are missing, or identity cannot be verified, do not modify the target. Record a terminal receipt as UNKNOWN/BLOCKED/STALE as appropriate.

## Terminal receipt

Results are written to this carrier PR as a normal PR Conversation comment, not as a review, so the result does not retrigger the review-submission webhook.

Receipt format:

```text
[CW_YELLOW_RECEIPT_V1]
{
  "protocol_version": 1,
  "command_id": "same command_id",
  "worker_generation": 1,
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

A new chat does not need the old chat history. It should read the replacement runbook before replacing a Cloud Work.

A replacement chat should:
1. fresh-read this carrier PR and this file;
2. fresh-read current target state;
3. create a new unique command_id;
4. submit one correctly prefixed COMMENT review to this carrier PR;
5. later read the matching terminal receipt from this carrier PR.

GitHub state is the durable source of truth.
