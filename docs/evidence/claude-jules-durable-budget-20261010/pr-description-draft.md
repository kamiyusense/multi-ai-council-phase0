# Draft PR (prepared, NOT opened): Durable cross-wake LIVE budget guard for the Jules label

Head branch `feature/claude-jules-durable-budget-guard` -> base `main` (`4bb5cd7`). Draft. Do not merge without
separate human approval and independent review.

**Why not opened yet:** the existing Reviewer Routine has a GitHub trigger on `pull_request.opened` and
`pull_request.synchronize` for this repository (batch 10, trigger `ed6e9a1c…`, no filter recorded). Opening a PR
may start a model run that nobody approved for this batch. Whether it fires for a Draft PR is UNKNOWN. A human
decides whether to open it (the CI `offline-validation` only runs on pull_request events).

## What

* `claude_jules_durable_budget.py`: global LIVE budget from the existing create-only slot ledger (9/10), the cap
  from a human-merged declaration, slots bound to one activation, readback decides, creation disabled.
* `GhLiveWritePort.add_label`: V2 authorization + durable budget + fresh pre-label checks; no label after an
  unknown label outcome in the same wake.
* loop: `BUDGET_EXHAUSTED` is a visible, human-required isolation, re-checked every wake.
* probe: first-page `rel="last"` without `next` is UNKNOWN.
* v1.6 candidate: the LIVE command also needs `--budget-declaration`.

## Evidence

`docs/evidence/claude-jules-durable-budget-20261010/batch26-durable-live-budget-guard.md`, `checkpoint-batch26.json`,
`old-main-per-wake-cap-hazard-reproduction.txt`. Local: 2262 tests OK (skipped=1); 33 new budget tests.

## Not done / human

No LIVE. Budget declaration, V2 authorization, slot-10 record, enabling slot creation, v1.6 apply, triggers,
schedule, slot 10: separate human approvals.
