# Relay M3 / M4 / M5 / M6 — STATIC evidence (no LIVE)

Base: main `2ef4e297a8b99329a81d1ce8764bf5fb63685be9` (PR #270 merge commit `d24685d` is an ancestor).
Nothing here starts a real provider/model turn, reads a real account, logs in/out, refreshes a token or touches Billing/settings.
retry=0, fallback=disabled everywhere. The existing Claude Admission Gate (`automation/command_bus/claude_admission_gate.py`) is untouched
(59 existing tests re-run OK) and `allowDangerouslySkipPermissions=False` is unchanged.

## M3 Claude — `STATIC_BOUNDARY` (initialize reachable, session/new = LIVE_BOUNDARY)
Official `@agentclientprotocol/claude-agent-acp` 0.84.0 (pin) and 0.85.1 (latest) behave identically. Installed with `--ignore-scripts --omit=optional`
(no native Claude CLI). `CLAUDE_CODE_EXECUTABLE` is pointed at `fixtures/relay/claude_cli_tripwire.py`, which only records argv and exits 2
(it is a tripwire, **not** a fake Claude: no credentials, no network).

| Step | Observed |
|---|---|
| `initialize` | succeeds with no provider: protocolVersion 1, `authMethods: []`, session capabilities incl. `close` |
| side effect of `initialize` | the adapter itself runs `<cli> auth status --json` in the background (`dist/acp-agent.js` `probeCliAuthStatus`). With a real CLI this is a **read of the real Claude login state**, so a real CLI must never be present in STATIC runs |
| `session/new` | the SDK spawns the CLI (`--output-format stream-json ... --permission-mode default --permission-prompt-tool stdio`); with the tripwire, `session/new` returns an error |
| permission primitive | official: `--permission-mode default`, `--permission-prompt-tool stdio`. **Finding (M10, found by GitHub Linux CI as a non-root user):** without `session/new` `_meta.claudeCode.options.allowDangerouslySkipPermissions=false` the adapter also passes `--allow-dangerously-skip-permissions` to the CLI (bypass becomes *allowed*, mode stays `default`). The adapter enables it unless root (`ALLOW_BYPASS`). Relay's transport did not send the profile's `session_meta`, so the Phase 0 no-bypass policy never reached the adapter. Fixed: `AcpStdioStaticTransport.open_session` now sends `profile.session_meta` (Claude only; Codex/Antigravity send no `_meta`); with it the flag is absent. Canary test pins the upstream default (`IS_SANDBOX=1` reproduces the non-root behavior as root) |

Consequence: a full Relay lifecycle (`initialize -> session/new -> prompt`) through the official Claude adapter cannot be shown without a real or genuine
CLI, i.e. without a provider. `OfficialAdapterLaunch` therefore keeps failing closed for `anthropic` (no verified backend seam). No fake is dressed up as official.
Tests: `tests/relay/test_claude_acp_static_boundary.py` (3 env-gated on `RELAY_CLAUDE_ACP_DIR`, POSIX; 1 tripwire unit test always runs).

## M4 Antigravity — `LIVE_BOUNDARY / UNKNOWN`
Registry manifest `antigravity-acp` is now `1.3.0` (Phase 0 pin `1.2.1`, **unchanged**; pin bump = Deferred Decision). Proprietary Google binary
(`agy_acp_server.par` / `.exe`, license https://antigravity.google/terms); it was **not downloaded or run** (license terms are the human's to accept).
Upstream public protocol matrix (registry `.protocol-matrix/latest.json`, 2026-10-02, snapshot at registry version 1.2.1): unauthenticated `initialize` = success,
`authMethods: ["agent"]`, `session/new` = `auth_required (-32000)`. That is upstream's evidence, not ours. No fake/no-provider mode is documented; no interception point
is known, so no custom proxy was built. Added only data: `antigravity_launch_args()` (linux `--uid=`, others none; unsupported platform fails closed) + tests.

## M5 ACP-TCK
`acp-tck` is not on PyPI; installed from `git+https://github.com/agentclientprotocol/acp-tck@fa00ccd` (0.2.0, experimental, Python >= 3.14 via `uv run --python 3.14`).
No `--allow-logout`, no `--auth-method`.

| Agent | Result |
|---|---|
| official codex-acp 2.1.0 + fixture backend (re-run today) | **unchanged**: 40 passed / 9 failed / 7 skipped; MANDATORY 19 PASS / 2 SKIPPED; CAPABILITY 8/7/4; ADVISORY 9/2/1 |
| official claude-agent-acp 0.84.0 + tripwire CLI | 16 passed / 37 failed / 3 skipped; MANDATORY 7 PASS / 14 FAIL. The failing MANDATORY items all depend on `session/new`, which cannot succeed without a CLI (see M3). **Not an adapter conformance verdict**; MANDATORY session-dependent requirements are NOT_TESTED in effect |
| Antigravity | NOT_RUN (binary not obtained) |

The TCK was not copied into the repo and no duplicate local tests were written for PASS cases.

## M6 read-only account/quota (prepare-only, nothing queried)
- Codex: unchanged `src/relay/codex_account_readonly.py`. The real `account/read` made by the M9 runner returned `CHATGPT_ACCOUNT` / plan `plus` / side_effects 0 (user-supplied screenshot of the PC run).
- Claude: new `src/relay/claude_auth_readonly.py` maps an already-received `claude auth status --json` payload with the same precedence as the official adapter
  (gateway/3P -> API key -> subscription); route violations are named, no email/org copied, quota stays UNKNOWN (no official read-only quota surface in the pinned adapter). Never executes the CLI.
- Antigravity: no official read-only surface known beyond the existing checklists; UNKNOWN.

## M7 / M8 / M10
- M7: existing 3-provider mock lifecycle tests unchanged and green; the official-adapter path exists for Codex only (above explains why not Claude/Antigravity).
- M8: Codex one-generation gate unchanged; Claude = existing Admission Gate (59 tests OK); Antigravity: no interception point, UNKNOWN.
- M10 (static defect): session/new `_meta` (Claude no-bypass policy) now actually reaches the official adapter - see the M3 table. Regression: `TestSessionMetaReachesTheAdapter` + the boundary canary.
- M10 (observed from the user's first run): startup stops now print Japanese install hints (Node via `winget`, Codex via `npm.cmd`, login by the user via `codex.cmd login`;
  PowerShell blocks `npm.ps1`). Message text only; no behavior change. The earlier reply-shape receipt fields (PR #270) remain the diagnostic for the `COMPLETED_UNEXPECTED_TEXT` result.

## Deferred Decisions / BLOCKED (human)
1. Antigravity pin `1.2.1 -> 1.3.0` and whether to download/run the proprietary binary (accepts Google terms).
2. Any real Claude or Antigravity handshake/turn, or a real-account read (LIVE approval).
3. Second Codex LIVE (not requested).
