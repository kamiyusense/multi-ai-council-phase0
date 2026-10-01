# Claude × Jules AUTO loop — minimal LIVE proof plan (NOT AUTHORIZED)

> 日本語要約: これは「1回だけ」実際に Claude → Jules → Claude を通す実証の計画です。
> 準備ができていることと、実行が許可されていることは別です。下の「必要な承認」が
> すべて人間から明示されるまで、何も実行しません。

Status: **prepared, not authorized, not executed.**

## 1. Goal

Exactly one Claude-origin Jules task (docs-only, one new file) goes through the
real carrier workflow, Jules opens its normal PR, Claude detects it, inspects
it independently and fast-forwards only a Claude-dedicated, non-default target
branch. Then the loop must stop (`max_rounds = 1`).

## 2. Human approvals required (each explicit, in the user's own words)

1. **Live Jules dispatch, once.** Writing one claim + one command to the shared
   carrier branch `feature/chat-work-command-bus` triggers the existing workflow,
   which calls the Jules API with the existing `JULES_API_KEY` secret (Jules
   quota usage; private-repo Actions minutes, possibly billable after the free
   allowance). No new key, secret, or setting is needed.
2. **A Claude-dedicated target branch**, created from a chosen base (proposal:
   `claude/autoloop-live-target` from the current Claude dev branch HEAD). The
   ChatGPT controller must not use it.
3. **A Jules lane grant** for Claude AUTO (proposal: one lane not currently used
   by the ChatGPT controller, decided by the user; J-GREEN is **not** assumed).
4. **An AUTO owner ACQUIRE event** for `origin_loop_id` (proposal:
   `claude-auto-live-001`) with a short lease (e.g. 3 h), written to the Claude
   data branch (proposal: `claude/claude-jules-autoloop-data`, a new branch).
5. **Policy edit** on the integration branch: fill `allowed_target_branches`,
   `allowed_lane_ids`, `expected_pr`, `max_rounds: 1`, and
   `live_dispatch_authorization` (`max_dispatches: 1`, expiry, approval ref).
6. **Wake mechanism choice** (see §4). Option A needs a Claude Code scheduled
   routine to be created, which is an account-side action.

## 3. Execution (after approval only)

1. Fresh-read carrier, claims, target HEAD/tree, owner chain; run the full suite.
2. `step()` once → expect `DISPATCH / DISPATCHED`; read back claim, work branch,
   command, binding, receipt; read the workflow run and accepted session id.
3. Wait for the Jules PR (base `jules-work/<command_id>`).
4. Ingress the PR (§4), then `step()` → `INSPECT`; Claude runs the full suite on
   the exact candidate head and records acceptance evidence.
5. `step()` → `ADOPT` (non-force fast-forward of the dedicated target only) →
   read back HEAD/tree; `step()` → `STOP / MAX_ROUNDS`.

## 4. Wake options

- **A (recommended):** a Claude Code scheduled routine re-reads open PRs whose
  base starts with `jules-work/` and feeds them to the same normalizer with a
  synthetic delivery id (`poll-<PR>-<HEAD>`); the result id is unchanged, so
  polling and webhooks can never double-process.
- **B:** a PR-activity subscription after the PR exists (needs the PR number,
  so it only helps after the first observation).
- **C (not proposed):** a GitHub Actions job starting Claude would need a new
  API key/secret → separate approval and billing decision.

## 5. Stop conditions / observation / recovery

- Any BLOCKED/UNKNOWN step stops the loop; nothing is retried or resent.
- Observe through the data-branch records and the carrier workflow summary.
- If the session is lost, a new Claude session calls `step()` with the same
  policy; records make it resume or NO-OP.
- Undo: the dedicated target branch can be left as is; nothing touches `main`,
  the ChatGPT lanes or existing PRs. Branch deletion would need separate approval.

## 6. Inspection for the proof

Required evidence: workflow run conclusion + accepted session id; head-ref
session = PR footer session; changed paths exactly the one allowed ADD; full
suite on the exact head/tree; both acceptance checks observed directly in the
file content; adoption readback HEAD/tree.
