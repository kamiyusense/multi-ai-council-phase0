# Relay Antigravity initialize-only probe (STATIC code; no run approved)

> **撤回済み（2026-10-23）**: the Antigravity route was withdrawn from the Relay for terms reasons. Do not run these steps. The launch code is archived and disabled in `archive/antigravity_launch/`; see `docs/RELAY_TOWER_DIRECTION_V4.md` §4.

Status: code and tests only. **No Antigravity binary was downloaded or run, no login, no model turn.** Running it on the real binary is a separate human approval (see "Human-only steps").

## What it is

`python -m relay.antigravity_initialize_probe --binary <path to agy_acp_server> --expected-sha256 <64 hex> --state-dir <empty dir>` (module `src/relay/antigravity_initialize_probe.py`).

It starts the human-supplied official binary once with the registry launch arguments, sends exactly one ACP `initialize`, records classifications, and stops. It never sends `authenticate`, `session/new` or `session/prompt`, so no login and no model turn can happen. This is step 2 of the order already suggested in `docs/RELAY_REMAINING_LIVE_DECISIONS_PREP.md` item 3 ("record the binary hash and version, run `initialize` only").

## What it records (terminal receipt, no secrets)

Binary SHA-256 and size, platform, ACP protocol version, agent name/version, the list of offered auth method ids (for example `oauth-personal`, `gemini-api-key`), boolean capability flags, and zero counts for authenticate/session/prompt/generation/retry, with fallback disabled. It does not record the selected or logged-in account, billing, environment values or any text from the server beyond name/version.

## Guards

- The binary must have the registry file name for the platform and match the expected SHA-256 that the human copied from their own download; mismatch stops before any prompt.
- Typed approval `APPROVE_ANTIGRAVITY_INITIALIZE_PROBE <first 7 hex of the SHA-256>`, entered on an interactive console (no console, no approval).
- One-shot: `consumed` file (O_EXCL) is written before the process starts; a receipt makes a later run a NO-OP; consumed without receipt is UNKNOWN and never re-run.
- Environment passed to the binary is the minimal inherited set; Gemini/Google API-key, ADC and Vertex variables are not passed (tested).
- No retry, no relaunch, no fallback; 20 s timeout.

## Human-only steps (not done)

Download the official `agy_acp_server` for the PC (accepting Google's terms), compute its SHA-256 and keep it, then type the approval on the PC console. A Google login and choosing `oauth-personal` come later and are separate decisions.

## What it does not show

It does not prove which Google account or billing route would be used, does not give a one-generation gate for Google, and does not test `session/new` (which returns `-32000 Authentication required` without a selected method). Those stay `BLOCKED_UNKNOWN` (`docs/RELAY_ANTIGRAVITY_ACCOUNT_ROUTE_READONLY_CHECKLIST.md`).

## Limits found in inspection (UNKNOWN, cannot be stopped by this code)

The binary inherits `APPDATA`/`LOCALAPPDATA`/`HOME`, so it may read its own saved login or settings and may make its own start-up network calls (for example an update check). The file could in theory be swapped between the hash check and the launch (local access only). Neither changes what the probe sends, but both are why the first run is a human decision.

## Evidence

Tests: `tests/relay/test_antigravity_initialize_probe.py` (10 tests, fake ACP server script only; skipped on Windows because the fake is a POSIX script). Local run `PYTHONPATH=src python3 -m unittest discover -s tests -t .`: 963 tests OK (23 skipped). The `offline-validation` PR check does not run `tests/relay`, so this evidence is a local run.
