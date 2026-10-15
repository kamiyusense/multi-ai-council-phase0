# Relay Antigravity initialize-only probe: result record (2026-10-15)

Status: the one-shot probe ran once on the owner's PC and ended `INITIALIZE_OK`. Documentation only: no code, registry, workflow or settings change. A second run is a NO-OP.

## What ran

- Tool: `python -m relay.antigravity_initialize_probe` (`antigravity-initialize-probe-v1`, merged in #433) from a fresh clone of main on the owner's Windows PC (`agy-probe-run`).
- Binary: official `agy_acp_server.exe`, `antigravity-acp` 1.4.0 (ACP registry), extracted from the Windows x86_64 zip. Hashes were checked on the PC against the values recorded in `docs/RELAY_REMAINING_LIVE_DECISIONS_PREP.md` (update 2026-10-15, Draft #436): zip `d737aad2d6388e071bc907db415c129a256915d275f436e68f10dcdf6af896da` and exe `2aa1897144a60aaa1b8b54fc0595511ac6e6ce0cf2a7b3166cb1d0e4d4005ab8`, both full-length MATCH.
- Approval: typed by the owner on the PC console (`APPROVE_ANTIGRAVITY_INITIALIZE_PROBE 2aa1897`). An AI does not type approval lines on the PC.

## Result (terminal receipt, read on the PC)

| Field | Value |
|---|---|
| terminal_state | `INITIALIZE_OK` |
| platform / protocol_version | `windows` / 1 |
| agent_name / agent_version | `antigravity-acp` / `1.4.0` |
| auth_method_ids | `agent-platform`, `gemini-api-key`, `oauth-business`, `oauth-personal` |
| capability_flags | `{"loadSession": true}` |
| binary_sha256 | `2aa1897144a60aaa1b8b54fc0595511ac6e6ce0cf2a7b3166cb1d0e4d4005ab8` |
| authenticate / session_new / prompt counts | 0 / 0 / 0 |
| retry_count | 0 |
| timestamp | 2026-10-15T11:12:45Z |
| receipt_sha256 | `69ef42f7f830669a9a67e1f7deac389f8a7bf9a1e02100c38815553221e88378` |

The receipt file stays on the owner's PC (`$HOME\agy-probe-state`). The values above were read from the owner's console screenshots. After the run the console printed a Python `ResourceWarning` / `ValueError: I/O operation on closed pipe` traceback from asyncio's Windows pipe clean-up; it came after the receipt was written, and the receipt shows `INITIALIZE_OK`. The cause is not investigated (UNKNOWN); it looks like process-exit noise.

## What this shows and does not show

- Shows: the official 1.4.0 ACP server starts on the owner's PC and answers one `initialize` with the same four auth methods the repo already expected; the probe sent no `authenticate`, `session/new` or prompt, so no login and no model turn happened.
- Does not show: which Google account or billing route a later turn would use; a one-generation gate for Google; whether the server read a saved login or made start-up network calls (UNKNOWN, see "Limits found in inspection" in `docs/RELAY_ANTIGRAVITY_INITIALIZE_PROBE.md`); compatibility of the repo pin (1.2.1) with 1.4.0 beyond this initialize.
- Next steps stay separate owner decisions: bump the pin 1.2.1 to 1.4.0, choosing `oauth-personal`, any Google login, and any Antigravity LIVE turn.
