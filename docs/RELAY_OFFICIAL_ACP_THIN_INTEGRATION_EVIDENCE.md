# Relay official-ACP thin integration — STATIC evidence

Base: current main `7e1c90b72c7523f4265803da7ee82671c9dbd800` (fresh readback after PR #249 merged). This is the clean latest-main successor to Draft PR #252; only its three Relay files were ported, with no merge/rebase of the old branch.

## What was added
- `src/relay/acp_stdio_relay_transport.py`: `AcpStdioStaticTransport`, a sync `RelayTransport` that connects the existing `RelayLifecycle` to the existing `acp_mock_text_update_wire` + `acp_mock_text_to_phase0_raw`. One request = one child = one prompt.
- `tests/relay/test_acp_stdio_relay_transport.py`: 10 tests (3-provider fake-agent E2E, duplicate/conflict, stop, timeout, malformed/non-end_turn, isolation, second prompt, obvious live-adapter-name refusal, Claude no-bypass meta).
- No change to dispatcher, lifecycle, Claude Admission Gate, Core, Signal, Blue, Auto Loop.

Important limitation: the constructor still accepts a caller-supplied command. The marker check refuses known official adapter identities, but it is not a sandbox and does not prove that an arbitrary wrapper command could never launch another process. Therefore this seam is treated as a STATIC/test-only caller-controlled seam; the evidence does **not** claim that the class can make LIVE execution impossible by itself.

## M1 decision
A (keep stdlib `acp_stdio_transport`) over B (adopt SDK): the latest GitHub release inspected for the Python SDK is `v1.0.0rc2`; the last stable line visible before the RCs is `0.12.1`. Phase 0 keeps its existing stdlib transport rather than adding/replacing it merely because a newer prerelease exists. No broad redesign was performed.

## Upstream version table (compatibility first)
| Item | Fresh inspected state | Phase 0 pin/reference | Decision |
|---|---|---|---|
| ACP Python SDK | latest release `v1.0.0rc2`; stable line includes `0.12.1` | existing stdlib transport references `0.12.1`-era implementation | keep current transport; no prerelease migration |
| codex-acp (Apache-2.0) | package `2.1.1` | `2.1.0` | keep for now; no official launch contract exercised in this PR |
| claude-agent-acp (Apache-2.0) | package `0.85.1` | `0.84.0` | keep for now; no official launch contract exercised in this PR |
| antigravity-acp registry | `1.3.0`, Google-distributed `agy_acp_server.par/.exe`, proprietary license | `1.2.1` | keep for now; compatibility/update decision deferred |
| acp-tck | repository readable; experimental; v1 default, v2 Draft | none | safe fixture/subset is available, but NOT_RUN in this PR/review |

## Results
- **M1 PARTIAL**: the new class connects `RelayLifecycle` to the existing ACP stdio/mock wire and phase0 mapper with a local fake agent. It does **not** yet host an official ACP adapter/runtime, so the handover definition of M1 is not complete.
- **M2 Codex PARTIAL / M3 Claude PARTIAL / M4 Antigravity PARTIAL**: provider profiles and binary identities exist and the fake-agent seam exercises the same Relay lifecycle shape, but the official adapter launch/session contracts are still unexercised.
- **M5 ACP-TCK NOT_RUN**: official TCK is available and its bundled fixture can be used without a real provider, but no TCK execution result exists on this PR head.
- **M6 UNKNOWN / BLOCKED_UPSTREAM_VISIBILITY**: no verified machine-readable read-only account/quota path was added.
- **M7 PARTIAL**: 3-provider STATIC/mock lifecycle coverage exists through one fake ACP agent shape, but the handover target requires a path through the official adapters/servers (or an official-adapter-compatible injected boundary) before calling this milestone complete.
- M8+ not touched.
- Claude Admission Gate untouched; no bypass route added.

## Exact-head verification status
The predecessor PR #252 reported local `tests/relay` 811 OK, but this latest-main successor requires its own exact-head validation. Do not promote the predecessor result to PASS for the successor until a GitHub run/readback exists for this branch HEAD.

## No-LIVE
live provider/model execution NO; Codex/Claude/Antigravity turns 0 as reported by the originating batch; API-key route added NO; retry/fallback added NO; billing/settings/secrets mutation NO; main write NO; merge NO. Historical PR cleanup remains DEFERRED.
