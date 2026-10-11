# Claude x Jules: Jules API route V1 (design, STATIC)

Status: changes 1 (corrective resend) and 2 (selectable start route) implemented on this branch, STATIC only.
Nothing is LIVE until this is merged and the carrier branch exists.

## Owner decisions (2026-10-11 JST, chat with Claude Code)

- The Jules API may be used (AGENTS.md exception). The owner confirmed it from official information when the
  ChatGPT -> Jules semi-auto loop was built and ran it for 100+ loops; no extra billing confirmation is needed.
- Build it as a fallback **and** make it selectable as the main start route, because Routine/label behaviour may
  change.
- Limits (accepted as proposed): session reads <= 5 per wake; activity pages <= 3 per wake; `sendMessage` <= 1 per
  corrective and <= 3 per day, never resent when the outcome is unknown. Session create stays inside the existing
  durable budget ledger (one slot per start). `approvePlan` is not used.
- Reuse the semi-auto loop's parts as far as possible; no development or tests that are not needed.

## Why

The first LIVE prod-c1 cycle stopped twice:

1. Jules answered the `@jules` corrective PR comment with an emoji only; the next commit had the same tree, the
   reviewer correctly said NO-OP, and the loop waited forever. The owner had to use "Talk to Jules" by hand.
2. The start route depends on the Jules GitHub App reacting to the `jules` label. If that changes, starts stop.

## Shape: the key never reaches Claude

```text
Routine (Claude) -> deterministic tick command -> append-only request JSON
   -> git push to carrier branch claude/jules-api-carrier
   -> GitHub Actions workflow on main (secret JULES_API_KEY) -> exactly one Jules REST call, retry=0
   -> sanitized evidence in the run summary / job log -> next wake reads it back
```

- The key lives only in the existing repository secret `JULES_API_KEY` (set 2026-09-25, used by the semi-auto
  workflows). Claude, the Routine prompt and the request files never contain it. A prompt-injected Routine can at
  most write a request file, and every request is validated by the workflow before the call.
- The Routine can push `claude/*` branches: budget slot 1 was written by the Routine to
  `claude/claude-jules-autoloop-data` (commit `060efc53`, 2026-10-10T13:54Z). The semi-auto carrier
  `feature/chat-work-command-bus` stays the ChatGPT controller's; the Claude lane gets its own carrier so the two
  control planes do not share files or numbering.

## Reused parts (no rewrite)

| Need | Existing part | Change |
|---|---|---|
| send a corrective | `.github/workflows/jules-session-message.yml` (one added file, state check before send, prompt <= 4000, retry 0) | add carrier branch; allow `expected_state` `COMPLETED` as well as `AWAITING_USER_FEEDBACK` |
| read a session | `.github/workflows/jules-session-readback.yml` + `jules_session_acceptance.py` (sanitized evidence) | add carrier branch |
| start a session | `.github/workflows/jules-chat-semiauto.yml` steps: exact head/tree check, payload `AUTO_CREATE_PR`, returned `startingBranch` check | new small workflow reusing these steps for a `CLAUDE_JULES_API_START_V1` request (no Loop-ID claim; base `main` at an exact head, as the label route already does) |
| one start = one slot | `claude_jules_durable_budget.py` ledger on `claude/claude-jules-autoloop-data` | none |
| Jules session id of a PR | Jules PR body link `https://jules.google.com/task/<id>` (parsed in PR #354) | none |
| duplicate-start safety | starter intent -> write -> readback -> receipt | same sequence, the write is the request file instead of the label |

## Changes

1. **Corrective fallback (fixes stop 1).** In the deterministic tick: a corrective exists for head H, the PR head
   still has H's tree after `jules_ack_timeout_minutes` (60), and no fallback was sent for this corrective ->
   prepare one message request (same corrective text, session id from the PR body). If the tree is still unchanged
   one timeout after the message's run succeeded -> `TASK_BLOCKED` for that task only (isolated; the campaign
   continues). An unknown send outcome is read back from the workflow run, never resent.
2. **Selectable start route (fixes stop 2).** Policy field `route` accepts `jules-api-carrier` besides
   `jules-github-app-issue-label`. The route is chosen in the human-merged campaign/authorization, never by the loop.
   No automatic switching between routes: a route failure is a DEFER/HARD_STOP as today, and the owner switches.
   `route_problem` accepts the API route only with `billing_route: subscription` declared by the owner.
3. **Reviewer prompt v1.7** = v1.6.1 (PR #354) + nothing else, unless the tick command needs a new flag.

## Change 1 as implemented

- `claude_jules_loop.ignored_corrective` / `_resend_corrective`: runs for every RUNNING task in a tick. Request id
  `<task_id>-r<round>-msg`, so a lost push is read back on the next wake (`api_message_sent_at`, one GET of the
  carrier's commits for that path) and never sent twice. Sent and still unchanged one ack timeout later ->
  `JULES_UNRESPONSIVE`, `human_required` (the task stays visible in the checkpoint; it does not end the campaign).
- `GhLoopPort.api_message_request`: session id from the PR body's Jules task link (exactly one), prompt = a short
  reason plus the reviewer's corrective comment (trusted author and corrective marker required), cut to 4000
  characters, `expected_state` `COMPLETED`.
- `GhLiveWritePort.api_message`: needs `api_message` in the human-merged authorization `writes` (added here), the
  stop switch open, one per wake, three per 24 hours (counted from the carrier's commits), and pushes the file
  with `GitLiveClient.create` (create-only, no force).
- The reviewer prompt needs no change: LAYER 4 already runs after a LAYER 1 NO-OP.
- After merge, a human-approved one-time step creates `claude/jules-api-carrier` from main; the workflows run from
  the carrier's own copy, so the carrier is refreshed from main when these workflows change.
- When Jules' helpers from objective `o2-jules-api-requests` land, the port uses them instead of its inline code.

## Change 2 as implemented

- Policy `route` is `jules-github-app-issue-label` (today) or `jules-api-carrier`. `allow_api_fallback` stays
  `false`: the loop never switches routes; a human merges the switch.
- `route_problem(observation, route)`: the API route needs the declaration `transport: jules-api-carrier`,
  `auth_method: repository_secret_api_key`, `billing_route: subscription`. Paid words or another REST route still
  HARD_STOP; a declaration for the other route is DEFER.
- Starter on the API route: the create-only file `claude_jules_api_start_requests/issue-<n>.json` on the carrier is
  the label (present = started, never written twice). The `jules` label on such an issue isolates it (the GitHub
  App would start a second task). An unread carrier is DEFER `START_RECORD_UNKNOWN`. Everything that can refuse
  (task block, carrier branch present) is checked before the budget slot is reserved.
- Planner tasks carry the policy's route; a task prepared for the other route is isolated, never started.
- `.github/workflows/claude-jules-api-start.yml`: one added request file, exact keys and profile, repository,
  file name = issue, starting branch = default branch, the issue is open, holds this correlation id and has no
  `jules` label; then one `POST /v1alpha/sessions` (`AUTO_CREATE_PR`, no plan approval), returned starting branch
  checked, session id in the run summary. The secret appears only in that step; retry 0.
- The prompt is the issue title and body plus "the PR description must contain `Fixes #<n>`" (the reviewer links
  PRs to tasks by it).

### Switching the start route (one owner-merged PR, three files)

1. `docs/claude-jules-loop/active/campaign.json`: `policy.route` -> `jules-api-carrier`.
2. `docs/claude-jules-loop/active/authorization.json`: `route` -> `jules-api-carrier`.
3. `docs/evidence/claude-jules-production-starter-20261009/route-declaration.json` (the path the Routine prompt
   passes): `transport` -> `jules-api-carrier`, `auth_method` -> `repository_secret_api_key`.

Unstarted tasks prepared for the old route are isolated and re-planned; running tasks are unaffected. Switching
back is the same three edits in reverse.

## Not in V1

`approvePlan`, session listing, any automatic route fallback, merging, changing the Routine trigger.
The missing wake after a merge (Routine is not woken by `pull_request.closed`) is a Routine setting and is tracked
separately.

## Work split

- Claude (this lane's controller): workflows, starter route, tick fallback. These are execution-config or
  safety-boundary paths and are not given to Jules.
- Jules via the loop (owner asked for many small rounds): a pure helper module
  `automation/command_bus/claude_jules_api_requests.py` (build + validate the three request kinds, file naming,
  size limits) and its tests, split into small signal issues under a new objective. The safety-boundary modules
  import it only after Claude reviews it.

## UNKNOWN until the first LIVE use

- Whether the id in a Jules PR's `https://jules.google.com/task/<id>` link is the API session id (the semi-auto
  loop used the same number for both; not re-checked for label-started tasks).
- Whether `sendMessage` is accepted for a session in state `COMPLETED` (the web "Talk to Jules" worked on such a
  session on 2026-10-11; the API path is untested).
- Whether a PR from an API-started session keeps the `Fixes #N` line the prompt asks for (the reviewer needs it).
- Whether `pull_request` events from an API-started Jules PR wake the Routine the same way (same bot account
  expected).
