# Relay Static Build Plan

Updated: 2026-09-21
Status: implementation-ready for static/mock work; live remains prohibited

## 1. Target architecture

```text
Phase0 Core
  -> Phase0 Relay
       -> ACP client/process layer
            -> Codex ACP
            -> Claude Agent ACP
            -> Google Antigravity ACP
  <- raw ACP/provider evidence
  -> Core evidence/state/comparison/report
```

Preferred common dependency:

```text
agent-client-protocol == 0.12.1
```

Pin provider-agent versions independently:

```text
Codex ACP:             1.12.0
Claude Agent ACP:      0.79.0
Google Antigravity ACP: 1.1.1
```

No live provider starts are authorized by this plan.

## 2. Relay-owned modules

Recommended branch ownership:

```text
src/relay/
  envelope.py
  correlation.py
  duplicate_guard.py
  acp_client.py
  lifecycle.py
  result.py
  errors.py

src/providers/
  base.py
  codex_acp.py
  claude_acp.py
  antigravity_acp.py

fixtures/relay/
tests/relay/
docs/RELAY_*.md
```

Do not move Council comparison/fan-out policy from `phase0_core` into Relay.

## 3. Core adapter mapping

Relay must satisfy the existing Core contract:

```text
prepare(case_context)
preflight(prepared_context)
dispatch(prepared_context)
collect(process_handle)
abort(process_handle)
classify(raw_result)
```

Recommended mapping:

- `prepare`: build immutable provider envelope only;
- `preflight`: static capability/auth-policy/config validation, no live prompt;
- `dispatch`: exactly one ACP session prompt attempt after all gates;
- `collect`: gather provider/ACP result and evidence without starting another turn;
- `abort`: ACP cancellation + deterministic process teardown policy; never restart;
- `classify`: transport/provider evidence to Core state mapping only.

## 4. Common ACP lifecycle

Static implementation should model this lifecycle without contacting real providers:

```text
spawn agent process
-> initialize
-> receive/verify advertised capabilities
-> verify auth-status policy
-> session/new or session/load
-> one prompt
-> stream/capture updates
-> prompt terminal result
-> close/cancel
-> persist evidence
```

Use standard ACP cancellation for an active turn. Do not depend on an agent-specific `session/stop` extension.

No prompt method may be called a second time automatically for the same slot.

## 5. Correlation and duplicate guard

Every dispatch slot should carry:

- case/task id
- provider id
- slot/sequence id
- deterministic packet hash
- correlation id
- session id when created
- raw/evidence references
- dispatch-attempt count

Rules:

- one slot has at most one Phase0 dispatch attempt;
- same slot + same hash = already reserved/dispatched, not a new send;
- same slot + different hash = conflict;
- ambiguous post-send state = UNKNOWN;
- UNKNOWN must not trigger another prompt;
- exactly-once delivery must never be claimed without provider/backend proof.

## 6. Provider-specific static policy

### Codex

Before any future live spawn/prompt:

- require intended ChatGPT subscription/account auth;
- reject API-key, personal-access-token, gateway, external-provider, or unknown auth status;
- remove/reject `CODEX_API_KEY` and `OPENAI_API_KEY`;
- reject unapproved `MODEL_PROVIDER`, custom gateway/provider configuration, and arbitrary `CODEX_CONFIG`;
- use a fixed model allowlist from manifest;
- no dangerous/full-access mode by default;
- no adapter/client automatic retry.

### Claude

Before any future live spawn/prompt:

- require subscription `account` auth status;
- reject API-key/gateway/external cloud/unknown auth status;
- scrub/reject API-key and gateway credential routes;
- never pass `--hide-claude-auth`;
- on session/new and session/load set:
  `_meta.claudeCode.options.allowDangerouslySkipPermissions=false`;
- reject a returned/advertised dangerous bypass mode if it still appears;
- no adapter/client automatic retry.

### Antigravity

- use only the official Google-distributed `antigravity-acp` binary selected from the pinned ACP Registry entry;
- do not use PTY scraping or third-party bridges;
- no API-key substitution;
- require verifiable intended account/subscription identity before live;
- do not assume token/quota state from absence of an error;
- do not depend on `session/stop`; implement standard ACP cancel plus deterministic process teardown;
- preserve filesystem/hash evidence because live ACP file-change reporting may be incomplete.

## 7. Static tests required before integration with Core

At minimum:

- ACP command/process is injected as a test double; no real provider starts;
- initialize capability fixture per provider;
- auth status `account` accepted, all other kinds rejected/UNKNOWN;
- Codex API-key/gateway env/config rejected;
- Claude dangerous bypass option explicitly false;
- Claude bypass mode cannot reappear silently;
- Antigravity official-binary descriptor selected by Windows architecture fixture;
- same-slot/same-hash duplicate does not dispatch;
- same-slot/different-hash conflict;
- one prompt call maximum per slot;
- timeout does not retry;
- provider failure does not fallback;
- cancel targets only the intended provider/session;
- process teardown never restarts a provider;
- malformed ACP/event payload becomes INVALID/UNKNOWN, never success;
- one provider failure does not erase another;
- raw transport/provider evidence saved before semantic classification;
- simulated state cannot be confused with real delivery;
- no production dummy provider when executable/package is absent.

## 8. Core integration checkpoint

After Relay static tests pass:

1. map Relay adapter to `phase0_core.adapter.ProviderAdapter`;
2. run Core three-provider E2E using Relay mock transports;
3. repeat invalid output, timeout, unknown, safety-warning, and stop cases;
4. capture branch SHA + test output + contract diff;
5. stop before any real provider model turn.

No Merge is implied by reaching this checkpoint.
