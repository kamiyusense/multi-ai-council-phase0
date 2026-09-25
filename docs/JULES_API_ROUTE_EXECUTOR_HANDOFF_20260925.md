# Jules API Route — Executor Sol Handoff — 2026-09-25

Role: implementation/execution Sol for Multi-AI Council Phase 0.

Canonical decision:
`docs/JULES_API_ROUTE_DECISION_20260925.md`

## 1. Fresh-read first

Before doing anything mutable, fresh-read:

- repository `kamiyusense/multi-ai-council-phase0`
- PR #4 and branch `feature/relay-transport-7070955470193506982`
- PR #6 and branch `feature/chat-work-command-bus`
- PR #8 and its isolated Jules failure history
- current default branch
- the Jules API route decision above
- `.github/workflows/jules-phase0-smoke.yml` once it exists on default branch

GitHub current state wins over SHAs in this document.

## 2. Current route decision

The BrowserHook / Work Cloud Browser Jules route is frozen.

The user authorized the Jules API route.

Primary predecessor:
`google-labs-code/jules-action@bff7875eaa123cac6742b7cfc51005b95ba4d566`

Do not use the upstream README's stale-looking `jules-invoke@v1` reference.

## 3. What is already allowed

Without new confirmation, continue safe/read-only/preparation work:

- fresh GitHub readback
- static inspection
- docs/checkpoint/evidence updates on authorized non-default branches
- workflow syntax inspection
- target branch/head/tree readback
- test-plan verification
- post-write readback
- no-live dry/static validation

## 4. Human/system boundaries still remaining

Do not perform on the user's behalf unless the product explicitly presents the
user approval flow and the user approves it:

- create/show/change Jules API key
- add/change GitHub repository Secret `JULES_API_KEY`
- Merge any PR to `main`
- direct write to `main`
- Billing/Credits/Overages changes
- force push / history rewrite / branch deletion

The user's authorization of "API route" does not expose the secret value to Chat.

## 5. First live smoke procedure

After the workflow is present on the default branch and the user has placed the
secret:

1. Fresh-read PR #4 head/tree.
2. Record the exact expected head/tree for this logical smoke.
3. Confirm the workflow uses the exact non-default branch.
4. Dispatch exactly once.
5. Do not retry if the GitHub Actions result is ambiguous.
6. Read back GitHub/Jules evidence.
7. Identify the Jules-created PR/commit.
8. Verify ancestry/base/path scope against the fresh expected target.
9. Verify available tests/evidence.
10. Write a durable checkpoint.
11. Do not Merge.

The smoke task is intentionally tiny:
modify only `tests/relay/test_dispatcher.py` and add the pre-dispatch abort
regression described in the decision document.

## 6. Required acceptance evidence

PASS requires evidence, not self-report:

- fresh expected target head/tree
- action/workflow commit identity
- one dispatch only
- Jules session/task evidence
- resulting commit SHA
- resulting PR URL/number
- resulting commit parent/ancestry
- PR base/source branch evidence
- changed filenames/operation
- test evidence or explicit UNKNOWN
- retry_count = 0
- fallback_used = false
- Merge = false

A green Actions job alone is insufficient because the pinned upstream action
does not fail on every HTTP 4xx/5xx response.

## 7. Failure handling

- wrong branch/base/parent -> BLOCKED, no replay
- no durable session evidence -> UNKNOWN, no replay
- Action green but no Jules session -> UNKNOWN, no replay
- unrelated changed files -> BLOCKED
- test failure -> record failure; do not hide it
- API quota/rate limit -> record exact backend response; do not auto-retry
- Billing/auth/settings request outside the approved route -> stop at human boundary

Do not cherry-pick/rebase the failed PR #8 into PR #4.

## 8. After a successful smoke

Only after the first API smoke is verified:

- use the Jules API/GitHub Action route as the Jules transport
- keep GitHub as durable control plane
- replace only the failed BrowserHook launch transport, not the whole Phase 0
  state/evidence architecture
- wire durable command -> dispatch -> readback -> receipt in the smallest useful
  increment
- preserve retry=0 and terminal replay prevention
- keep Sol semantic review separate from Work/mechanical evidence
- do not add cjules/SDK/custom controller unless a concrete limitation requires it

## 9. Completion principle

Do not stop at "workflow added" or "Action ran".

Continue safe verification/readback until either:

- the bounded smoke has a durable verified result, or
- a true human boundary/blocker remains.
