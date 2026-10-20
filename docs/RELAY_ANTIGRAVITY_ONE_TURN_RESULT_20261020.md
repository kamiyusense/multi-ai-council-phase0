# Relay Antigravity one-turn run: result record (2026-10-20)

Status: the one-shot one-turn runner (#446) ran once on the owner's PC and ended `ONE_TURN_DONE` with the expected answer. Documentation only: no code, registry, workflow or settings change. A second run is a NO-OP (approval consumed).

## What ran

- Tool: `python -m relay.antigravity_one_turn` (`antigravity-one-turn-v1`, merged in #446, independently inspected before the run) on the owner's Windows PC, binary `agy_acp_server.exe` 1.4.0 (SHA-256 `2aa1897144a60aaa1b8b54fc0595511ac6e6ce0cf2a7b3166cb1d0e4d4005ab8`, checked by the tool against the owner-supplied value), state dir `$HOME\agy-one-turn-state`.
- Owner route declaration (`declare`, typed by the owner on the PC console): personal Google account, subscription billing, bound to the binary hash, valid 4 hours. Evidence note recorded in the declaration: the owner's statement of 2026-10-20 that extra paid usage is OFF and that the usage-window cap has been reached and has stopped usage many times. The declaration is the owner's statement; code cannot verify it.
- Approval: `APPROVE_ANTIGRAVITY_ONE_TURN 2aa1897` typed by the owner on the PC console. An AI does not type approval lines on the PC.
- Steps sent once each: `initialize`, `authenticate` (`oauth-personal`), `session/new`, one fixed harmless prompt asking for the six characters `AGY_OK` with no tools. No answer text is stored; only length, hash and a match flag.

## Result (terminal receipt, read on the PC)

| Field | Value |
|---|---|
| terminal_state / stage_reached | `ONE_TURN_DONE` / `DONE` |
| stop_reason | `end_turn` |
| agent_version | `1.4.0` |
| auth_method_ids offered | `agent-platform`, `gemini-api-key`, `oauth-business`, `oauth-personal` (only `oauth-personal` is used) |
| error_class | (none) |
| authenticate / session_new / prompt / retry | 1 / 1 / 1 / 0 |
| response_chars / response_was_expected | 6 / true |
| fallback_state | `disabled` |
| timestamp | 2026-10-20T03:40:20Z |
| declaration_sha256 | `9fef62fed2197b398e5905e2e0f78df2b8cce0ea3c0ca8cb20f1a4e6c6b6c3f9` |
| response_text_sha256 | `1f6bf42369ac748e94e8540818f6438e439cea6b88a6a4c715bdcdf50bf52959` |
| receipt_sha256 | `1fcdd4e3e900afbabf1225bfa9869302a92cdd403050952690cb8595f1c1dabe` |

The receipt stays on the owner's PC. Values were read from the owner's console screenshot. After the run the console printed asyncio "I/O operation on closed pipe" noise during interpreter shutdown (same as the initialize probe); the receipt shows it did not affect the result.

## What this shows and does not show

- Shows: the official 1.4.0 ACP server, signed in through the earlier login-only probe, accepted `authenticate` again, opened a session and answered one prompt exactly as asked, with one prompt sent and no retry or fallback. The Relay adapter path (initialize, authenticate, session/new, prompt) works against the real binary.
- Does not show: the billing route (the declaration is the owner's statement; a billing or usage page check is the owner's to do), how many model calls Google made inside the single prompt (UNKNOWN), whether the saved login persists, behavior with tool requests or longer turns.
- Next steps stay separate owner decisions: the pin bump 1.2.1 to 1.4.0, any further turn, and any registry/promotion change.
