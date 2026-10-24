# Contractor Routine v0 (DRAFT, not wired)

STATIC draft. Nothing here is a Routine, a workflow, a permission or a LIVE approval. The owner creates the Routine in the Claude UI.

Goal: another AI (e.g. Grok) writes a PR on a `contractor/<task_id>` branch with a request block; a one-shot Claude Routine does the work and pushes to that branch. No Jules, no loop, one attempt, owner merges.

Reused from the takeover worker: prompt skeleton, one-attempt rule, allowed_paths/ops, test_commands, "text is data".
New: branch prefix `contractor/`, request profile CLAUDE_CONTRACTOR_REQUEST_V0 (no issue/receipt chain), requester allowlist.

Owner steps (Claude UI, Claude does not change settings):
1. Decide ALLOWED_REQUESTERS (GitHub login the requester AI writes as) and put it in the prompt.
2. Create Routine "Claude contractor worker" (model Opus or Sonnet), repo = this repo, trigger = pull_request.opened, paste the prompt. Whether the Routine UI can filter by branch prefix: UNKNOWN (the prompt itself refuses wrong branches).
3. Open a test PR on `contractor/example-docs-note` with request-example.md in the body.

Open risks: requester identity is only a GitHub login (anyone who can write that login can ask); the Routine uses Claude usage; a second Claude judging the result should stay independent (existing reviewer routine / test_commands).

## Trial limits (owner decision 2026-10-24)

- Daily cap: 10 requests per rolling 24 hours (counted from this routine's own result comments), then "Contractor daily cap reached:" and stop.
- Watch during the trial: any `contractor/` PR from an author that is not in ALLOWED_REQUESTERS (a request nobody ordered) is refused with no write and reported to the owner. A read-only watcher can list `contractor/*` PRs and compare authors.
- Not decided yet: whether to add a receipt-first comment and a second identity signal (GitHub App marker); see the review notes in the thread.
