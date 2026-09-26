# Claude Phase 0 Admission Gate — static design and evidence

Status: static implementation and local fake-provider regression only. This is
not approval or readiness for Claude, Anthropic, Jules, or any external model.

## Invariant

For each host-registered Phase 0 `dispatch_id`, at most one `POST
/v1/messages` is admitted to the configured upstream. The SQLite transaction
claims the sole slot with `BEGIN IMMEDIATE` and commits it before the gate
opens the upstream connection. A second, concurrent, terminal, expired,
malformed, or unknown dispatch is denied before that connection. The first
attempt consumes its slot even when the upstream times out or disconnects.
There is no retry, Claude relaunch, provider fallback, or replacement model.
Controller policy remains `retry=0`, `fallback=disabled`.

The authorization credential is not a Claude session, prompt, or request-class
header. The host registers a UUID through `DispatchStore.register`; the local
transport carries it as `X-Phase0-Dispatch-ID`. Claude's session/prompt/request
headers are optional evidence only. No HTTP endpoint can register a dispatch.

## Endpoint and wire policy

* `POST /v1/messages`: only generation endpoint; bounded body is forwarded
  byte-for-byte after the durable slot claim.
* `POST /v1/messages/count_tokens`: deterministic local 403; it is neither
  forwarded nor charged against the generation slot.
* `HEAD /api/hello`: local 204 health response; no upstream access.
* Other endpoints/methods: local fail-closed response.
* Upstream response bytes are relayed incrementally in read order; upstream
  error statuses and response bodies are relayed. Transport errors return a
  local 502 if the response has not begun. An already-admitted request remains
  consumed in every error case.
* Admission denials return `x-should-retry: false` and `retry-after: 61`.
  These headers are client guidance, not a security boundary; the atomic slot
  is the boundary even if Claude ignores them.
* Hop-by-hop headers and headers named by `Connection` are removed. Host,
  content length, and the Phase 0 dispatch header are regenerated/consumed;
  Anthropic headers, including `anthropic-beta` and `anthropic-version`, are
  passed through without a closed allowlist. Authorization values are
  forwarded unchanged but never recorded. The body itself is never recorded.
* Evidence stores dispatch ID, ordinal/decision, UTC timestamp, body SHA-256,
  byte count, optional Claude prompt/session/request-class headers, and
  upstream status. Repeated denials are recorded as denied evidence.

## Claude loop connection

`claude_loop.prepare_claude_transport()` exposes an explicit static preflight
for `CLAUDE_BACKEND`. It returns a non-launching environment contract with
`ANTHROPIC_BASE_URL`, `ANTHROPIC_CUSTOM_HEADERS` in the documented
`Name: Value` syntax, `CLAUDE_CODE_GATEWAY_HINT_HEADERS=1`,
`CLAUDE_CODE_MAX_RETRIES=0`, and `fallback=disabled`. It rejects
`JULES_BACKEND`, `live_model=True`, and external sends. It does not spawn a
process or make a network call. Existing JULES dispatch and durable executor
paths are unchanged.

## Local verification

`automation/command_bus/tests/test_claude_admission_gate.py` covers successful
admission, duplicate and 10-way concurrent admission, missing/malformed/
unknown/terminal/expired identifiers, count_tokens and health classification,
unknown paths, exact body/header forwarding, secret/body non-logging, streaming
order and early delivery, one-shot 500/429/disconnect, denial retry hints,
optional/non-authorizing Claude metadata, separate budgets, SQLite reopen
replay protection, loopback binding, duplicate registration, and static-only
loop integration. All provider servers in these tests bind to `127.0.0.1` and
use synthetic payloads and fake credentials.

## Durability and limitations

SQLite gives a durable write-ahead claim across normal process restarts when
the same database file is retained. It does not protect against database
deletion, rollback to an old backup, storage corruption, multiple hosts using
different DB files, or an operator bypassing the gate. Production must place
the database under host-controlled durable storage, back it up without rollback
semantics, and enforce egress so the Claude process can reach only the gate
while only the gate can reach the approved Anthropic destination. This code
does not configure that network policy.

The server is loopback-only and does not provide TLS or dispatch-registration
authentication; its registration API is a local in-process host API. Upstream
destination authorization, proxy egress policy, lifecycle/terminal receipt
integration, OS-specific process isolation, and actual Claude compatibility
remain unproven. A request failure after upstream bytes have started cannot be
converted into a fresh JSON error response; the consumed slot still prevents
a second upstream attempt. The implementation must not be exposed to an
untrusted local user/process.

`CLAUDE_CODE_MAX_RETRIES=0`, `x-should-retry`, and `retry-after` are additional
client-side hints only. Safety does not infer that they stop every Claude
continuation. The gate denies all later generation requests independently.

## Prior art, attribution, and licenses

The implementation in this repository is original Python using only the
standard library. **No source code was copied or adapted** from the following
reviewed candidates; consequently, no third-party code notice is required for
this implementation. They informed the design boundaries only:

| Project and exact inspected revision | License | Reviewed file / relevant concept | Adaptation |
| --- | --- | --- | --- |
| [`terok-ai/terok-sandbox`](https://github.com/terok-ai/terok-sandbox/tree/12ccdbf527f95bbcd92ecd4704721e4f709526d2) — `12ccdbf527f95bbcd92ecd4704721e4f709526d2` | Apache-2.0 | `src/terok_sandbox/vault/daemon/token_broker.py`: proxy/stream/header/audit boundaries | None; no code or credential subsystem copied |
| [`terok-ai/terok-executor`](https://github.com/terok-ai/terok-executor/tree/8a4b64faedb6ef3de68bb31fba21d50184977794) — `8a4b64faedb6ef3de68bb31fba21d50184977794` | Apache-2.0 | `src/terok_executor/resources/agents/claude.yaml`, `src/terok_executor/resources/providers/anthropic.yaml`: Claude/gateway configuration examples | None; no configuration or token handling copied |
| [`100yenadmin/hermes-claude-agent-sdk`](https://github.com/100yenadmin/hermes-claude-agent-sdk/tree/e611437f7a97a67eacee95c3fb7ff0f2f3fe6d5f) — `e611437f7a97a67eacee95c3fb7ff0f2f3fe6d5f` | MIT | `docs/ownership-recovery/native_recovery_probe.py`: local endpoint classification | None; no probe code copied |
| [`NousResearch/hermes-agent`](https://github.com/NousResearch/hermes-agent/tree/eafb4186a4e8be7ac0ca94d69b10c57e0154aee8) — `eafb4186a4e8be7ac0ca94d69b10c57e0154aee8` | MIT | `evals/directsdk_cache_wire.py`: fake Messages/SSE peer | None; no fixture code copied |

The [Anthropic gateway guide](https://code.claude.com/docs/en/llm-gateway),
[gateway protocol](https://code.claude.com/docs/en/llm-gateway-protocol), and
[environment-variable reference](https://code.claude.com/docs/en/env-vars) are
behavioral documentation, not source-code inputs. They document the Messages
path and optional count_tokens path, pass-through headers, streaming behavior,
custom-header syntax, gateway hints, retry response hints, and that setting
only `ANTHROPIC_BASE_URL` does not replace a saved claude.ai subscription
credential. No credential discovery, injection, refresh, or API-key creation
is implemented here.

## Safety record for this batch

Real Claude executions: 0. Real Anthropic requests: 0. Real credentials read,
created, or used: 0. Jules dispatches: 0. Workflow dispatches/reruns: 0.
Merge/default-branch writes/force pushes/deletes: 0. `retry=0`,
`fallback=disabled`.
