# GitHub event → Work → Jules loop: static feasibility review

Snapshot: 2026-09-29 JST. Research only; no Work wake, provider call, Jules
dispatch, automation creation, permission change, or Merge was performed.

## Source identity and current operation

- `main`: `e1b453452df64053bde15596674ee6796e2d9e25` at the first read.
- Command-bus carrier `feature/chat-work-command-bus`: `3b680b8692d2f90cd779f3f809be8641f94965c6` at the implementation snapshot.
- Canonical Relay PR #4: OPEN at `672033b9ab0ff91829b2595617b5ae120aceb6b1` at the first read.
- PR #6: MERGED. Re-read all refs before using this design; these values are evidence, not future expected heads.
- `RELAY_2PLUS1_EXPERIMENT.md` records Loop 048 accepted after correction and Loop 049 dispatched/in progress at its latest entry. The ledger is a checkpoint, not proof that Loop 049 remains active now.
- `docs/CHAT_JULES_API_SEMIAUTO.md` defines one append-only command JSON at
  `automation/command_bus/jules_api_requests/<command_id>.json` per bounded
  Jules submission. The Actions workflow checks a fresh target HEAD/tree before
  its single REST submission. Jules acceptance and later PR/ancestry/diff/tests
  need independent readback; an Actions green result is insufficient.

## Route decision

| Priority | Route | Status for replacing this Chat | Verified capability / boundary |
| --- | --- | --- | --- |
| 1 | Official GitHub event-triggered scheduled task | PARTIAL | Eligible web/mobile tasks can watch PR activity, filtered by repository, PR, author, title or label; reviews, comments, commit updates and merges are documented. Desktop event triggers are not offered. Matching events may be combined into one run. Exact event payload fields, per-event run identity, branch filter, this account's eligibility and GitHub write permissions remain UNKNOWN. |
| 2 | GitHub Actions → Workspace Agent API | PARTIAL | A published Workspace Agent has an official asynchronous trigger API, stable `agtch_` ID, optional idempotency key, and beta run-status readback. This is a Workspace Agent, not a public API for creating an ordinary ChatGPT Work task. It requires a Workspace Agent access token and workspace/admin permissions; that setup is outside this static batch. Completed response content is not returned through the API. |
| 3 | BrowserHook / Work UI navigation | NOT AVAILABLE as a supported event trigger | Repository modules are static preflight/mock contracts. They neither create a Work nor establish a supported GitHub → Work event channel. A UI session/PC/browser route would need separate live proof and durable output readback. The old Jules-launch BrowserHook remains frozen. |
| 4 | Codex cloud GitHub integration | PARTIAL alternative | Official GitHub entry points can start Codex cloud coding work, but this is a different surface and does not establish automatic Work wake or the full Relay loop. |
| 5 | Agents API | PARTIAL alternative | Official managed Codex sessions can be started through an API with webhooks, but model usage is billed at API rates. This does not meet the requested no-new-metered-API route. |

Official sources:

- https://learn.chatgpt.com/docs/automations
- https://learn.chatgpt.com/docs/browser
- https://learn.chatgpt.com/docs/enterprise/chatgpt-work-cloud-security
- https://developers.openai.com/workspace-agents/trigger-runs
- https://developers.openai.com/workspace-agents/authentication
- https://developers.openai.com/api/docs/guides/agents-api/overview
- https://learn.chatgpt.com/docs/cloud

## Recommended arrangement and ownership

Use the official GitHub PR event trigger, if the account exposes it, as a
**wake hint**. The fresh Work run must read the current GitHub control plane and
decide what is unprocessed. It must never equate one trigger with exactly one
GitHub event, because matching events can be combined. Do not require an event
payload SHA or a persistent Chat/Work session ID for correctness.

| Current Chat steps | Candidate owner | Status for this repository |
| --- | --- | --- |
| 1–5: fresh state, canonical PR, Jules PR, ancestry, paths | Cloud Work + GitHub connection | Conceptually replaceable; actual read scope/permissions and exact-source access UNKNOWN. |
| 6–7: semantic diff and safety review | Cloud Work | Replaceable as reviewer judgment, with structured verdict/evidence and fail-closed UNKNOWN. Quality equivalence unproven. |
| 8: safe isolated correction | Work executor | UNKNOWN until cloud checkout, mutation permissions, path policy and workspace integrity are verified. |
| 9–12: tests, compile, diff and exact candidate validation | GitHub Actions for deterministic checks; Work interprets results | Existing exact validation route is reusable. Work-side local execution is not established by event-trigger docs. |
| 13–15: canonical fast-forward, exact validation, readback | GitHub-controlled publication plus Work review | Safe static gates exist, but unattended canonical publication is not proven; no live authority granted by this document. |
| 16: loop ledger/checkpoint | Work via authorized GitHub write | Feasible only if app can make the required append-only/branch writes; account-level proof UNKNOWN. |
| 17: bounded next task design | Work planner | Possible with explicit scope, structured verdict and human decision boundaries; semantic quality UNKNOWN. |
| 18–20: isolated starting branch, exact HEAD/tree, command JSON | Work preparation + GitHub deterministic validator | Existing command schema/workflow can be reused; cloud Work branch/write capability UNKNOWN. |
| 21–22: one Jules submit and accepted-session readback | Existing GitHub Actions + Jules API route | Keep the existing single-submit path. Do not add a second dispatcher. |
| 23–25: retry/fallback/merge/live-provider policy | Shared machine gates + human for Merge | retry=0 and fallback=disabled are mandatory; Merge remains human-only. Live provider/model execution is outside this work. |

The original 25-step list counts Jules dispatch separately from live provider
execution. Any later unattended loop must reconcile that authorization boundary
explicitly; this static review does not authorize a new Jules session.

## Event-driven control flow

```text
Jules publishes PR or commit
  → official GitHub PR activity trigger (hint; can be coalesced)
  → fresh cloud Work, if supported for this account
  → fresh GitHub PR #4 / Jules PR / command / state / receipt readback
  → already terminal? NO-OP
  → mismatch or missing evidence? UNKNOWN/BLOCKED
  → verified diff + deterministic exact validation
  → approved publication boundary, then remote readback
  → structured review/next-task decision
  → one append-only existing Jules command, bound to fresh target HEAD/tree
  → existing Actions single-submit route → Jules acceptance readback
  → Work ends; later GitHub PR activity starts a fresh reconciliation
```

The carrier branch head can advance independently. `expected_target_head`
binds the target PR #4, not the carrier. Existing `EventProcessor`, reviewer
records, `DurableWakeBackend`, executor `PREPARE_ONLY`, and the Jules command
workflow remain the authoritative mechanisms. A wake reservation is append-only:
after an ambiguous outcome, a fresh session reads it but cannot resend.

## Static proof included here

`test_work_event_static_poc.py` composes the existing command processor,
durable reviewer wake reservation and mock scheduled transport. It checks that:

1. the first command is processed and the repeated event is NO-OP;
2. exactly one mock wake follows one verified reservation;
3. a new session recovers the reservation and cannot send again;
4. a stale target HEAD blocks before any wake;
5. receipts retain retry_count=0 and fallback_used=false.

This proves only local protocol behavior. It does not prove the official event
trigger is enabled, that Work receives any particular payload, that a cloud
Work can write GitHub, that semantic review is correct, or that the full
unattended Jules loop is operational.

## Last boundary before live Hook proof

For the first real event-trigger POC, the user would need to create/enable an
eligible web/mobile event-triggered task and authorize the GitHub connection.
Start with one fixed PR and a read-only prompt that writes no command or
canonical commit. Verify the resulting Work run and its independent GitHub
readback; then separately review write permissions and a harmless append-only
checkpoint before enabling any Jules command. Account plan, run limits, and
model-use implications are UNKNOWN here. The GitHub connection transmits
repository content to the configured service under its permissions. A failed
or coalesced wake may delay processing; GitHub receipts keep duplicate events
from becoming duplicate actions.

The Workspace Agent API route would additionally require an admin-enabled
agent, access token, API channel, app permissions and a separate live test.
No token or permission changes are part of this research. The Agents API has
metered API billing and is outside the chosen route.
