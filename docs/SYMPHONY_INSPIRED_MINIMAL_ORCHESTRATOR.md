# Symphony-inspired minimal orchestrator (Phase 0 static scope)

Status: static controller, bounded Codex app-server adapter, GitHub Contents
transport, and separate Symphony LIVE durable command/claim/result schema.
LIVE remains blocked until GitHub state is freshly verified and remote proof
postconditions can be read back.

## Shape

`automation/command_bus/symphony_controller.py` adds a single-cycle controller
and `GitHubExecutorTracker` for static PREPARE_ONLY work. The separate
`GitHubSymphonyLiveTracker` in `symphony_live_store.py` implements LIVE command,
claim, and result records without invoking or weakening the executor schema.
Both use the `ExecutorContentsClient` and target-reader interfaces. The concrete
single-request GitHub Contents transport is in `symphony_github_adapter.py`.

The request must use `symphony_profile=SYMPHONY_INSPIRED_STATIC_V1` and include
`logical_command_id` and `generation`. The existing executor validator still
requires `PREPARE_ONLY`, `requires_live_model=false`, `live_start_permitted=false`,
`retry=0`, and `fallback=disabled`. The runner gate accepts only the exact
built-in `StaticFakeAgentRunner` and `CodexAppServerAgentRunner` classes. Other
live runner objects remain rejected regardless of their `live_enabled` value.

`symphony_codex_app_server.py` implements the Codex app-server JSON-RPC JSONL
route. It is disabled by default, permits one turn submission, and reports
ambiguous submissions as UNKNOWN without resend. The maximum model-start
attempt is one; retry is zero and fallback is disabled. The GitHub transport in
`symphony_github_adapter.py` makes one Contents API request per operation, does
not follow redirects or retry, and is intended to sit under the existing
`GitHubExecutorBackend`, which performs PREPARE_ONLY write readback.

`GitWorkspaceVerifier` checks the configured proof worktree before dispatch:
clean status, exact branch, repository identity, HEAD, and tree. After the single
turn it verifies one normal commit whose parent is `head_before`, exact changed
path, exact proof content, and clean final status. It reports local verification
only. It cannot establish remote force-push, merge, or default-branch counts.

LIVE records use a distinct `record_type` and path family:
`symphony_live/commands/<command_id>.json`,
`symphony_live/claims/<command_id>.json`, and
`symphony_live/results/<command_id>.json`. Commands bind command/correlation,
generation, target repository/branch, target HEAD/tree, expiry, the sole allowed
proof path, and execution limits. Claims are create-only and permanently fence
redispatch. Terminal results record `head_before`, freshly read `head_after`,
dispatch/model-start counts, retry count, status, and `terminal=true`. Every
write is followed by exact readback; an uncertain write gets readback only and
is never resent. Model-start count may be null when an interrupted submission
cannot be proved either way. A missing complete proof verification cannot be
reported as PASS.

Each cycle reconciles current durable state, filters one eligible request, and
checks expiry, generation, target HEAD, duplicate logical identity, claim and
terminal receipt. It writes one durable claim before the fake runner. After
dispatch, it writes a result and terminal receipt through the existing backend;
all writes are read back. Ambiguous claim writes stop before runner invocation.
Ambiguous result/receipt writes are read back only and never resent. A claim
without a receipt is a permanent no-redispatch fence, including after restart.
Carrier HEAD is kept as evidence and is never compared to target HEAD.

`run_forever()` polls immediately, then waits the configured interval (default
30,000 ms); `stop()` requests graceful shutdown after the active cycle. Idle
cycles make no claim or receipt writes and invoke no runner.

## Difference from official Symphony

Symphony supplies the high-level ideas used here: long-running tracker polling,
reconciliation on each tick, bounded dispatch, and an agent-runner boundary.
Its current spec defaults to `max_concurrent_agents=10` and `max_turns=20`, and
includes continuation/retry/backoff and stalled-worker handling. This Phase 0
adaptation fixes concurrency to one, one turn, retry zero, fallback disabled,
no automatic redispatch, and durable claim/terminal receipt fences. It requires
an exact target-head check and does not merge or start a live model. See the
[official README](https://github.com/openai/symphony/blob/main/README.md),
[SPEC.md](https://github.com/openai/symphony/blob/main/SPEC.md), and
[Elixir reference README](https://github.com/openai/symphony/blob/main/elixir/README.md).

The upstream repository declares Apache-2.0 and includes a NOTICE file. This
change reuses **no upstream source code**; it records design concepts only, so
no copied-code attribution block or additional LICENSE/NOTICE file is needed.
The official Elixir implementation itself warns that it is prototype software
for evaluation and recommends building a hardened implementation from the spec.

## Recovery and known limitations

- A durable claim without a terminal receipt is UNKNOWN/blocked for redispatch;
  elapsed time alone does not prove the old attempt stopped.
- The existing executor request validator admits PREPARE_ONLY requests only and
  its result schema enforces `model_executed=false`. That contract remains
  untouched; the Symphony LIVE store is isolated by `record_type` and path.
- Only explicitly marked `PREPARE_ONLY` executor requests are admitted. Existing
  generic `commands/` records are not silently reinterpreted as runner work.
- The exact Codex adapter class is admitted, but this does not authorize LIVE
  by itself; its constructor defaults `live_enabled=False`.
- The local app-server adapter does not itself prove remote branch push,
  force-push count, merge count, or default-branch immutability. Those must be
  supplied by fresh GitHub readbacks before any LIVE result can be PASS. The
  current adapter emits `LOCAL_PASS`; the durable store keeps that result
  UNKNOWN until complete remote evidence is present.
- Service installation, credential provisioning, a CLI entry point, workspace
  lifecycle, and unattended process supervision remain unimplemented.
- The in-process loop does not force an immediate repeat after UNKNOWN; the
  durable reservation prevents redispatch when the next poll occurs.

Validation is static/unit only. Tests use fake GitHub contents and a fake
app-server; they do not contact GitHub or start any model/provider.
