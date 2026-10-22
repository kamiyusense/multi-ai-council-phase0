# Relay Antigravity login-only probe: result record (2026-10-16)

> **撤回済み（2026-10-23）**: the Antigravity route was withdrawn from the Relay for terms reasons. This result is kept as evidence only. The launch code is archived and disabled in `archive/antigravity_launch/`; see `docs/RELAY_TOWER_DIRECTION_V4.md` §4.

Status: the one-shot login-only probe ran once on the owner's PC and ended `LOGIN_PROBE_DONE` with `AUTHENTICATE_OK`. Documentation only: no code, registry, workflow or settings change. A second run is a NO-OP.

## What ran

- Tool: `python -m relay.antigravity_login_probe` (`antigravity-login-probe-v1`, #440, independently inspected before the run) on the owner's Windows PC, binary `agy_acp_server.exe` 1.4.0 (SHA-256 `2aa1897144a60aaa1b8b54fc0595511ac6e6ce0cf2a7b3166cb1d0e4d4005ab8`, checked by the probe against the owner-supplied value), state dir `$HOME\agy-login-state`.
- Approval: typed by the owner on the PC console (`APPROVE_ANTIGRAVITY_LOGIN_ONLY 2aa1897`). An AI does not type approval lines on the PC.
- Account: the owner signed in in their own browser with the personal Google account that holds Google AI Pro (the owner's choice; the account identity is not recorded here or in the receipt). The browser showed "Authentication successful" on the local callback page (seen in the owner's screenshot).

## Result (terminal receipt, read on the PC)

| Field | Value |
|---|---|
| terminal_state | `LOGIN_PROBE_DONE` |
| authenticate_state / method | `AUTHENTICATE_OK` / `oauth-personal` |
| agent_version | `1.4.0` |
| error_class | (none) |
| authenticate_count | 1 |
| session_new / prompt / model_generations / retry | 0 / 0 / 0 / 0 |
| timestamp | 2026-10-16T07:06:10Z |
| receipt_sha256 | `1e5425d935911529b8d8c9432824080577c48bb2e526b80517ecb60fe9969fe1` |

The receipt file stays on the owner's PC (`$HOME\agy-login-state`). The values above were read from the owner's console screenshot.

## What this shows and does not show

- Shows: the official 1.4.0 ACP server accepted one `authenticate` with `oauth-personal` after a browser sign-in, with no model turn, no `session/new`, no retry.
- Does not show: which billing route a later turn would use (still `BLOCKED_UNKNOWN`), a one-generation gate for Google, where the server stores the login or whether it stays after the run (UNKNOWN; the PC's Antigravity may now be signed in), or that a real turn works.
- Account route: the receipt records no account class, so `antigravity_account_route` stays unproven by this alone; the owner's statement is that the AI Pro account was used.
- Next steps stay separate owner decisions: the pin bump 1.2.1 to 1.4.0, any `session/new`, and any model turn (needs a one-generation boundary and billing evidence first).
