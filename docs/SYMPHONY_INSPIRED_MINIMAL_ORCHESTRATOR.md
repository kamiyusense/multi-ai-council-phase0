# Symphony-inspired minimal orchestrator (Phase 0 static scope)

Status: static controller core and fake GitHub-backed executor tests only.
No live provider/model runner is implemented or enabled.

## Shape

`automation/command_bus/symphony_controller.py` adds a single-cycle controller
and `GitHubExecutorTracker`, which adapts the existing `GitHubExecutorBackend`
request/claim/result/receipt store. A connected process supplies the existing
`ExecutorContentsClient` and a `GitHubTargetReader` that freshly reads the target
PR head/tree, carrier branch head, and active generation. Those process-level
GitHub and generation readers are interfaces; this change does not add a
credential or network client.

The request must use `symphony_profile=SYMPHONY_INSPIRED_STATIC_V1` and include
`logical_command_id` and `generation`. The existing executor validator still
requires `PREPARE_ONLY`, `requires_live_model=false`, `live_start_permitted=false`,
`retry=0`, and `fallback=disabled`. The runner gate accepts only the exact
built-in `StaticFakeAgentRunner` class; arbitrary injected or real runners are
rejected, even if they claim `live_enabled=false`.

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
- A production `ExecutorContentsClient`, `GitHubTargetReader`, and durable
  generation source are not wired to a standalone local service in this change.
- Only explicitly marked `PREPARE_ONLY` executor requests are admitted. Existing
  generic `commands/` records are not silently reinterpreted as runner work.
- Only the built-in test fake runner is admitted. A future real runner needs a separate
  approval and must preserve a hard LIVE gate, one dispatch, and ambiguity
  handling; this module alone does not authorize that work.
- Service installation, credential provisioning, a CLI entry point, workspace
  lifecycle, and unattended process supervision remain unimplemented.
- The in-process loop does not force an immediate repeat after UNKNOWN; the
  durable reservation prevents redispatch when the next poll occurs.

Validation is static/unit only. The tests use fake GitHub contents and a fake
runner; they do not contact GitHub or any model/provider.
