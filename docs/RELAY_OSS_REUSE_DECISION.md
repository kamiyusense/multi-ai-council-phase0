# Relay OSS Reuse Decision

Updated: 2026-09-21
Scope: static/code-level audit for Multi-AI Council Phase 0
Relay branch: `feature/relay-transport`
Audit base checkpoint: `dc52755b007a3db2c3f4ed63d0a216336d9ac9e0`

## 1. Decision

Use a **thin Python Relay built on the Agent Client Protocol (ACP) Python SDK**.

Do not build generic stdio JSON-RPC framing, ACP schema models, or ACP child-process lifecycle from scratch unless a later pinned-version gap proves it necessary.

Preferred structure:

```text
Phase0 Core (Python)
  -> thin Phase0 Relay (Python)
     -> ACP Python SDK
        -> Codex ACP adapter
        -> Claude Agent ACP adapter
        -> Google Antigravity ACP server
```

Phase0 Core remains the policy owner. Relay is transport only.

## 2. Pinned audit checkpoints

The following upstream checkpoints were directly inspected during this audit. These pins are evidence identities, not automatic dependency-upgrade authorization.

| Candidate | Audit checkpoint / version | License evidence | Phase 0 decision |
| --- | --- | --- | --- |
| ACP protocol/spec | `8f76d6c8cf379a0f8a7fe2bbee6007fb2a53a84e` | Apache-2.0 LICENSE | protocol reference |
| ACP Python SDK | `9d07d7871ef4b220b8507e15fc4b1560f0950a64`, package 0.12.1 | Apache-2.0 LICENSE | **direct dependency candidate** |
| ACP Registry | `4e886ce526a50f37da991ea43758b0ba35466485` | registry metadata | distribution/protocol evidence |
| codex-acp | `acc035a7444bf7550aabcc24597ed845ba3e593b`, package 1.12.0 | Apache-2.0 LICENSE/package metadata | **external agent candidate** |
| claude-agent-acp | `d421f56a6c43cde16d9a7531d08a750a5ef2f04a`, package 0.79.0 | source LICENSE/package say Apache-2.0; ACP Registry says proprietary | **external agent candidate; license metadata discrepancy noted** |
| Gemini CLI | `cfbcaa8df13ea4610bb379b377b56d62980c0032`, registry 0.60.0 | Apache-2.0 | defer as Google substitute |
| Antigravity CLI | `7bb195acaec9e7788df5210d0dc3e15f3cefc6b3` | repo terms/metadata | do not use as Relay fallback |
| Antigravity ACP | registry 1.1.1 | proprietary; Google-hosted binary | **preferred Google external agent candidate** |
| OpenHands | `d07e1126a37d0efc6fb2a096d3f48453f4d0def9` | MIT LICENSE | design/test reference only |
| conduct | `981a53243940c1c0da2fd12515eb44bf6996eb28` | MIT LICENSE | design/reference only |
| Open Orchestrator | `1b485ae105596de19d8012ace921701c7b84b99c` | MIT LICENSE | design/reference only |
| multi-agent-orchestrator-skill | `9ba99f3faa28197946bde378eab713666191a386` | MIT LICENSE | reject runtime launcher; design reference only |
| CAID | `f364d9e95727c2e2ba3dbf23f2d6de52c5f3d5fa` | pyproject says MIT; no top-level LICENSE observed | design only; no code copy |
| A2A | `afda8316c64951a2ecb2a0d3d10867405d2b4095` | Apache-2.0 LICENSE | future vocabulary only |

## 3. Direct reuse

### 3.1 ACP Python SDK

Package: `agent-client-protocol==0.12.1`

Observed runtime dependencies:

- `pydantic>=2.7`
- `pydantic-core>=2.18.1`

The SDK already supplies generated ACP schema models, asyncio transports, stdio JSON-RPC plumbing, and process/lifecycle helpers. It is a much smaller fit for the existing Python Core than adopting an entire orchestration product.

**Reuse:** typed ACP messages, stdio transport, process spawn/lifecycle, cancellation/client primitives.

**Do not delegate to the SDK:** Council safety policy, retry/fallback decisions, auth-route acceptance, evidence interpretation, comparison, or final decision.

### 3.2 Codex ACP 1.12.0

ACP Registry distribution: `@agentclientprotocol/codex-acp@1.12.0`.

Observed capabilities include ChatGPT authentication, API-key authentication, custom gateway authentication, model/config control, permissions, and Codex App Server translation.

Phase 0 policy must reject all non-subscription routes. The adapter's auth-status extension distinguishes:

- `account` (ChatGPT account)
- `api_key`
- `gateway`
- `external`
- `none`

For Phase 0 live eligibility, the outer Relay gate must require a verified `account` status and reject/UNKNOWN every other kind.

Environment/config routes such as `CODEX_API_KEY`, `OPENAI_API_KEY`, custom model provider/gateway configuration, or unapproved `CODEX_CONFIG` must be absent or deterministically rejected.

**Static decision:** use as external ACP agent behind a Phase0-owned wrapper.

**Live decision:** BLOCKED by retry/replay and executed-model verification items in `RELAY_LIVE_BLOCKERS.md`.

### 3.3 Claude Agent ACP 0.79.0

ACP Registry distribution: `@agentclientprotocol/claude-agent-acp@0.79.0`.

Auth-status code distinguishes subscription account, API key, gateway, external cloud credential, and none. Phase 0 must require `kind=account` for the intended Claude subscription route.

The adapter exposes a host control that removes dangerous bypass mode:

```text
_meta.claudeCode.options.allowDangerouslySkipPermissions = false
```

This must be sent on both session/new and session/load and covered by regression tests.

Do **not** use `--hide-claude-auth`: that flag intentionally blocks claude.ai subscription use and is opposite to this project's intended subscription route.

Source/package metadata says Apache-2.0 while the current ACP Registry entry labels the distributed agent proprietary. Do not silently resolve this discrepancy. No vendoring is needed for the Phase 0 design; treat the adapter as an external dependency and retain the discrepancy as a legal/package-metadata caveat.

**Static decision:** use as external ACP agent behind a Phase0-owned wrapper.

**Live decision:** BLOCKED by internal retry/fallback semantics and executed-model verification items in `RELAY_LIVE_BLOCKERS.md`.

### 3.4 Google Antigravity ACP 1.1.1

This audit supersedes the older assumption that native/official Antigravity ACP availability was UNKNOWN.

ACP Registry at the pinned checkpoint lists **Google Antigravity 1.1.1** as a proprietary binary distributed from Google-hosted download URLs. Native packages are listed for:

- Windows x86_64
- Windows aarch64
- Linux x86_64/aarch64
- macOS aarch64

The 2026-09-21 Registry protocol matrix reports a successful ACP initialize for `agy_acp_server_1.1.1`, with session list/load/resume capabilities. The unauthenticated session/new probe correctly returned authentication-required.

This removes the need to substitute Gemini CLI merely because it supports ACP, and removes the need to use unsafe third-party Antigravity bridges.

The server is proprietary/closed for this audit: **use it as an external Google binary only; do not vendor or reverse engineer it.**

**Static decision:** preferred Google external ACP agent candidate.

**Live decision:** BLOCKED by subscription/account proof, quota/billing observability, retry/fallback UNKNOWN, and executed-model verification items in `RELAY_LIVE_BLOCKERS.md`.

## 4. Not adopted as runtime dependencies

### Gemini CLI

Gemini CLI is a real official ACP-capable alternative, but its current model-routing/fallback mechanism is enabled by default and the codebase contains retry/fallback strategies. A complete user-facing proof that all model routing, retry, and subagent fallback can be disabled for the intended subscription path was not established.

Because official Antigravity ACP now exists, Phase 0 should not substitute Gemini CLI for the user's Antigravity/agy seat unless a later explicit design change chooses that route.

Classification: **defer / fallback research only, not current Relay runtime**.

### OpenHands

OpenHands has mature ACP process/server patterns and useful mock ACP tests, but it also carries a much larger credential/cloud/container/application surface. The ACP Python SDK covers the low-level stdio/process need with far less dependency weight.

Classification: **design/test reference only**.

### conduct

Useful Windows-aware process/mock/worktree patterns are present, but conduct also exposes Git merge, push, and PR actions. Those side effects do not belong in the Phase 0 runtime.

Classification: **design/reference only**.

### Open Orchestrator

Useful worktree/orchestration patterns, but Git/PR/ship behavior and terminal-multiplexer-oriented architecture are unnecessary for a thin Relay and increase side-effect surface.

Classification: **design/reference only**.

### multi-agent-orchestrator-skill

The runtime launcher examples use high-autonomy/bypass options such as dangerous permission/sandbox bypass or YOLO-style execution. That is incompatible with Phase 0.

Classification: **runtime launcher rejected**. Coordination/event/fake-CLI ideas may be used as design inspiration only.

### CAID

Heavy OpenHands/LiteLLM/OpenAI/Anthropic dependency surface and API-credential assumptions do not match the subscription-only Phase 0 route. License metadata is also not sufficiently clean for code copying: pyproject declares MIT while a top-level LICENSE was not observed in this audit.

Classification: **design only; no code copy/dependency**.

### A2A

A2A solves agent-to-agent interoperability, not the local controller-to-coding-agent transport needed now.

Classification: **future design vocabulary only**.

## 5. Explicit rejections

Do not use:

- third-party Antigravity ACP bridges that require permission-bypass flags;
- generic launchers that require `--dangerously-*`, `--yolo`, or equivalent;
- Gemini CLI as an automatic substitute for Antigravity;
- API-key or custom-gateway auth as a fallback;
- runtime Git merge/push/PR helpers from conduct/Open Orchestrator;
- code from a license-unclear source merely because its design is useful.

## 6. What no longer needs to be built from scratch

After this audit, the current Relay should **not** self-build:

- ACP JSON-RPC framing;
- ACP protocol schema/model definitions;
- generic stdio child-process transport;
- basic ACP initialize/session/prompt/cancel lifecycle;
- Codex App Server to ACP translation;
- Claude Agent SDK to ACP translation;
- a third-party Antigravity terminal scraper/PTY bridge.

Phase 0 still owns the safety wrapper, evidence boundary, provider manifests, exact no-retry/no-fallback policy, auth-route allowlist, model verification, timeout/abort policy, deterministic comparison, and human final decision.
