# Relay official-ACP thin integration — STATIC evidence

Base: current main `25a64885ae64c8bc04065e07caaeb9a30ce3c86d` (fresh fetch). Baseline `tests/relay`: 801 tests OK.

## What was added
- `src/relay/acp_stdio_relay_transport.py`: `AcpStdioStaticTransport`, a sync `RelayTransport` that connects the existing `RelayLifecycle` to the existing `acp_mock_text_update_wire` + `acp_mock_text_to_phase0_raw`. One request = one child = one prompt. Launches only an injected fake/local command; official adapter names (`codex-acp`, `claude-agent-acp`, `agy_acp_server*`, `antigravity-acp`, `@agentclientprotocol/*`, profile `binary_name`) are refused (fail closed).
- `tests/relay/test_acp_stdio_relay_transport.py`: 10 tests (3-provider E2E, duplicate/conflict, stop, timeout, malformed/non-end_turn, isolation, second prompt, live-launch refusal, Claude no-bypass meta).
- No change to dispatcher, lifecycle, Claude Admission Gate, Core, Signal, Blue, Auto Loop.

## M1 decision
A (keep stdlib `acp_stdio_transport`) over B (adopt SDK): PyPI stable `agent-client-protocol` is `0.12.1` (== existing pin); only `1.0.0rc1/rc2` are newer (prerelease, not adopted). Adopting the SDK adds a dependency without removing needed code. B not pursued; not a redesign block.

## Upstream version table (compatibility first)
| Item | Inspected | Phase 0 pin | Decision |
|---|---|---|---|
| ACP Python SDK (PyPI) | stable 0.12.1, pre 1.0.0rc2 | 0.12.1 (docs only) | keep |
| codex-acp (npm, Apache-2.0) | latest 2.1.1, preview 2.1.2-preview.1 | 2.1.0 | keep (no launch contract exercised; no evidence needing 2.1.1) |
| claude-agent-acp (npm, Apache-2.0) | latest 0.85.1 | 0.84.0 | keep (same reason) |
| antigravity-acp registry | UNKNOWN (GitHub repo outside this session's scope) | 1.2.1 | keep / UNKNOWN |
| acp-tck | UNKNOWN (not readable; experimental per task text) | - | NOT_RUN |

## Results
- M1 PASS (static, fake agent). M2/M3/M4: PASS only for "profile + Relay seam hosts an ACP stdio child with a fake agent"; official adapter launch/session contract = UNKNOWN / BLOCKED_UPSTREAM (not launched; would risk real provider process).
- M5 ACP-TCK: BLOCKED / NOT_RUN. M6: UNKNOWN / BLOCKED_UPSTREAM_VISIBILITY. M7: PASS for static 3-provider via lifecycle with fake agent (not through official adapters). M8+ not touched.
- Claude Admission Gate untouched; no bypass route added.

## No-LIVE
live provider/model execution NO; Codex/Claude/Antigravity turns 0 (only a local python fake agent process was spawned); API-key route NO; retry/fallback added NO; billing/settings/secrets NO; main write NO; merge NO. Historical PRs #196/#210/#211/#213/#218/#223/#224: DEFERRED (not checked individually this session; ALREADY_IN_MAIN per task note, unverified here).
