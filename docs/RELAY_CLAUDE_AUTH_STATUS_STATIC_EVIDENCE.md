# Relay — Claude official `_auth/status_update` (STATIC) + M4 public-metadata check

Base: main `aebae14695cfaaf1dc8bcc2ec35faca9c898fd48` (PR #281 merge `7b1d29b` is an ancestor; PR #283 is a separate docs-only Draft, not assumed merged, not touched).
No provider/model turn, no real `claude auth status`, no real account read, no Antigravity binary download/run, no login/logout, no pin change. retry=0, fallback=disabled.

## What the official adapter does (claude-agent-acp 0.84.0 and 0.85.1; `dist/auth-status.js` is byte-identical in both)
- `_auth/status_update` is a notification (no `id`), params `{authStatus: {kind, label, detail?, account?{plan,email,organization}}}`; `kind` is one of `account | api_key | gateway | external | none`.
- It is pushed **after** the `initialize` response (async `claude auth status --json` probe), after `session/new`, and at the **start of each user prompt (mid-turn)**. It is sent only when the payload changed.
- Precedence is decided by the adapter (`fromCliStatus` / `fromAccountInfo` -> `mapAuthFields`): 3P/gateway > API key > subscription; a known logged-out verdict (`loggedIn=false`, no key, not 3P) wins before stale subscription fields.
- Observed wire shape (real adapter, **synthetic** `auth status --json` answered by `fixtures/relay/claude_cli_tripwire.py` via the new `RELAY_TRIPWIRE_AUTH_STATUS_JSON`): subscription -> `kind=account`, key helper -> `api_key`, `apiProvider=bedrock` -> `external`, logged out -> `none`. No real CLI/account was involved; the tripwire log shows the adapter ran only `auth status --json`.

## Defect found (M10) and fix
Before: `_acp_prompt_text` raised on any non-`session/update` notification, so the official adapter's mid-turn `_auth/status_update` would have turned a real Claude turn into `UNKNOWN`; `initialize`/`session/new` silently dropped it.
After (smallest change inside the existing seam):
- `claude_auth_readonly.summarize_claude_auth_status_update()` (same module/evidence dict as the CLI-status summarizer) translates only `kind`: account -> `CLAUDE_SUBSCRIPTION_ACCOUNT`, api_key -> `API_KEY_ROUTE_VIOLATION`, gateway/external -> `EXTERNAL_ROUTE_VIOLATION`, none -> `NOT_AUTHENTICATED`, anything else -> `UNKNOWN`. It never recomputes the precedence; label/detail/account (email, organization, plan) are never copied (plan stays `UNKNOWN`).
- `acp_client`: the notification is skipped as non-text (counts against the existing ignorable bound) and its sanitized classification is appended to an optional sink; any other unknown notification still fails closed in the prompt wire.
- `AcpStdioStaticTransport.auth_status_evidence`: list of sanitized classifications (evidence only; Relay does not decide to abort/retry/fallback on it).
- Tests: `tests/relay/test_claude_auth_status_notification.py` (11; 2 env-gated on `RELAY_CLAUDE_ACP_DIR`): all five kinds after initialize and mid-prompt, not text / not execution / no retry (spawn 1, prompt 1), no email/org/label in evidence or result, malformed -> UNKNOWN without breaking the turn, other unknown methods still fail closed, flood bounded, and the official adapter's push is classified identically to the CLI-status summarizer (including `loggedIn=false` + stale subscription).

## M3 Claude: current pin 0.84.0 vs latest 0.85.1 (read-only comparison)
- Identical: `auth-status.js`, `permissions/modes.js`. No change found around `session/new` `_meta`, `allowDangerouslySkipPermissions`, `initialize` or the CLI auth probe. The STATIC boundary tests and the new notification tests pass on **both** versions.
- Changed in 0.85.1: new `serve.js` + `v2/` (draft ACP v2, opt-in via `CLAUDE_AGENT_ACP_EXPERIMENTAL_V2=1`, default stays v1), session-replay filtering of harness-framed meta messages, `air-extension`, `elicitation`, `session-effort` edits.
- Decision: **pin stays 0.84.0** (`DD-CLAUDE-ACP-PIN-UPGRADE`, below).

## M4 Antigravity (public metadata only; binary not downloaded/run; no Terms accepted)
- Registry manifest is `1.3.0` (Phase 0 pin `1.2.1`). Platforms: same as 1.2.1 data plus `darwin-x86_64`; `cmd`/`args` unchanged (linux `--uid=`, `.par`; windows `.exe`); archive names `agy-acp-server-1.3.0-<os>-<arch>.zip`.
- Upstream public protocol matrix, re-read 2026-10-03T10:26Z, now probed at **1.3.0**: unauthenticated `initialize` success, protocolVersion 1, `authMethods:["agent"]`, same capabilities as the 1.2.1 snapshot (loadSession, sessionList, sessionResume; no fork/stop/setModel), `session/new` = `auth_required (-32000)`. No protocol/capability difference between 1.2.1 and 1.3.0 was visible. This is upstream's evidence, not ours.
- No Phase 0-mandatory fix is evident, so no prepare-only patch was made. `https://antigravity.google/docs/ide/extensions` was not reachable from this environment (HTTP 403 at the proxy) -> UNKNOWN; not worked around.
- Interception point for an at-most-one-generation gate: no official hook is documented in the manifest/matrix (only `cmd`/`args`, no env/backend option, no no-provider mode); no reverse engineering or proxy attempted -> **UNKNOWN / LIVE_BOUNDARY** (unchanged).

## M5 TCK (unchanged, nothing copied)
Codex: existing result reused (MANDATORY 19 PASS / 2 SKIPPED; 40 passed / 9 failed / 7 skipped, NOT CONFORMANT on CAPABILITY items the fixture backend cannot serve). Claude: tripwire CLI -> MANDATORY 7 PASS / 14 FAIL, all session-dependent: **a boundary, not a conformance verdict**. Antigravity: NOT_RUN.

## M6 / M7 / M8
- M6: Claude identity classification now reachable from the official push (classification only; quota UNKNOWN, no official read-only quota surface). Antigravity account/quota: UNKNOWN (no official read-only surface known).
- M7: Relay request -> Claude profile -> `AcpStdioStaticTransport` -> synthetic `_auth/status_update` -> sanitized classification -> `SIMULATED` mock result (tests above); Codex/Antigravity mock E2E and Codex adapter tests unchanged and green.
- M8: Codex one-generation gate unchanged; Claude Admission Gate untouched (59 existing tests); Antigravity interception UNKNOWN.

## Deferred Decisions (human)
- `DD-CLAUDE-ACP-PIN-UPGRADE`: 0.84.0 -> 0.85.1. Gains: upstream fixes (replay filtering etc.). Risks: new v2 router code in the launch path (opt-in, default v1), larger `acp-agent.js` surface, re-audit cost. Keeping 0.84.0 costs nothing for the STATIC work above (all tests pass on both).
- `DD-ANTIGRAVITY-PIN-1_3_0`: 1.2.1 -> 1.3.0. Public metadata shows only a version bump and an added darwin-x86_64 platform; no capability change. Bump = accepting a newer proprietary artifact; binary download/run needs the human to accept Google's Terms.
- Antigravity binary download/run; real Claude/Antigravity handshake or account read; provider/model LIVE; policy on whether a mid-session `API_KEY_ROUTE_VIOLATION`/`EXTERNAL_ROUTE_VIOLATION` notification should abort a dispatch (a policy decision above Relay; Relay only records it).
- Merge of the resulting PR.
