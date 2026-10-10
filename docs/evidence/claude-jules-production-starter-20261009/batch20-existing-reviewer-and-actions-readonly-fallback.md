# Batch 20: existing Reviewer A / read-only GitHub Actions backup B

Date: 2026-10-10 JST. Purpose: prepare without any new Cloud Probe, LIVE,
settings change or workflow activation.

## Fresh readback at start

- main 702497c6b464a3b1ab09441b21fc6f96bd3bb2d0
- PR 340 Draft OPEN / head bf1315c22a3666dbaf4f17d37e9da5b7d92ddffa
- Issue 338 OPEN, prepared-not-started; LIVE slot-01..09, slot 10 unused
- Existing Reviewer v1.5.1 has past PR-event wakes, semantic reviews and
  durable PASS receipts. See batch10-github-native-closed-loop-proof.md.
- Existing Claude Routine current settings cannot be independently read here.
  Past working GitHub MCP reads do NOT prove gh api issue-event history reads.
- New Probe 01/03 received 403 because their session had no repo access.
  Probe 02 result remains UNKNOWN (not recovered). Do not repeat them.

## A: keep existing Reviewer, do not repeat new Routine probes

1. Preserve running Reviewer v1.5.1: do not touch permissions or reconnect auth.
2. Future proof, only after separate authorization, must use an ACTUAL existing
   Reviewer session to read Issue 335 and 338 events to the final page, including
   per_page=2 and the old 'labeled jules' event on 335.
3. Keep existing independent Layer 1-3 reviews and receipts going if new
   Layer 4 GitHub-read readiness fails. Scope the hold to NEW Jules starts.
4. Candidate v1.6 wording (draft only): perform a real authenticated GET;
   a 403 means REPO_ACCESS_BLOCKED. Incomplete label-event pages mean
   LABEL_HISTORY_UNKNOWN. Skip only new activation, do not erase receipts,
   change settings, use add_repo, retry unknown writes or infer historical
   absence from current labels.
5. Separate human approval remains necessary for PR Merge, updating v1.6,
   recovery schedule, any live authorization and slot 10 activation.

## B: optional read-only GitHub Actions backup (NOT deployed)

A future GitHub Actions job could use its repository-scoped GITHUB_TOKEN
with minimum Issues-read permission to query
GET /repos/{owner}/{repo}/issues/{number}/events
with page and per_page, following Link next-page records and checking all IDs.

Important: GitHub's token normally does not recursively trigger workflows
except documented dispatch cases and PR approval exceptions. Never treat an
Actions workflow as an automatic closed loop without wake-chain proof.

The new module claude_jules_history_proof.py only validates an untrusted
snapshot STRUCTURE: it rejects missing pages, malformed data, duplicate event
IDs, 403, stale head, wrong target/source and contradictory current labels.
It always returns provenance_verified=false. A valid JSON value, even with
source='github-actions-read-only', is NOT authentic proof. Before consuming,
independently bind the real workflow run identity, trusted workflow/ref,
successful exact-head check, artifact digest and current issue/main state.
Keep the Production Starter's own preflight and human LIVE boundaries.

No .github/workflows file was added. No actual Actions, Jules or Claude model
was started. No API key or new token used. Private repo Actions minutes and
billing/permissions must be reviewed before activation.

Official references:
https://docs.github.com/en/rest/issues/events
https://docs.github.com/en/actions/concepts/security/github_token

## Offline verification and status

- New stdlib-only structural helper; 17 local mock cases PASS.
- Expected result is STRUCTURALLY_COMPLETE or UNKNOWN, never 'LIVE PASS'.
- No Cloud Routine changes, triggers, schedules, label writes or Merge.
- Full repository CI requires independent exact-head readback after push.
- Route A runtime gh event-history capability is UNKNOWN until a separately
  approved proof on the existing Reviewer.
