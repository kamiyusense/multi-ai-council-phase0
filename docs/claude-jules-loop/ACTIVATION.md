# Claude × Jules loop: how to start a long-running campaign

One approval starts a campaign; after that the loop chooses, starts, reviews and continues tasks by itself until
the budget, the expiry, the human stop switch or the objectives end it. Only the subscription route is used.

## Human steps (once per campaign)

1. **Merge the code PR** that contains the loop (budget guard, planner, LIVE port).
2. **Merge one activation PR** that adds `docs/claude-jules-loop/active/`:
   * `campaign.json` from `docs/evidence/claude-jules-production-mvp-20261010/prod-campaign.TEMPLATE.json`:
     approved objectives (scope paths, allowed operations). `control_issue` is **required** (prepared: #346); without
     an existing, OPEN control issue without `loop-stop`, no Jules start and no new task issue happens;
   * `authorization.json` from `prod-authorization.TEMPLATE.json`: `approved_by`, `approval_ref`, `expires_at`,
     `max_activations`, `usage_credits_confirmed_off: true` (Settings → Usage: credits OFF, so nothing spills into
     metered usage);
   * `budget-declaration.json` from `prod-budget-declaration.TEMPLATE.json`: `approved_by`, `approval_ref`, `cap`.
   Claude can prepare this PR; the approval is the human's Merge.
3. **Routine UI, once**: paste `routine-prompt-v1.6.CANDIDATE.txt` (Raw view) and, for overnight recovery, add an
   hourly schedule to the same Routine.
4. **Go**: one "Run now" (or the next PR event).

## First work is already on GitHub

`initial-backlog.json`: control issue #346 and three signal issues #347-#349 (real Windows-only `read_text()`
encoding bugs in three independent test files), created by `kamiyusense` without labels. A read-only tick against
live GitHub with the template filled in locally planned the first task from them and sent nothing
(`readonly-tick-rehearsal.json`).

## While it runs

* Work comes from signal issues: an issue by a trusted writer containing
  `<!-- claude-jules-signal v1 {"signal_id": "...", "objective_id": "...", "kind": "failing_test", "summary": "...",
  "paths": ["..."], "evidence": ["..."]} -->`. Closing the issue marks the signal resolved.
* **Stop**: close the control issue or add the label `loop-stop` (works from a phone). Remove it to resume.
* **Usage exhausted**: the loop waits for the reset and resumes; it never switches to an API key.
* **Budget used up**: `BUDGET_EXHAUSTED` is shown on every wake; raise `cap` / `max_activations` with one Merge.
