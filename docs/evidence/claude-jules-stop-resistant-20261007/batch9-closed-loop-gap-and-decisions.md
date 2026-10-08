# Batch 9 (2026-10-08 JST): what stands between the code and one live closed loop

Fresh readback at the start of this batch:

| Item | Value |
|---|---|
| main | `8fbbef9` |
| #330 head | `c840e3a` (Draft, MERGEABLE) |
| carrier | `38e92c7` (readback workflow blob `a4f0189`) |
| data branch | `b6d5756` (Loop 139 CLI settlement) |
| live target | `53f2caf` |
| runs in progress / queued | 0 / 0 |
| Loop A budget | 6/10 |
| owner a-003 | generation 2, SEMI_AUTO |

No write was made in this batch except this document.

## 1. Closed-loop requirements against what already exists

| # | Requirement | Status | Where |
|---|---|---|---|
| 1 | Detect Jules output on GitHub | done | `claude_jules_result_event` inbox, `poll`, result PR normalizer (`jules-result-pr<PR>-<HEAD>`) |
| 2 | GitHub event wakes Claude | designed and tested by hand, **not created** | `docs/CLAUDE_JULES_ROUTINE_WAKE_V1.md`: a Routine on `pull_request.opened` for non-draft PRs fired on PR #317; target `claude_jules_live wake-resume` |
| 3 | Claude inspects automatically | done (STATIC) | `claude_jules_inspection`, review record, exact-head tests, reinspection chain |
| 4 | PASS/FAIL recorded durably | done | create-only inspection, reinspection and adoption receipts on the data branch |
| 5 | Return a corrective to Jules on FAIL | done (STATIC); **live route blocked** | `corrective_task_spec` → next dispatch intent. The dispatch transport is the carrier REST API-key workflow, which the route guard stops (D1) |
| 6 | Re-inspect after the fix | done (STATIC) | same `step` / `wake-resume` path |
| 7 | PASS → next task | done (STATIC) | adoption → `_after_adoption` → next roadmap task |
| 8 | Restart recovery | done | every step re-derives state from GitHub; tested |
| 9 | Duplicate event → NO-OP | done | create-only records, terminal receipt checks, `CliSettlementStore` |
| 10 | Stale HEAD → replan | done | `STALE_TARGET` recovery |
| 11 | Task blocker isolation | done | campaign state, `TASK_BLOCKED` |
| 12 | Tests / exact-head CI | done for #330 | full suite 1975 OK (skipped 1) locally and on Actions |
| 13 | One live loop over an approved subscription/account route | **blocked** | sections 2–3 |

## 2. Why item 13 cannot run without a human decision

A live loop needs Jules to do new work twice: the first task, then a corrective or the next task. Every way to start new Jules work is outside the approvals given so far:

| Route | How it starts Jules work | Approval |
|---|---|---|
| Carrier REST (`jules-chat-semiauto.yml`, `X-Goog-Api-Key`) | `POST /v1alpha/sessions` | **not approved** (D1); the guard stops it before any write |
| REST message (`jules-session-message.yml`) | `sendMessage` with the API key | not approved (D1) |
| Jules Tools CLI (`jules remote new`) | new session over the account login | **not covered** by D2 (reads only); the route's billing is not confirmed |
| Jules web UI | a human types the task | outside automation |

Evidence collected for the CLI/account route (for the user's decision, not a decision):

* jules.google/docs/usage-limits: the plans are task-count limits. Jules (base)
  has 15 daily / 3 concurrent tasks, Pro has 100 / 15 and Ultra has 300 / 60.
  When the limit is reached, "you will not be able to trigger new tasks until
  the limit resets". That means blocked, not billed. "Paid Jules plans are
  accessed via a Google AI Plans subscription."
* The page says nothing about API or CLI pricing. So the CLI route's billing
  stays UNKNOWN in the guard, and new model work over it is `STOP_PROVIDER`.

## 3. A second, architectural gap: where the wake runs

* A Claude Routine runs in Anthropic's cloud. It can read GitHub and run
  `wake-resume` for inspection and adoption. It has no Jules CLI login, so the
  only Jules transport it could use is the REST API-key carrier, which is
  blocked.
* The Jules CLI login exists only on the user's PC. The PC is not woken by
  GitHub events: making it so would need a self-hosted runner or a local
  scheduler, and both are configuration changes.

A loop that is both event-driven and API-key-free therefore needs one of these:

| Option | Shape | What the user must approve |
|---|---|---|
| A | The cloud Routine inspects, adopts and writes the next or corrective task as a create-only **request file** on GitHub. A PC-side Claude Code session runs that request with `jules remote new` over the CLI. The PC side is woken by a local scheduled task, so this is polling on the PC. | Routine creation; new model work over the CLI route (billing decision); a local scheduled task |
| B | Declare the CLI/account route as subscription-confirmed from the usage-limits evidence and run the whole loop from the PC. The wake is a PC poll of GitHub, not a GitHub event. | new model work over the CLI route; accept polling instead of events |
| C | Accept the REST API-key route for Jules only (revisit D1) with a cost cap. | D1 reversal; it was explicitly refused |

## 4. Deferred decisions opened by this batch

| id | question | safe default |
|---|---|---|
| D4 | May Claude start **new Jules work** (`jules remote new`) over the CLI/account route? The task counts against the plan's daily task limit, which per the usage-limits page blocks rather than bills. If yes, record a `PROVIDER_ROUTE_DECLARATION_V1` (`transport: jules-tools-cli`, `auth_method: account_oauth`, `billing_route: subscription`, evidence = the usage-limits page, with an expiry). | no new Jules work |
| D5 | Create the production Routine (`pull_request.opened`, base starts with `jules-work/`, prompt from `CLAUDE_JULES_ROUTINE_WAKE_V1.md`, wake-resume only). | not created |
| D6 | Choose option A or B in section 3 (event wake in the cloud plus a PC executor, or PC polling). | none |
| D7 | Approve a new Loop A LIVE stream for the proof: policy with a current expiry, owner takeover from SEMI_AUTO, budget slots 7–8 for task plus corrective. | no LIVE stream |

## 5. Safe work done that does not depend on these decisions

Batches 6–8: route guard v2 wired into dispatch; CLI read-only transport;
Loop 139 settled over the CLI; full suite 1975 OK; exact-head CI green on
`c840e3a`.
