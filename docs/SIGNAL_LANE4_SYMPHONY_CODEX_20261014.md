# Signal lane 4 redefinition: Symphony -> Codex (2026-10-14)

Owner decision (2026-10-14 JST, thread message): the fourth lane `Work -> Jules` (`work-jules-auto`) is dropped
because that route stalled and cannot be realised. Its place is taken by the Codex-based Symphony loop, which the
owner reports is about 80 percent complete. Lanes 1 and 2 (`chatgpt-semi-auto`, `chat-work-semi-auto`) stay as they are.

## Lane table after the decision

| # | Display | Internal id today | State |
|---|---|---|---|
| 1 | Chat -> Jules | `chatgpt-semi-auto` | DURABLE |
| 2 | Chat -> Work | `chat-work-semi-auto` | PLACEHOLDER |
| 3 | Claude -> Jules | `claude-jules-auto` | PLACEHOLDER |
| 4 | Symphony -> Codex (replaces Work -> Jules) | `symphony-codex-auto` (renamed 2026-10-14) | PLACEHOLDER, in development |
| - | Claude -> Claude | `claude-claude-auto` | FROZEN |

This note itself changed no registry. The owner then approved the rename (2026-10-14) and the production registry row
was renamed in a follow-up change (see "Rename plan", now executed). Nothing here promotes a lane to DURABLE or wires
global registration; Issue #33 stays STOPPED.

## What GitHub shows for Symphony (read 2026-10-14, main 1e24510)

- Content for the minimal orchestrator, adoption bridge, G5-G7 bridges, operator installation and readiness is on main
  (PR #320, #343, #364, #382, #388 are closed/merged; files such as `symphony_autonomous_controller.py` exist on main).
- Official Symphony Local LIVE generation 4 passed a bounded one-file worker proof (one model turn, normal same-thread
  continuation observed, operator stop). Generations 1-3 failed and are preserved. Source: PR #320 description.
- Open Draft PR #398 prepares the worker-first native binary and SQLite checks. Its own result is
  `PUBLICATION_AUTHORITY_UNKNOWN / LIVE_NO_GO`; `WORKER_FIRST_LOCAL_READY` is not reached.
- PR #382 and #388 results: `PRELIVE_BLOCKED / INSTALLATION_NOT_ACTIVATED / LIVE_NO_GO` and
  `INSTALLATION_READINESS_COMPLETE / ACTIVATION_REVIEW_READY / LIVE_NO_GO`. Production workflows stay hard OFF.
- Unproven per those PRs: automatic Git adoption, real delivery, completed continuation, natural stall recovery,
  quota-reset restart recovery. No claim of 80 percent is verified from GitHub; it is the owner's figure.

## Rename plan (executed 2026-10-14 after owner approval)

When the owner approves, one change set renames the row and keeps the old id out of live use:

1. `control_tower_registry.json`: new `loop_id` (proposal `symphony-codex-auto`), display `Symphony -> Codex`,
   `controller_kind` OTHER, `worker_kind` OTHER (no schema change; a dedicated CODEX kind can come later).
2. `lane_stable_identity.LANE_SHAPES["work-jules"]` and `post_adoption_verification` placeholder tuple.
3. About a dozen tests that name `work-jules-auto` or "Work -> Jules", plus the Issue #33 dry-run render evidence,
   which would need a new sealed render instead of an edit.

Stable id rules still apply: never derived from colour, carrier PR, worker generation, session or command id.

Executed as planned: registry row, `LANE_SHAPES` key (`symphony-codex`), the post-adoption placeholder tuple and the
tests that read the production registry now use `symphony-codex-auto`. Sealed evidence was NOT edited: the v3 fixture,
naming-policy JSON, Issue #33 dry-run render and the SF-9 post-adoption checkpoint (hash-pinned) keep the old id, and
the tests that compare against them map the one renamed id and the registry digest back explicitly.
