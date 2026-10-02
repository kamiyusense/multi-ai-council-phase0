# LIVE proof configuration (2026-10-02) — evidence only, never a normal config

These two files are the exact inputs of the LIVE proof of the Claude × Jules AUTO
loop. They live here, **outside** `automation/command_bus/config/`, so they can never be
picked up as the normal operating configuration.

| File | What it is |
|---|---|
| `policy.live-proof.json` | One-off policy: isolated target `claude/autoloop-live-target`, lane label `J-GREEN`, PR 220, Loop A total LIVE budget 10, authorization **expired 2026-10-02T15:00:00Z**. |
| `roadmap.live-proof.json` | The three-task roadmap (live proof note, budget summary helper, operator quickstart). |

The normal policy is `automation/command_bus/config/claude_jules_autoloop_policy.json`: it
grants no target branch, no lane and no live authorization.

## Rules

- Do not copy these files into `config/` and do not extend the expiry or the budget.
  The Loop A LIVE budget is a fixed total of 10 (4 used) kept in the create-only ledger on
  `claude/claude-jules-autoloop-data` (`.../claude-auto-live-budget/slot-NN.json`); it is
  never reset by changing a file.
- The ledger, dispatch intents/receipts, inspections, adoption receipts and owner events on
  that data branch are evidence and must not be deleted or re-initialised.
- A new LIVE test needs a new, explicit human approval and a new policy file; this one is
  history.

## How the proof ran (for reproduction of the read-only views)

The origin loop id was `claude-auto-loop-a-001`; the lane label `J-GREEN`.

```text
python3 -m automation.command_bus.claude_jules_live <command> \
  --policy docs/evidence/claude-jules-autoloop-20261001/live-proof-2026-10-02/policy.live-proof.json \
  --roadmap docs/evidence/claude-jules-autoloop-20261001/live-proof-2026-10-02/roadmap.live-proof.json \
  --origin-loop-id claude-auto-loop-a-001 --lane-id J-GREEN
```

`status`, `budget`, `observe`, `poll` and `carrier` are read-only. `step`, `takeover`,
`renew`, `handback`, `reclaim` write; do not run them again without a new approval.

Results (command, Jules session, result PR, candidate head, verdict) are in
`../checkpoint.json` under `live_runs`.
