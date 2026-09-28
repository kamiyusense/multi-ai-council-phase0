# Status workflow dispatch/readback v1 — static checkpoint

## Baseline

- Baseline main: `3e14cb41ce3a30f9b17e3ac4837fe587caf89e25`.
- PR #66 was merged before this batch.
- Issue #33 remained `STOPPED` with zero comments at the starting readback.
- No live Status workflow dispatch is performed by this batch.

## Implemented static boundary

`runtime_transition_status_dispatch.py` adds a transport-neutral coordinator for
the next Status boundary step.

It accepts an already prepared `PreparedStatusWorkflowCall` and requires:

1. trusted executable workflow path `.github/workflows/loop-status-signal.yml`;
2. executable code ref `main`;
3. caller inputs exactly `loop_id` and non-default `state_ref`;
4. a pre-dispatch workflow-run identity snapshot;
5. at most one dispatch call;
6. a post-dispatch workflow-run readback;
7. exactly one new workflow run after a confirmed submit;
8. `workflow_dispatch`, `main` code ref, and `run_attempt == 1`;
9. terminal workflow conclusion `success`;
10. fresh Issue #33 readback matching the expected Runtime title, loop identity,
    generation and durable receipt identity.

The Issue check binds the human-facing display to:

`generation <generation>; receipt <event_id>`

which is the same durable progress string produced by the deployed Status
workflow.

## Retry / ambiguity behavior

- retry remains `0`;
- an exact call may be attempted only once per coordinator instance;
- a dispatch exception is treated as ambiguous;
- ambiguous dispatch still performs one workflow-run readback but is **not**
  promoted to success from run appearance alone;
- the same call is not automatically resent;
- zero or multiple newly observed runs are `UNKNOWN`;
- a rerun (`run_attempt != 1`) is rejected;
- a nonterminal run is `UNKNOWN`; this coordinator does not poll;
- a terminal non-success run is `BLOCKED`;
- Issue title/body mismatch is `UNKNOWN`.

The in-memory replay guard is not claimed as a production durable exactly-once
mechanism. A future live GitHub transport must preserve the repository's durable
retry=0/replay policy rather than treating this static guard as sufficient.

## Test coverage added

The mock tests cover:

- one confirmed dispatch -> one new run -> success -> exact Issue projection;
- ambiguous dispatch readback without resend;
- same-call replay guard;
- missing/multiple new run;
- wrong workflow, event, code ref or rerun attempt;
- nonterminal run;
- failed workflow conclusion;
- Issue number/state/title/runtime-block mismatch;
- invalid prepared call blocking before any transport activity.

The existing Status test workflow is extended so the new module and test file
trigger the workflow and the new test is part of the focused suite. The full
command-bus suite still runs with zero-failure policy.

## Exact-head verification

- Exact tested code head:
  `3bfca1fa5321a0f2d978b456efbe43f7b5a889e6`.
- GitHub Actions run:
  `36370576064` — **SUCCESS**.
- Focused Status/runtime/validation suite:
  **155/155 PASS**.
- Full command-bus suite:
  **442/442 PASS**.
- Command-bus JSON schemas parsed:
  **16/16 PASS**.
- Python compileall:
  **PASS**.
- `git diff --check`:
  **PASS**.
- PR #68 was OPEN / mergeable=true at exact-head readback.
- The commit after this exact tested code head is documentation-only checkpoint
  evidence and must be compared before Merge.

## Explicitly not performed

- no real `workflow_dispatch`;
- no Issue #33 mutation;
- no owner event/provider observation creation;
- no Jules/Claude/provider/model execution;
- no SEMI_AUTO/AUTO acquisition, handoff or takeover;
- no default-branch direct write;
- no Merge in this batch.

## Remaining production boundaries

1. A concrete GitHub Actions transport for this interface, with durable
   cross-session replay protection/correlation.
2. Production authority-grant issuer.
3. Production independent AuthorityGrantVerifier.
4. Production ProviderVerifier.
5. Explicit approval before the first real Status dispatch/Issue #33 mutation.
6. Real SEMI_AUTO/AUTO acquisition/handoff/takeover remains last.
