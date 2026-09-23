# Relay Live Blockers

Updated: 2026-09-21
Rule: every safety-relevant UNKNOWN below blocks live provider execution.

This document does **not** authorize a live Relay/provider POC.

## 1. Common live blockers

The following remain unresolved across providers:

- exact finite timeout values;
- exact minimum permission profile;
- executed-model verification mechanism;
- proof that the intended subscription/auth route is the route actually paying for the turn;
- provider-specific abort/readback evidence;
- final secret/PII/private-code fan-out patterns;
- live filesystem/network confinement feasibility;
- end-to-end proof that no hidden retry/fallback violates Phase 0 policy.

Static/mock Relay implementation is allowed while these remain unresolved.

## 2. Codex / ChatGPT

### BLOCKER: provider-internal retry/replay

Current Codex configuration documentation describes provider request and stream retry budgets with non-zero defaults. Upstream issue evidence also indicates that the built-in OpenAI/ChatGPT provider may not accept the same retry overrides available to custom providers, and a separate authentication-recovery/replay path has been reported.

Phase 0 requires automatic retry = 0 and forbids hidden retry/fallback inside the provider path.

Therefore:

**Codex live status: BLOCKED / UNKNOWN**

Required proof before live:

- built-in ChatGPT-auth provider can be configured/verified with zero automatic request retry;
- zero stream/reconnect replay that can cause another model request;
- no auth recovery path silently replays a turn;
- evidence can distinguish a single model request from a replay.

Do not solve this by switching to an API-key/custom provider; that violates the intended subscription-only route.

## 3. Claude

### BLOCKER: Claude SDK retry/fallback semantics

The current Claude Agent ACP session-failure contract explicitly handles SDK `api_retry` progress and model-fallback notices. This proves that retry/fallback behavior may exist below the Phase0 Relay layer.

No audited setting was found that proves all such behavior can be disabled while retaining the intended claude.ai subscription route.

Therefore:

**Claude live status: BLOCKED / UNKNOWN**

Required proof before live:

- provider/SDK automatic model-call retry can be disabled or deterministically prevented;
- model fallback can be disabled;
- no restart/recovery path creates another model turn without a new human/Phase0 dispatch;
- subscription auth status remains `account`;
- `allowDangerouslySkipPermissions=false` is effective on new/load;
- executed model is independently verified.

Auth note: `--hide-claude-auth` must not be used because it intentionally rejects claude.ai subscription billing.

## 4. Google Antigravity ACP

### Confirmed static facts

ACP Registry 1.1.1 provides a Google-distributed Antigravity ACP server, including Windows x86_64/aarch64 binaries. Registry protocol probing on 2026-09-21 successfully initialized `agy_acp_server_1.1.1`.

This supersedes the old assumption that official Antigravity ACP availability was UNKNOWN.

### BLOCKER: closed runtime safety/account evidence

The server is proprietary/closed for this audit, so internal retry/fallback behavior cannot be established by source inspection.

The current ACP surface also does not provide sufficient proof of subscription quota/billing state for Phase 0's fail-closed billing boundary.

Therefore:

**Antigravity live status: BLOCKED / UNKNOWN**

Required proof before live:

- the authenticated identity is the intended Google AI Pro/Antigravity account route;
- API-key/Cloud Billing/overage paths are not selected;
- internal retry/fallback behavior satisfies Phase0 auto-retry=0/no-fallback;
- executed model is verifiable;
- active-turn cancellation/process teardown can be proven without automatic restart;
- quota/billing UNKNOWN can be detected and stops before send.

Do not fall back to Gemini CLI or a third-party Antigravity bridge automatically.

## 5. Gemini CLI

Gemini CLI is not the selected Google transport for the current design.

Its model-routing fallback is enabled by default in current documentation/code, retry controls are not yet proven sufficient for the complete intended path, and model selection does not necessarily control every subagent model.

Status: **DEFERRED, not an automatic fallback.**

## 6. Live approval boundary

Even after all technical blockers above are resolved, the first real provider/model turn remains a separate explicit-user-approval boundary.

Before requesting that approval, the implementation must provide:

- static/mock test evidence;
- exact dependency/provider versions;
- auth-route readback;
- permission readback;
- no-retry/no-fallback proof;
- model verification plan;
- timeout/abort behavior;
- evidence paths/hashes;
- confirmation that API keys, billing mutation, settings mutation, GitHub runtime writes, and dangerous permission bypass are absent.

Until then:

```text
live_model_execution = false
live_relay_poc = not authorized
```
