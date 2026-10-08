# Batch 7 (2026-10-08 JST): route guard in the dispatch path, Jules Tools CLI transport

User decisions recorded on 2026-10-08:

* D1: the `JULES_API_KEY` / `X-Goog-Api-Key` REST route is **not**
  subscription-confirmed. It counts as API-key auth with unknown billing, so
  provider execution over it is a hard stop. STATIC work continues.
* D2: reads of an existing Jules session are approved to run automatically,
  under these conditions:
  * no API key, no metered / overage / credits, no billing-route change;
  * no new session, no provider POST, no new model turn;
  * correlation is checked, and a request that already has a terminal receipt
    is a NO-OP.

  Bounded retry is allowed for these reads.
* D3: `settle-dfcd5c4061f53c45-a1.json` over REST is not approved. Investigate
  the Jules Tools CLI / account-login route first.

No Jules call, no provider POST, no new session, no Merge, no force push, no
change to billing, permissions or secrets in this batch.

## 1. Jules Tools CLI: facts and UNKNOWN

| Item | Finding |
|---|---|
| Installed locally | **No.** No `jules` on the Windows or WSL PATH and no `~/.jules*`. Node/npm exist on Windows (`C:\Program Files\nodejs`). |
| Install | `npm install -g @google/jules` (official reference, jules.google/docs/cli/reference). Downloading and running a package is a human-approved action. |
| Auth | `jules login` opens a browser for Google sign-in, which is a human action; `jules logout`. The reference names no API key and no environment variable. One third-party note mentions a `JULES_TOKEN` variable; that is unverified. |
| Read commands | `jules version`, `jules remote list --session`, `jules remote list --repo`. |
| Commands that create or write | `jules remote new` creates a session (`--parallel` creates several). The interactive TUI (`jules` with no arguments) offers guided creation. `jules remote pull --session <id>` writes code locally. |
| Output format | Not documented: no JSON flag, and no command to show one session's state or PR. |
| Billing of CLI use | UNKNOWN. Account login does not by itself prove subscription-only billing. |

So with the CLI as it is today, the following are UNKNOWN until a real
output sample is recorded:

* whether Loop 139's session (`12043323850985900453`) can be read with the CLI;
* whether its listing shows state, PR or completion.

## 2. Route guard v2 (`claude_jules_provider_route.py`)

Authentication and billing are now separate facts:

* `auth_class`: `ACCOUNT_OAUTH` / `REST_API_KEY` / `UNKNOWN`
* `billing_class`: `SUBSCRIPTION_CONFIRMED` / `METERED_CONFIRMED` /
  `OVERAGE_CONFIRMED` / `BILLING_UNKNOWN`

The summary verdict is one of `ACCOUNT_OAUTH_CONFIRMED`, `REST_API_KEY`,
`METERED_CONFIRMED`, `OVERAGE_CONFIRMED`, `AUTH_BROKEN` or `UNKNOWN_ROUTE`. The
declaration now names a `transport`, and a declaration for another transport
gives `UNKNOWN_ROUTE`.

| verdict | `READ_ONLY_LIVE` | `SUBSCRIPTION_MODEL_WORK` | `LOCAL_STATIC` |
|---|---|---|---|
| ACCOUNT_OAUTH_CONFIRMED | ALLOW (D2) | ALLOW only with `SUBSCRIPTION_CONFIRMED` billing, else STOP_PROVIDER | ALLOW |
| REST_API_KEY | HARD_STOP (D1) | HARD_STOP | ALLOW |
| METERED / OVERAGE | HARD_STOP | HARD_STOP | ALLOW |
| AUTH_BROKEN | STOP_PROVIDER | STOP_PROVIDER | ALLOW |
| UNKNOWN_ROUTE | STOP_PROVIDER | STOP_PROVIDER | ALLOW |

`PAID_OR_UNKNOWN_PROVIDER` is never automatic. An unknown operation kind or
verdict is a HARD_STOP. Batch 6's verdict names are superseded by this table.

## 3. Guard wired into the real dispatch path

* `ClaudeJulesDispatcher(provider_route=...)` checks the gate for
  `SUBSCRIPTION_MODEL_WORK` twice:
  * in `preflight`, before the intent, claim, work branch or budget slot is
    written;
  * again right before the irreversible carrier command and the budget slot.

  If the route changed in between, nothing irreversible is written. A
  resolver that raises is never a pass. Every block is
  `PREPARED_NOT_AUTHORIZED` with nothing written.
* `ClaudeJulesAutoLoop(provider_route=...)` passes the resolver through.
* Production entry points always install the guard:
  * `claude_jules_live.build_live`: new `--provider-route <declaration.json>`
    option; when it is absent the route is `UNKNOWN_ROUTE`.
  * `claude_jules_lane_proof_launcher.build_live_proof_ports`: new
    `provider_route_declaration` argument.

  Both use the transport `carrier-rest-api-key`, which is the transport new
  Jules work actually uses today. Under D1 any dispatch through them is
  stopped before a write.
* Tests built directly on the fake world keep `provider_route=None`, the
  legacy behaviour. All 1926 earlier tests still pass unchanged.

## 4. New: CLI read-only transport (`claude_jules_cli_transport.py`)

* `command_allowed` allows exactly `version`, `remote list --session` and
  `remote list --repo`. It refuses before any process starts: no arguments
  (TUI), `remote new`, `--parallel`, `login`, `logout`, `remote pull`, and any
  other argument.
* `sanitized_env` removes every variable whose name contains `API_KEY`,
  `TOKEN`, `SECRET`, `CREDENTIAL` or `PASSWORD`, plus
  `GOOGLE_APPLICATION_CREDENTIALS`. The CLI therefore cannot fall back to a key.
* `run_read` retries reads that failed or timed out. It makes at most 4
  attempts with backoff 0 / 15 / 60 / 180 s and logs every attempt. A missing
  CLI is `UNAVAILABLE` and is not retried.
* `find_session` reports only whether the exact session id appears once as a
  whole token (`FOUND` / `NOT_FOUND` / `AMBIGUOUS`). State and PR stay
  `UNKNOWN` until a recorded output sample lets a parser be fixed against it.

## 5. Loop 139

Not settled. The CLI is not installed and not logged in, and the REST route is
not approved (D1/D3). Nothing was sent. The prepared request is unchanged and
still unsent. Loop 139 stays non-terminal, with dispatch receipt `DISPATCHED`
and PR #322 open at `adbd5de`.

## 6. Validation

| Check | Result |
|---|---|
| Focused: route guard + wiring + CLI transport | `Ran 35`, OK |
| Full regression (WSL, Python 3.14.4) | `Ran 1961`, `OK (skipped=1)` |
| compileall / `git diff --check` | OK / OK |

## 7. Next human actions (true blockers)

1. Install and log in to the CLI on this PC; both need a browser and a
   download:
   * `npm install -g @google/jules`
   * `jules login`
2. Then the read-only steps run automatically under D2:
   * `jules version` and `jules remote list --session` through `run_read`;
   * record one output sample;
   * fix the parser against the sample;
   * if the session is FOUND with a terminal state, record a settlement
     receipt for Loop 139.
3. Before any new model work over the CLI, write a
   `PROVIDER_ROUTE_DECLARATION_V1` for the `jules-tools-cli` transport with
   billing evidence. Without that evidence new model work stays
   `STOP_PROVIDER`.
