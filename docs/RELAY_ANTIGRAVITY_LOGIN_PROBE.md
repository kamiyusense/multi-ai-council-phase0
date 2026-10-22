# Relay Antigravity login-only probe (STATIC code; no run approved)

> **撤回済み（2026-10-23）**: the Antigravity route was withdrawn from the Relay for terms reasons. Do not run these steps. The launch code is archived and disabled in `archive/antigravity_launch/`; see `docs/RELAY_TOWER_DIRECTION_V4.md` §4.

Status: code and tests only (fake server). **No login, no model turn, no Antigravity run happened.** Running it on the real binary is a separate human approval typed on the PC console.

## What it is

`python -m relay.antigravity_login_probe --binary <agy_acp_server> --expected-sha256 <64 hex> --state-dir <empty dir>` (module `src/relay/antigravity_login_probe.py`).

It starts the human-supplied official binary once, sends ACP `initialize`, then (only if `oauth-personal` is offered) exactly one `authenticate` with `methodId: oauth-personal`, and stops. The sign-in happens in the human's own browser; this code never sees what is typed there. It never sends `session/new` or `session/prompt`, so no model turn can happen. `oauth-personal` is the only method Relay's `antigravity_route_admission` allows; the other three offered by 1.4.0 are never sent.

Purpose: the account route (which Google account class signs in) cannot be observed without a sign-in (`docs/RELAY_ANTIGRAVITY_ACCOUNT_ROUTE_READONLY_CHECKLIST.md`). This is the smallest step that signs in and nothing more.

## Guards

- Same binary checks as the initialize probe (registry file name, SHA-256 equal to the human-supplied value, mismatch stops before any prompt; the shared check is `_preflight_binary`).
- Typed approval `APPROVE_ANTIGRAVITY_LOGIN_ONLY <first 7 hex of the binary SHA-256>` on an interactive console; the phrase of the initialize probe is rejected.
- One-shot: `consumed` file (O_EXCL) is written before the process starts; a receipt makes a later run a NO-OP; consumed without receipt is UNKNOWN and never re-run.
- Environment: minimal inherited set; Gemini/Google API-key, ADC and Vertex variables are not passed.
- `authenticate` sent once, 300 s limit for the human to sign in; no retry, no relaunch, no fallback.

## Receipt (classifications only)

Binary hash/size, platform, agent name/version, offered auth method ids, `authenticate_state` (`AUTHENTICATE_OK`, `AUTHENTICATE_FAILED`, `AUTHENTICATE_TIMEOUT`, `METHOD_NOT_OFFERED`, `NOT_SENT`), error class, and counts (authenticate 0 or 1; session/new, prompt, generations, retry 0; fallback disabled). It records no account id, e-mail, token, URL or server text (tested with a fake server that returns an e-mail address).

## What it does not show, and risks (UNKNOWN)

- Does not prove the billing route or give a one-generation gate for Google; both stay `BLOCKED_UNKNOWN`.
- Where the server stores the login and whether it persists after the run is UNKNOWN; a successful sign-in is an account-side effect on the owner's PC that this code cannot undo (the owner can remove it in their Google account / Antigravity settings).
- What `authenticate` does inside the real 1.4.0 server (browser flow, any plan/quota enrolment) is UNKNOWN until the owner runs it.
- The file could in theory be swapped between the hash check and the launch (local access only).

## Evidence

Tests: `tests/relay/test_antigravity_login_probe.py` (fake ACP server only; skipped on Windows because the fake is a POSIX script) plus the existing initialize-probe tests after the small `_preflight_binary` split. Local run `PYTHONPATH=src python3 -m unittest discover -s tests -t .`: 989 tests OK (23 skipped). The `offline-validation` PR check does not run `tests/relay`, so this evidence is a local run.
