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

## URL and production upstream boundaries

The Claude-facing `ANTHROPIC_BASE_URL` preflight has explicit transport modes.
`HOST_LOOPBACK` is the safe default and accepts only plain HTTP to a literal
loopback IP with an explicit nonzero port (`127.0.0.1` or `[::1]`). It rejects
hostnames, including `localhost` (name resolution can vary), remote or
private-network addresses, user-info, query, fragment, and non-root paths.
`CONTAINER_INTERNAL` is opt-in and restricted to exact `http://gate:8080`; it
freshly loads the static manifest and requires the topology validator to return
PASS, including network membership, the Claude URL and gate bind address/port,
and unpublished-port checks. Other service names and all direct IP addresses
remain denied. PREPARED output records mode, validated endpoint, and topology
state.

The production transport accepts only `https://api.anthropic.com` on default
port 443, with no URL credentials, path prefix, query, or fragment. The fake
provider path is a separate `test_only_upstream_factory` argument and accepts
only plain HTTP to an explicit loopback IP and port. It is forbidden in
container mode.

## Docker network contract (static; never started here)

`automation/command_bus/claude_gate_compose.yaml` is a JSON-form Compose
manifest template with placeholder `UNBUILT` images, a
`human-approval-required` profile, and `/bin/false` entrypoints. It is not a
runnable deployment. The deterministic validator requires:

* Claude service: internal network only, no `ports`, no `network_mode`,
  `privileged: false`, and no `extra_hosts`/`links` overrides.
* Gate service: internal and egress bridge networks, no published ports,
  `privileged: false`, binds only to internal address `172.29.247.2:8080`
  (never `0.0.0.0`), production store and production upstream. It cannot use
  the fake upstream factory in container mode.
* Internal network: bridge with `internal: true`; Claude is not attached to
  the separate egress network. Gate alone joins both.

This follows Docker's documented Compose networking ([networking guide](https://docs.docker.com/compose/how-tos/networking/),
[network reference](https://docs.docker.com/reference/compose-file/networks/)).
It is static intent, not proof of daemon routes, host firewall, subnet
availability, or running-container membership. Docker was not invoked. A
human must resolve subnet conflicts and verify effective egress before live
use.

## Dispatch lifecycle and command-bus receipt linkage

`ClaudeDispatchLifecycle.prepare()` accepts an explicit transport mode (safe
default `HOST_LOOPBACK`), creates a UUID, and records loop ID,
correlation ID, `CLAUDE_BACKEND`, generation, expiry, and exact target head,
then returns the local gate environment as `PREPARED`. It never invokes a
process launcher. Invalid transport after registration terminalizes/burns the
dispatch; it must not be reused. `complete_fake()` models a terminal result
with a fake-only outcome and writes an append-only local terminal receipt.
Mismatched/repeated terminal transitions fail closed.

The lifecycle consumes the existing command-bus executor receipt shape:
`state=CONSUMED`, loop/correlation, `round` mapped to gate `generation`, and
`expected_target_head`. A matching receipt is NO-OP; a conflicting generation,
head, or state for the same correlation blocks. This is a static in-process
adapter, not a GitHub poller: the caller must supply freshly read receipts.
The gate request path never writes to GitHub.

## First-store bootstrap (separate from normal startup)

Normal startup is `OPEN_EXISTING_ONLY`: `DispatchStore.open_production()` only
accepts an already-existing DB after validating the fixed path, platform access
policy, externally supplied `expected_store_id`, and complete existing schema.
Identity/schema validation is read-only; production open refuses schema repair
or migration and never calls bootstrap.
On Windows, production open remains BLOCKED because ACL verification is not
implemented.

The explicit `prepare_production_store_bootstrap()` is read-only and requires
`explicit_bootstrap=True`, an existing empty private `claude-gate` state
directory, an absent external receipt at
the fixed host-control-plane sibling path `claude-gate-bootstrap-receipt.json`,
no externally retained expected store ID, `retry=0`, and fallback disabled. It
refuses any file in the state directory, an existing DB, an existing receipt,
or unknown state. On POSIX, both state and external receipt directories must be
host-owned and private. Windows production bootstrap is blocked; the narrow
Windows test-fixture exception accepts only OS temporary directories.
`initialize_production_store_once()` revalidates, then
atomically claims the one-time attempt by creating the external receipt with
status `INITIALIZING` using exclusive-create semantics before creating the
fixed `dispatches.sqlite3`. It generates the store UUID, finalizes the receipt
with status, timestamps, state-directory identity hash, DB filename and SHA-256,
and returns that record for the host/control plane to retain. The receipt does
not contain credentials or the raw state path. Retry is never attempted.

An interrupted attempt leaves its receipt marker behind and is burned; a
partial marker or missing DB is UNKNOWN/BLOCKED for manual recovery, not a
reason to bootstrap again. After a successful bootstrap, deleting the DB while
the host receipt remains is treated as deletion/corruption and a second
bootstrap is refused. This distinguishes first initialization from known
disappearance. If the external receipt itself is lost, this local mechanism
cannot prove whether the state is new; that condition is UNKNOWN and must not
be auto-reinitialized. The bootstrap API also blocks if the host supplies an
already-retained expected store ID, even when the DB or receipt is missing.

Future named-volume initialization order is fixed:

1. Host/control-plane one-time bootstrap into an empty, privately owned volume
   (or a separately designed one-shot bootstrap container that is not the Gate
   runtime and is never part of normal startup).
2. Capture the returned store ID and receipt in host/control-plane durable
   storage outside the volume.
3. Supply that retained ID as `PHASE0_GATE_EXPECTED_STORE_ID`.
4. Start the ordinary Gate only in `OPEN_EXISTING_ONLY` mode and compare the
   existing DB ID with the external value. Missing DB, missing input, or any
   mismatch blocks startup; there is no bootstrap fallback.

This batch does not create a real production volume or run a bootstrap. The
Windows-only test-fixture exception is constrained to OS temporary directories;
it does not enable Windows production bootstrap. Full anti-rollback remains a
known limitation: an older DB copy can carry the same store ID. A later design
may compare a GitHub durable receipt, monotonic generation, or external store
epoch. Whether complete anti-rollback is mandatory before a narrowly scoped
single live proof is a separate decision; it must be reassessed before any
unattended overnight operation.

## Durability and limitations

SQLite gives a durable write-ahead claim across normal process restarts when
the same database file is retained. Production open requires an existing
`dispatches.sqlite3` directly under the supplied fixed state directory and an
externally expected store UUID. It refuses to create a fresh production DB on
startup. The Compose contract mounts named volume `gate-state` at that fixed
directory and requires the expected UUID to be injected from host/control-plane
environment `PHASE0_GATE_EXPECTED_STORE_ID`; the gate must not generate its own
expected identity. Startup compares the existing database identity with that
external value. Empty volume, missing database, missing/unknown/replaced ID, or
mismatch must block startup and never auto-create a trusted production store.
Container recreation may reuse the volume only after rechecking the same
external expected ID. POSIX ownership/mode checks are required; ACL verification
is UNKNOWN on Windows, where production open refuses. The expected ID detects
replacement by a newly initialized DB, but not rollback to an older copy with
the same ID.

Deletion, old-backup rollback, corruption, separate per-host DBs, and operator
bypass remain possible. The host must protect the DB and directory (0700/0600
or stricter), keep them outside untrusted container mounts, and compare against
monotonic external receipts. Complete anti-rollback remains unresolved.

The host server is loopback-only and does not provide TLS or
dispatch-registration authentication; registration is an in-process host API.
The separate container contract binds only to a fixed internal-network IP.
Host firewall/Docker route enforcement, crash consistency with external
receipts, OS-specific process isolation, and actual Claude compatibility
remain unproven. A request failure after upstream bytes have started cannot be
converted into a fresh JSON error response; the consumed slot still prevents
a second upstream attempt. The implementation must not be exposed to an
untrusted local user/process.

`CLAUDE_CODE_MAX_RETRIES=0`, `x-should-retry`, and `retry-after` are additional
client-side hints only. Safety does not infer that they stop every Claude
continuation. The gate denies all later generation requests independently.

`POST /v1/messages/count_tokens` remains `DENY_LOCAL` and
`DOES_NOT_CONSUME_GENERATION_BUDGET`. If future live compatibility testing
shows it is required, that result is UNKNOWN and the live proof must stop;
there is no automatic forwarding. `HEAD /api/hello` remains local, and
unknown endpoints remain denied.

Current `JULES_BACKEND` prepares the existing Jules durable request and does
not start a Claude reviewer process, so it is unchanged. Any future Claude
reviewer/planner process within that backend must use this same Admission Gate,
dispatch metadata, one-generation budget, local gate URL, and egress isolation.

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
