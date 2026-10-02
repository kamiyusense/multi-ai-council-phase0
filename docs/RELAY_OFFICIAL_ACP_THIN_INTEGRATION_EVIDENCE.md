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


---

# Update 2 — official-adapter contract audit + lifecycle mapping (STATIC)

Base: main `7e1c90b72c7523f4265803da7ee82671c9dbd800`; this update is on top of #255 head `79d9bf2b6b6dd820ec2e49c8f64e30b4dc3ec3a6`. Milestone verdicts follow the Reviewer scale (no promotion to PASS).

## Upstream inspected (read-only)
| Repo | Commit / version | License | Notes |
|---|---|---|---|
| agentclientprotocol/codex-acp | `ca1d971`, package 2.1.1 | Apache-2.0 | npm 2.1.0 and 2.1.1 both exercised |
| agentclientprotocol/claude-agent-acp | `a44c486`, package 0.85.1 | Apache-2.0 | not launched |
| agentclientprotocol/registry | `2e432ea`, antigravity-acp 1.3.0 | proprietary (Google) | manifest read only; binary NOT downloaded |
| agentclientprotocol/acp-tck | `fa00ccd`, 0.2.0 (experimental, v1 default) | Apache-2.0 | requires Python >= 3.14 |

Pins unchanged (compatibility first): codex 2.1.0, claude 0.84.0, antigravity 1.2.1. Codex 2.1.0 and 2.1.1 showed identical behavior in the fixture lifecycle test, so there is no compatibility reason to bump yet.

## Contracts found
- **Codex** (`node dist/index.js`, newline-delimited JSON-RPC on stdio). It spawns `<CODEX_PATH> app-server` (`src/CodexJsonRpcConnection.ts`); `CODEX_PATH` is a documented option, so a fixture can replace the whole backend and the bundled Codex is never run. ACP calls reach the backend as: initialize -> `initialize`,`config/read`; session/new -> `account/read`,`config/read`,`thread/start`,`model/list`,`skills/list`; session/prompt -> `turn/start`; session/close -> `thread/unsubscribe`/`thread/archive`. `initialize` advertises authMethods `api-key` and `chat-gpt`; Phase 0 never authenticates.
- **Claude**: `claude-agent-acp`; `CLAUDE_CODE_EXECUTABLE` can replace the CLI, but `query()` spawns that CLI as soon as a session is created, and no static fake CLI exists. => **UNKNOWN / LIVE_BOUNDARY** (not launched). Admission Gate untouched; `allowDangerouslySkipPermissions=False` unchanged.
- **Antigravity**: proprietary Google binary (`./agy_acp_server.par`, linux args `--uid=`; `.exe` on Windows); no fake/no-provider mode documented. => **UNKNOWN / LIVE_BOUNDARY** (not downloaded or launched). No code copied.

## Finding needing a human decision (Deferred Decision)
Official `codex-acp` starts a fire-and-forget **title-generation turn** (`TitleGenerator`, cheap model, separate thread) after the first completed turn of a session without a title. With the fixture backend two `turn/start` calls were observed. On a real backend this would be a second upstream generation for one Relay request, which conflicts with the Phase 0 one-request/one-generation boundary. Not mitigated here (no verified client-side switch found). Must be decided before M8/M9.

## Code changes in this update
- `acp_client.py`: wire helpers accept optional `env`; interleaved one-way notifications are skipped (bounded 16); agent-initiated *requests* (e.g. permission) fail closed and are never answered; metadata-only session updates (`available_commands_update`, `usage_update`, `session_info_update`, `current_mode_update`, `config_option_update`) are skipped in the prompt wire, anything else (tool_call, plan...) fails closed. `_acp_initialize/_acp_new_session/_acp_prompt_text` split out of existing code (behavior unchanged).
- `acp_stdio_relay_transport.py`: Relay lifecycle now maps 1:1 onto ACP over one persistent child (initialize / session/new / session/prompt / session/cancel notification / session/close then teardown). `OfficialAdapterLaunch` allows an official adapter only for providers with a verified backend seam (openai) with the backend inside the fixture root and no credential/route env; claude/google fail closed as UNKNOWN / LIVE_BOUNDARY.
- `fixtures/relay/fake_codex_app_server.py`: no-network fake `codex app-server` (initialize, read-only account/config/model, thread/start, fake turn).

## M5 ACP-TCK (experimental; not in CI)
Run: `uv run --python 3.14 acp-tck --agent-cwd <tmp> --agent-env HOME=<tmp> --agent-env CODEX_HOME=<tmp> --agent-env CODEX_PATH=<repo>/fixtures/relay/fake_codex_app_server.py -- node <codex-acp>/dist/index.js` (no `--allow-logout`, no `--auth-method`).
- TCK bundled `conforming.py`: 33 passed / 23 skipped, CONFORMANT.
- official codex-acp 2.1.0 + fixture backend: MANDATORY 19/19 PASS (after fixing the fixture's constant thread id, a fixture bug); 40 passed, 9 failed, 7 skipped. Remaining FAILs: ACP-LIST-001/002, LOAD-001/002/003, RESUME-001/002, PROMPTCAP-001 (image), SCHEMA-002 (advisory). The first group needs backend features the fixture does not implement and Phase 0 does not use; not an adapter-conformance verdict. Not regression-tested (Phase 0 does not need them). Result: PARTIAL; CI integration = NOT_RUN / TEST_ENVIRONMENT_NOT_PREPARED (needs Python >= 3.14 via uv, jsonschema 4.26.0, pytest 9.1.1).

## Tests
`PYTHONPATH=src:. python -m unittest discover -s tests/relay -t .`: see final report for counts. Tests needing Node/TCK are skipped unless `RELAY_CODEX_ACP_DIR` / `RELAY_ACP_TCK_FIXTURE` are set. `PYTHONPATH=src python -m unittest discover -s tests` shows 11 import errors that also exist on the base (modules importing `src.` need the repo root on the path) — pre-existing, not caused by this change.

## Verdicts (Reviewer scale)
M0 COMPLETE · M1 PARTIAL (lifecycle mapped; official adapter hosted only for Codex + fixture) · M2 Codex PARTIAL (real adapter, fixture backend; title-turn decision open) · M3 Claude PARTIAL (UNKNOWN / LIVE_BOUNDARY) · M4 Antigravity PARTIAL (UNKNOWN / LIVE_BOUNDARY) · M5 PARTIAL (run locally, not in CI) · M6 UNKNOWN (upstream exposes read-only `account/read` and `account/rateLimits/read` on the Codex backend; not mapped here) · M7 PARTIAL (Codex via real adapter; Claude/Antigravity only via the TCK conforming fixture agent, which is not their official adapter) · M8 unchanged · M9/M10 NOT_STARTED.

## No-LIVE (this update)
Real provider/model execution NO. Processes started: official `codex-acp` (node) with the fixture backend, TCK, local fake agents. The bundled `@openai/codex` was installed with `--omit=optional --ignore-scripts` (no native binary present) and never executed. API-key route NO; retry/fallback added NO; billing/settings/secrets NO; main write NO; merge NO.


---

# Update 3 — Codex second-turn decision, gate, contract tests, M3/M4/M6 audit (STATIC)

Decision (human, recorded): Phase 0 keeps **one Relay request = one model generation**. codex-acp's automatic title-generation turn is NOT allowed, not even as "cheap" or "not counted".

## Codex second turn: conclusion A (suppressed in STATIC with an outer gate)
Search of options (all read-only; no fork/patch/monkey-patch):
1. Upstream flag/env/option: none found to disable title generation (`TitleGenerator` is created unconditionally in `CodexAcpServer`; env options are CODEX_PATH, CODEX_CONFIG, MODEL_PROVIDER, DEFAULT_AUTH_REQUEST, INITIAL_AGENT_MODE, NO_BROWSER, APP_SERVER_LOGS).
2./3./4. No codex-acp, app-server or ACP session setting found that skips it. It is skipped only if the session title source is `explicit`/`unknown` (set from backend `thread/name/updated` or resumed sessions) or the prompt has no text block - quirks of upstream behavior, not a contract; not used.
5. Upstream tests mock in-process; no spawn-level switch.
6. Ending the session right after the response is a race (title turn starts as soon as the first turn completes) - not deterministic; not relied on.
7. **Adopted**: `src/relay/codex_turn_gate.py`, used as the documented `CODEX_PATH` backend hook. It forwards JSON-RPC to the real/fixture backend (`RELAY_GATE_BACKEND`) and lets only ONE generation-starting request through per process (`turn/start`, `turn/steer`, `review/start`, `thread/compact/start`, `thread/goal/set`); later ones get a JSON-RPC error and never reach the backend; unparsable lines are not forwarded; decisions are logged. Same philosophy as the Claude Admission Gate: the host-side outer boundary, not upstream, bounds generations.

Regression tests (env-gated, `RELAY_CODEX_ACP_DIR`), verified on codex-acp 2.1.0 and 2.1.1:
- canary: **without** the gate the fixture backend sees 2 `turn/start` (title generation reproduced; if upstream changes this test fails and forces a re-audit);
- with the gate: backend sees exactly 1 `turn/start`, gate log = `allowed`, `blocked`;
- `OfficialAdapterLaunch` now refuses a launch whose `CODEX_PATH` is not the gate.

Limits (honest): this is proven against a fixture backend only. On a real backend the gate is the same byte-level filter, but nothing real was run. The gate is a Python script: on Windows codex-acp spawns `"<path>" app-server` through a shell, so a `.cmd`/exe shim is needed before any Windows LIVE use. Residual: the blocked title attempt still creates an ephemeral `thread/start` (no generation). Status: second-turn risk = suppressed in STATIC (A); M2 stays PARTIAL; M9 LIVE remains forbidden.

## Lifecycle contract (official codex-acp + gate + fixture backend, tests)
initialize and session/new reach the backend with no generation method; prompt is the only generation (1 `turn/start`); cancel/close finish within 10 s with no relaunch (1 backend `initialize`); timeout -> TIMEOUT, `session/cancel` sent, backend sees `turn/interrupt`, 1 initialize, 1 turn/start, retry 0; duplicate same request -> BLOCKED with no second process/generation; same slot + different hash -> conflict BLOCKED, still 1 process/1 turn; malformed notification and agent-initiated id'd request (permission) fail closed and are never answered (fake-agent tests).

## M3 Claude (PARTIAL / UNKNOWN / LIVE_BOUNDARY)
Upstream test seam is an in-process vitest mock of the Claude Agent SDK `query` (`src/tests/acp-scenarios/harness.ts`): test-only, not a launchable no-provider mode. The only spawn-level hook is `CLAUDE_CODE_EXECUTABLE` (replace the Claude Code CLI), but `query()` starts that CLI at session creation and speaks the SDK's own protocol; a self-written fake would not be an official seam. Not launched; no self-made fake is counted as adapter verification. Admission Gate and `allowDangerouslySkipPermissions=False` untouched; `ANTHROPIC_BASE_URL` etc. stay forbidden in the STATIC launch env.

## M4 Antigravity (PARTIAL / UNKNOWN / LIVE_BOUNDARY)
Registry `antigravity-acp/agent.json` v1.3.0, license proprietary (terms: antigravity.google/terms), binary distribution only (`agy_acp_server.par` linux/mac with linux args `--uid=`, `.exe` Windows; zip from dl.google.com). The registry's public protocol matrix (`.protocol-matrix/latest.json`, a snapshot at registry version 1.2.1) reports for the unauthenticated binary: initialize success, protocolVersion 1, authMethods `["agent"]`, session/new -> `auth_required` (-32000). That is third-party CI evidence, not a Phase 0 test, and not a no-provider mode (after auth, prompts are live). Binary not downloaded/run/reverse-engineered; no code copied.

## M6 read-only design (interface only; nothing queried)
`src/relay/codex_account_readonly.py`: allow-list of exactly `account/read` (`refreshToken:false`) and `account/rateLimits/read`; `summarize_account_evidence()` maps responses to auth_state (CHATGPT_ACCOUNT / NOT_AUTHENTICATED / API_KEY_ROUTE_VIOLATION / ...), plan type, `ordinaryUsageAllowed`, primary/secondary window used%/reset, reached type, spend-control flag, credits flags (no balance/email/accountId copied). Missing/null/malformed -> UNKNOWN; usage is never "allowed" unless the account was positively read as a ChatGPT account; side_effects always 0. Not wired into Relay. Upstream fields `rateLimitResetCredits` / `rateLimitUpsell` are ignored. No login/logout/token/billing path exists. M6 = UNKNOWN (design ready, no real read).

## Verdicts after this update
M0 COMPLETE · M1 PARTIAL · M2 PARTIAL (gate proven on fixture; no real backend) · M3 PARTIAL/UNKNOWN/LIVE_BOUNDARY · M4 PARTIAL/UNKNOWN/LIVE_BOUNDARY · M5 PARTIAL (see `docs/RELAY_ACP_TCK_EVIDENCE.md`) · M6 UNKNOWN (design only) · M7 PARTIAL · M8 unchanged · M9/M10 NOT_STARTED.

## No-LIVE (this update)
Real provider/model execution NO; Codex/Claude/Antigravity real turns 0; processes started: official codex-acp (node) + gate + fixture backend, TCK, fake agents. API-key route NO; retry/fallback added NO (the gate adds a block, not a retry); Billing/settings/permissions/credentials NO; main write NO; merge NO.

---

# Update 4 — GitHub reproduction of the one-generation gate contract (STATIC)

Exact-head validation of the full suite skipped the Node/adapter tests (`OK (skipped=8)`), so the gate contract had no GitHub-side evidence. A separate carrier workflow, `relay-codex-acp-static-validation.yml` (on `feature/chat-work-command-bus`, same append-only request trigger and `target_sha`), now installs the **pinned** `@agentclientprotocol/codex-acp@2.1.0` with `--ignore-scripts --omit=optional` (asserts version 2.1.0 and that no native Codex package exists), then runs `TestOfficialCodexAdapterWithFixtureBackend`, `TestCodexAdapterContract` (incl. gate 1-turn / title turn blocked, init+session/new no generation, timeout cancel without relaunch, duplicate/conflict, version == Phase 0 pin), `TestOfficialAdapterLaunchGuards` (un-gated launch and credential/route env refused), `TestLifecycleMapping` (malformed/permission request fail closed) and `TestLiveLaunchRefused`, failing on any skip. Backend = `fixtures/relay/fake_codex_app_server.py` behind `src/relay/codex_turn_gate.py`; no credentials, no provider/model connection. The existing exact-head workflow is unchanged. Pin stays 2.1.0; TCK is not part of CI (M5 PARTIAL). The run IDs are recorded in the PR comment, not here (a doc edit would change the validated HEAD).
