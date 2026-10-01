# Claude admission-gate prior-art research

Date: 2026-09-27 JST

## Decision

The previous full A-H "prove Claude Code itself emits at most one provider request"
path is no longer the primary architecture.

Upstream evidence already demonstrates that native Claude Code can issue multiple
`/v1/messages` generations under output-limit recovery even with
`--max-turns 1` and `CLAUDE_CODE_MAX_RETRIES=0`.

The Phase 0 safety invariant should therefore be enforced by a host-owned
admission/transport boundary:

> One authorized Phase 0 dispatch may transmit at most one
> `POST /v1/messages` request to the Anthropic upstream.

Claude Code may make additional local attempts, but the gate must reject them
before upstream transmission.

No live Claude/provider/Jules execution is authorized by this document.

## Official Claude gateway contract

Current official Claude Code gateway documentation was read directly.

Important supported behavior:

- `ANTHROPIC_BASE_URL` selects an Anthropic Messages-format gateway.
- If only `ANTHROPIC_BASE_URL` is set and no gateway credential/API-key helper
  replaces authentication, a saved claude.ai login remains the active
  credential; its subscription usage limits and billing continue to apply.
- A gateway forwarding that subscription traffic to Anthropic must preserve the
  OAuth capability carried in `anthropic-beta`.
- Anthropic Messages gateway endpoints include `/v1/messages` and optional
  `/v1/messages/count_tokens`.
- `HEAD /api/hello` is best-effort startup traffic and may be rejected without
  breaking inference.
- Request bodies and evolving `anthropic-*` headers should be forwarded
  unchanged rather than rewritten/allowlisted.
- Streaming must be relayed incrementally.
- On Claude Code v2.1.283+, `x-claude-code-prompt-id` groups requests serving
  one user prompt. Gateway hint headers can be enabled for custom base URLs with
  `CLAUDE_CODE_GATEWAY_HINT_HEADERS=1`.
- `x-claude-code-request-class` distinguishes main/subagent/workflow/
  compaction/auxiliary requests.
- Claude Code understands `x-should-retry: false`; a `retry-after` integer
  above 60 seconds stops ordinary retries outside retry-watchdog sessions.
- Fast-mode availability and WebFetch safety checks may contact
  `api.anthropic.com` directly rather than following `ANTHROPIC_BASE_URL`.
  A Phase 0 containment design must disable/block such direct side paths.

Primary official references:
- https://code.claude.com/docs/en/llm-gateway
- https://code.claude.com/docs/en/llm-gateway-protocol

## Direct retry/continuation prior art

### anthropics/claude-code#92936

This upstream issue uses unmodified native Claude Code against a localhost
synthetic Messages peer with zero real provider calls.

Reported for Claude Code 2.1.258 and 2.1.263:

- normal end_turn: 1 Messages generation
- one max_tokens response then recovery: 2 generations
- repeated max_tokens: 4 generations before output-limit error

Controls included `max-turns=1`, `CLAUDE_CODE_MAX_RETRIES=0`, tools disabled,
session persistence disabled, and compaction disabled.

Conclusion: ordinary retry-zero settings do not prove literal single-generation
semantics.

Portable reproducer:
- repository: `100yenadmin/hermes-claude-agent-sdk`
- inspected pin: `e611437f7a97a67eacee95c3fb7ff0f2f3fe6d5f`
- license: MIT

Maintained underlying client:
- repository: `NousResearch/hermes-agent`
- inspected pin: `eafb4186a4e8be7ac0ca94d69b10c57e0154aee8`
- repository metadata reports MIT license

The reproducer's peer distinguishes `/v1/messages` generations from
`/v1/messages/count_tokens` auxiliary traffic.

### anthropics/claude-code#68362

A localhost mock-provider reproduction reported 1201 provider requests after a
mid-stream disconnect on an older Claude Code build before timeout.

Conclusion: a gate must fail closed before a second upstream generation rather
than relying on process timeout to contain a pathological client loop.

## Reusable gateway prior art

### terok-ai/terok-sandbox and terok-ai/terok-executor

Both repositories are Apache-2.0.

Relevant inspected components:

- `terok-sandbox/src/terok_sandbox/vault/daemon/token_broker.py`
  - aiohttp reverse-proxy skeleton
  - per-container Unix socket / loopback TCP binding
  - request forwarding and streamed-response relay
  - hop-by-hop header handling
  - audit infrastructure
  - phantom-token credential broker

- `terok-executor/src/terok_executor/resources/agents/claude.yaml`
  - Claude headless CLI mapping including `-p`, stream-json, model,
    max-turns, and verbose

- `terok-executor/src/terok_executor/resources/providers/anthropic.yaml`
  - Anthropic upstream/provider routing description

Terok demonstrates the useful architectural boundary:
agent/container -> local broker -> upstream, with secrets and policy owned
outside the agent process.

However, Phase 0 should NOT copy the complete Terok credential vault/OAuth
refresh subsystem unless it proves necessary. Current official Claude docs
support retaining the saved claude.ai subscription when only
`ANTHROPIC_BASE_URL` changes. A smaller transparent admission gateway can
therefore be attempted first.

If source is adapted directly from Terok, retain the Apache-2.0 SPDX/copyright
notices and required license attribution. Prefer adapting only the minimal
transport/streaming/header plumbing needed by Phase 0.

### anthropics/claude-code PR #5490

This draft PR also demonstrates a host-side credential proxy concept, but it is
NOT suitable for wholesale reuse here:

- it extracts real OAuth credentials from the host;
- it dynamically swaps dummy tokens;
- it contains a 401 recovery path that starts Claude and retries.

Those choices conflict with Phase 0's retry=0 and no-credential-scraping
boundaries. Reuse only the architectural lesson that the policy boundary can
sit outside the Claude container.

## Minimal Phase 0 admission-gate design

Proposed request path:

```
Claude Code v2.1.283
  |
  | ANTHROPIC_BASE_URL=<Phase0 gate>
  | CLAUDE_CODE_GATEWAY_HINT_HEADERS=1
  | saved claude.ai login remains active
  v
Phase0 Admission Gate
  |
  | exact dispatch budget: one upstream POST /v1/messages
  v
Anthropic upstream
```

The gate must own a Phase 0 dispatch identifier independent of Claude's own
headers. `x-claude-code-prompt-id` is useful evidence but must not be the sole
authorization key because some requests may omit it.

Recommended correlation:
- Phase 0 creates a random/opaque dispatch ID and one-generation budget.
- Inject a non-secret dispatch header through `ANTHROPIC_CUSTOM_HEADERS` or
  equivalent process-scoped configuration.
- Gate requires a valid active dispatch ID before accepting generation traffic.
- Gate records Claude's prompt-id, request-class, and session-id when present.

Admission rule:
1. normalize path and identify exact `POST /v1/messages`;
2. atomically claim the dispatch's only generation slot BEFORE upstream I/O;
3. first claimant forwards the request unchanged;
4. every later generation attempt for the same dispatch is rejected locally
   and never opens an upstream connection;
5. gate-side retry count is zero;
6. after terminal state, replay is denied.

Auxiliary endpoints are separate policy:
- `/v1/messages/count_tokens` is not a model generation and must not silently
  consume the generation slot;
- startup `HEAD /api/hello` can be rejected;
- unknown paths fail closed until explicitly reviewed.

Local rejection should include retry-suppression response metadata consistent
with current official gateway docs (for example `x-should-retry: false` and a
`retry-after` value above 60 where semantically appropriate). Exact status/body
must be validated in mock tests; do not rely on client cooperation for safety,
because the gate's atomic admission decision is authoritative.

## Static acceptance tests before any live proof

A static/mock implementation is not live-ready until tests prove:

- first valid generation is forwarded exactly once;
- second same-dispatch generation is denied before upstream send;
- two concurrent first requests race and exactly one wins;
- no gate-side automatic retry;
- terminal/replayed dispatch is denied;
- missing/malformed/stale dispatch ID fails closed;
- count_tokens/HEAD/unknown paths are classified independently;
- admitted body bytes are not rewritten;
- `anthropic-beta` and `anthropic-version` are preserved;
- auth values and request bodies are never logged; body hash is sufficient;
- streaming response chunks are relayed incrementally;
- upstream 4xx/5xx is returned without a gate-side retry;
- prompt-id/request-class/session-id are evidence only, not authorization;
- a denied second request leaves upstream generation count at exactly one.

## Live boundary

After static implementation passes, a real-subscription proof still requires
separate explicit user approval.

That future proof should verify:
- Claude has no direct route to Anthropic except through the gate;
- saved subscription authentication still works through the gateway;
- first generation reaches Anthropic;
- a deliberately induced second local generation attempt is denied before
  upstream transmission;
- no API key, new billing route, or alternate provider is introduced.

Until then both Claude night-loop backends remain not live-green and
takeover/orchestration remains deferred.
