# Batch 6 (2026-10-08 JST): PC verification, carrier sync, billing route guard

Writes in this batch: one carrier workflow commit (user-approved), this branch's
commit. No Jules GET, no Jules session, no provider/model call, no Merge, no
force push, no owner/budget/permission/secret change.

## 1. PC verification of #330 (WSL2 Ubuntu 26.04, Python 3.14.4)

Clone `~/pcverify-330` at #330 head `d7427cb` (tree `2769010`), LF checkout.

* First run without `jq`: every readback step exited 127 before any call, so
  the probe said `NOT_ONE_GET` for main and carrier alike. That was the PC,
  not the workflow. The user installed `jq 1.8.1` and later `python-is-python3`.
  The step calls `python`, which a stock WSL Ubuntu does not have.
* With both installed: probe main `a4f0189` = `ONE_GET_CONFIRMED`; carrier
  `3672250` = `NOT_ONE_GET` (1/1 GETs for `false`, invalid values pass with 2
  GETs). Focused 73 OK; full `Ran 1926`, `OK (skipped=1)`; compileall and
  diff-check OK. Same counts as Actions run 37649836308.

## 2. Carrier sync (approved by the user for this change only)

* Built without a working tree (no line-ending conversion): parent `d5baadc`,
  tree `7ad5115`, commit `38e92c776e7c1bb090444ec8f13c7ce94a9baf06`.
  The only change is `M .github/workflows/jules-session-readback.yml`, blob
  `3672250` → `a4f0189`; the diff is byte-identical to the proposal patch.
* Pushed once, fast-forward `d5baadc2..38e92c77`, no force.
* Readback: carrier `38e92c7` (API and fetch); blob `a4f0189` (git and Contents
  API) equals main; commits API lists one modified file; runs for
  `head_sha=38e92c7`: 0; carrier runs created after the push: 0; `settle-*`
  requests: 0; main `8fbbef9` and data branch `5227589` unchanged.
* Probe on the synced carrier: `ONE_GET_CONFIRMED`. `false` gave 1 session GET
  and 0 activities GETs; 8 invalid values gave 0 calls and rc 5; a failing
  session GET gave 1 call and rc 22, with no retry. No sentinel leaked.

## 3. Loop 139 settlement: prepared, not sent (billing route boundary)

`settle-dfcd5c4061f53c45-a1.json`, recomputed against the synced carrier, has
the same path and content as before. It means one session GET of
`12043323850985900453`. The carrier has no `settle-*` file and the data branch
has no settlement record.

It was **not** published. The readback step authenticates with
`X-Goog-Api-Key: ${JULES_API_KEY}`. The route decision
(`docs/JULES_API_ROUTE_DECISION_20260925.md` §4.6) records Jules REST billing as
`PROBABLY_SAFE_BUT_NOT_EXPLICITLY_GUARANTEED`. The batch instructions make an
API-key route and an unconfirmed billing route a hard stop for provider
execution, and say not to infer SAFE. The GET therefore waits for decision D1.

## 4. New: provider / billing route guard (`claude_jules_provider_route.py`)

* `classify_route(declaration, provider, now)` reads a digest-bound
  `PROVIDER_ROUTE_DECLARATION_V1` record (provider, auth method, billing route,
  auth state, declarer, evidence, validity window). It returns one of
  `SUBSCRIPTION_CONFIRMED`, `API_KEY_CONFIRMED`, `METERED_CONFIRMED`,
  `OVERAGE_CONFIRMED`, `UNKNOWN_BILLING_ROUTE` or `AUTH_BROKEN`.
  * A missing, tampered, malformed, expired, not-yet-valid or foreign record is
    `UNKNOWN_BILLING_ROUTE`.
  * API-key authentication is never `SUBSCRIPTION_CONFIRMED`.
* `gate(operation, route)` checks one operation kind against the verdict:
  * `LOCAL_STATIC` work is always `ALLOW`, whatever the route says.
  * `READ_ONLY_LIVE` and `SUBSCRIPTION_MODEL_WORK` are allowed only on
    `SUBSCRIPTION_CONFIRMED`.
  * `AUTH_BROKEN` gives `STOP_PROVIDER`: provider execution pauses, safe work
    continues, and no human is needed.
  * Paid or unknown routes give `HARD_STOP` with `requires_human`. Provider
    execution stops and local work stays allowed.
  * `PAID_OR_UNKNOWN_PROVIDER` is never automatic.
  * An unknown operation kind or verdict fails closed.
* `detect_route_drift` flags any change in the verdict or the provider.
* 14 tests (`test_claude_jules_provider_route.py`). They include the current
  Jules route (API key, unconfirmed billing), which gives `HARD_STOP` for
  `READ_ONLY_LIVE`.
* The guard is not wired into dispatch yet. Wiring it in, with the user's route
  declaration, is D1.

## 5. Not done: read-only safe envelope (auto-publish of settlement GETs)

A pure decision module was drafted. It would answer `PUBLISH`, `NO_OP`, `WAIT`
or `STOP` for one prepared settlement request, from the route gate, preflight
blob, carrier state, duplicates and attempt cap. Creating that file was refused
by the session's auto-mode safety classifier, so it is not in this commit.
Removing the human approval from a provider call needs the user's explicit
decision and permission (D2).

## 6. Deferred decisions

| id | question | safe default | affected |
|---|---|---|---|
| D1 | Is the Jules API-key route (`X-Goog-Api-Key`) the subscription route? If so, write a `PROVIDER_ROUTE_DECLARATION_V1` with evidence and an expiry. | none: provider execution stays stopped | Loop 139 settlement GET; every Jules dispatch under the guard |
| D2 | May settlement GETs be published automatically inside a read-only envelope (existing session only, one GET, no activities, duplicate guard)? Needs a permission decision for this session. | ask per GET | unattended settlement |
| D3 | After D1: publish `settle-dfcd5c4061f53c45-a1.json` once. | not sent | Loop 139 terminal state |

## 7. Validation of this commit

| Check | Result |
|---|---|
| Focused `test_claude_jules_provider_route` | `Ran 14`, OK |
| Full regression (WSL, Python 3.14.4) | `Ran 1940`, `OK (skipped=1)` |
| compileall / `git diff --check` | OK / OK |

## 8. Counters

Jules GETs 0. New Jules sessions 0. Provider/model execution 0. Budget 6/10
(unchanged). Owner a-003 generation 2 (SEMI_AUTO, unchanged). Carrier writes:
one workflow-only commit. Merges 0. Force pushes 0.
