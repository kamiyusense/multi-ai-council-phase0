# Relay: remaining human decisions — pre-staged facts and plans (2026-10-05; nothing executed, nothing changed)

Docs only. No pin, runner, workflow or runtime file is changed here. Everything below stays a human decision; this page only removes the research cost.

## 1. Pin bump (Codex ACP 2.1.0 -> 2.1.1, Claude ACP 0.84.0 -> 0.85.1, Antigravity 1.2.1 -> 1.3.0)
Public facts (ACP registry clone at `c1ff2a7`, 2026-10-05; npm): `codex-acp` 2.1.1, `claude-acp` 0.85.1, `antigravity-acp` 1.3.0 (proprietary, binary only).
Trial in a scratch checkout (official packages installed with `--ignore-scripts`, nothing committed or pushed), with the matching official adapters present:
- **Claude 0.85.1:** `policy.py` pin + three test fixtures that hard-code the old version strings (`test_live_readiness_pipeline`, `test_provider_adapters`); the env-gated adapter tests (`test_claude_acp_static_boundary`, `test_claude_auth_status_notification`) did not fail with 0.85.1 installed. Consistent with the earlier finding that `auth-status.js` / `modes.js` are identical.
- **Codex 2.1.1:** the same plus `ADAPTER_VERSION = "2.1.0"` in `src/relay/m9_codex_first_live.py` (the first-LIVE runner verifies the installed adapter version; with 2.1.1 installed, six full-flow tests in `test_m9_codex_first_live` fail until that constant changes) and `test_acp_stdio_relay_transport` (`assertEqual(... "2.1.0")`). Touching the M9 runner is a decision for the human; the first-LIVE approval it guards is consumed.
- Carrier workflows hard-code `codex-acp 2.1.0`; they live on the carrier branch and would need their own change.
- **Antigravity 1.3.0:** cannot be tested without downloading the proprietary binary (Google terms) -> keep 1.2.1 until the human decides on item 3.
Recommendation: bump Claude alone first (smallest, policy + fixtures); Codex only together with the M9 constant and the carrier workflow change; Antigravity with item 3.

## 2. Path B (Relay ACP adapter inside the gated container)
What exists: gated container path (Gate, `claude` launcher, seccomp) proven twice on the human's WSL machine; Relay route admission, #301 mid-turn cancel, `ClaudeStaticDispatcher`.
What would be built: a runtime image with pinned `@agentclientprotocol/claude-agent-acp` behind the Gate; a verified launch seam in `AcpStdioStaticTransport` (currently closed for Claude, `UNKNOWN / LIVE_BOUNDARY`); a one-shot approval/consumed/terminal state like `m9_live_state` (generalized, not copied); `_FORBIDDEN_ENV` currently forbids `ANTHROPIC_BASE_URL`, which the Gate path requires, so the contract needs a reviewed exception.
Not testable here (no Docker daemon in the cloud session). What it would add: `_auth/status_update` and the mid-turn cancel observed on a real adapter. Open design questions: how the adapter reaches the Gate (base URL env through the adapter's own option), how the Gate admission interacts with adapter title-generation turns, and how `--allow-dangerously-skip-permissions` is kept off (`_meta` no-bypass, tested STATIC).
Human-only: approval to build, Docker on the machine, a fresh login if the token is revoked, one explicit run approval.

## 3. Antigravity LIVE
Public facts only (registry): `agy_acp_server` 1.3.0 from `dl.google.com` archives (`.zip`; Linux needs `--uid=`; Windows `agy_acp_server.exe`); registry lists no checksum (UNKNOWN). `initialize` lists auth methods (`oauth-personal`, `oauth-business`, `gemini-api-key`, `agent-platform`); selection is `auth.type` in the server settings or `authenticate`; no identity push found; `session/new` without a selection returns `-32000 Authentication required`. STATIC admission already on main (`antigravity_route_admission`, `AntigravityStaticDispatcher`).
Human-only steps: download and run the proprietary binary (accepts Google terms), Google login, choose `oauth-personal`. Not built: mid-turn cancel and a one-generation gate for Google (UNKNOWN). Suggested order after approval: record the binary hash and version, run `initialize` only (no model), then one `session/new` without prompt, then stop and decide.

### Update 2026-10-15: registry now lists Antigravity 1.4.0; download facts (nothing run)
- ACP registry (`cdn.agentclientprotocol.com/registry/v1/latest/registry.json`, read 2026-10-15): `antigravity-acp` **1.4.0** (repo pin stays 1.2.1; a bump is still a human decision with item 3). Windows x86_64 archive `https://dl.google.com/agy-extensions/releases/windows/agy-acp-server-1.4.0-windows-x86_64.zip`; license `https://antigravity.google/terms` (accepting it is the owner's).
- The zip was downloaded once in the cloud container and **not executed**: zip SHA-256 `d737aad2d6388e071bc907db415c129a256915d275f436e68f10dcdf6af896da` (125,646,049 bytes); `agy_acp_server.exe` SHA-256 `2aa1897144a60aaa1b8b54fc0595511ac6e6ce0cf2a7b3166cb1d0e4d4005ab8` (82,245,832 bytes); the zip also holds `localharness_external.exe` (SHA-256 `a5170ff005636b5e3fedbcb0f61fa3204a2789c19ef38dfc424ec884a98e80f9`, 146,036,888 bytes; purpose UNKNOWN). The registry itself lists no checksum, so these hashes are only a cross-check between two downloads.
- The ACP server is a separate component from the Antigravity app/IDE; whether an installed app contains the same server or shares its saved login is UNKNOWN.
- Next read-only step is the initialize-only probe (`docs/RELAY_ANTIGRAVITY_INITIALIZE_PROBE.md`), with the owner typing the approval.

### Update 2026-10-21: Antigravity steps taken since (all owner-approved, each once)
- Pin: `ANTIGRAVITY_POLICY` is now 1.4.0 (#448). The 1.2.1/1.3.0 lines above are history; the Claude 0.85.1 and Codex 2.1.1 pins also landed (#315, #400).
- initialize-only probe: `INITIALIZE_OK` (`docs/RELAY_ANTIGRAVITY_INITIALIZE_PROBE_RESULT_20261015.md`). login-only probe: `AUTHENTICATE_OK` with `oauth-personal` (`docs/RELAY_ANTIGRAVITY_LOGIN_PROBE_RESULT_20261016.md`). one-turn runner: `ONE_TURN_DONE`, one prompt, expected answer (`docs/RELAY_ANTIGRAVITY_ONE_TURN_RESULT_20261020.md`).
- Still open and human-only: running Antigravity through the Relay dispatch path itself (the three probes are separate one-shot tools, not the Relay adapter), the billing route (rests on the owner's declaration), a one-generation boundary for Google, login persistence, and any further turn.
