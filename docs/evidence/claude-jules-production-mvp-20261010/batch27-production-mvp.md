# Batch 27: Production MVP fast track (STATIC + mock + local git)

Date: 2026-10-10 JST. Executor: Claude. Independent reviewer: ChatGPT.
Direction (user): build the loop that keeps working while the human sleeps; using up the SUBSCRIPTION is fine;
API keys, metered usage, paid fallback and billing changes are not. No LIVE action in this batch.

## Start readback

main `4bb5cd72ee0d9912376b0bb3b989cbb028806392`; branch `feature/claude-jules-durable-budget-guard` at
`c5978fcab2fa7e42737419fe75eb452fd3873971` (= local); Issue #338 OPEN, no labels; proof ledger 9/10 (data branch,
unchanged); open PRs touching other files only (#343 Symphony, #344 codex).

## What changed (the three drifts the user named, fixed)

| Drift | Fix |
|---|---|
| A. slot creation disabled -> a human per task | A **V2 budget declaration** decides `slot_create`. Once a human approves it, every task reserves its own slot. Proven on a real local bare git remote with two independent clones (the loser's push is rejected by git: `cannot lock ref ... is at X but expected Y`). |
| B. the 9/10 proof ledger treated as the production limit | Production budgets have their **own `budget_id` and ledger namespace** (`.../claude-jules-production-budget/<budget_id>/`) and any cap 1..9999 from the declaration. The 9/10 proof ledger is kept as-is and never counted for production. |
| C. one-issue, one-start, short-expiry authorization | `prod-authorization.TEMPLATE.json`: campaign scope, 50 activations, two-week expiry, per-wake cap 1 (the global cap is the durable ledger). The #338 pilot template stays for a one-off pilot. |

Also:

* **Reviewer findings (batch 26)**: (A) TOCTOU: right before the label the base head is re-read and the base policy
  (`descendant_untouched`) re-evaluated on the fresh head; untouched -> continue, touched / unknown -> no label this
  wake (re-checked next wake). (B) stale cache: every ledger read and readback drops the git client's cached tip.
* **Loser advances**: a controller whose slot read back as someone else's re-reads and takes the next slot
  (bounded by the cap) instead of giving up.
* **Subscription usage**: a trusted `claude-jules-quota v1` record (`CONFIRMED_EXHAUSTED`, `reset_at`) on the control
  issue makes new starts WAIT until the reset, then the loop resumes; nothing is invented when usage is unreadable;
  never an API-key fallback.
* **Next-task selection from GitHub**: without `--signals`, the planner reads `claude-jules-signal v1` blocks in issues
  by trusted writers (closed = resolved), so the backlog lives on GitHub, not in a session.
* **Human stop switch**: close the control issue or add `loop-stop`; new starts and new task issues stop, running
  work continues; removing it resumes.
* **One active-campaign directory**: v1.6 LAYER 4 reads `docs/claude-jules-loop/active/{campaign,authorization,
  budget-declaration}.json`. Starting a campaign = one Merge that adds those files; no prompt edit per campaign.

## Tests

* `test_claude_jules_durable_budget_git.py` (7, real git, local disk only): sequential contiguous slots; two clones
  race (cap 2 -> one ACQUIRED, one EXHAUSTED); loser takes the next slot; stale cached tip never used (fails without
  the fix); push landed but response lost -> ACQUIRED by readback; push never landed -> UNKNOWN, fresh wake reserves
  once; process killed after the slot -> RECOVERED, no second slot.
* `test_claude_jules_autonomous_mvp.py` (8): every wake is a NEW LIVE port over mock GitHub with a production budget
  and campaign-wide authorization, planner-chosen tasks, simulated Reviewer and Jules:
  * >= 3 tasks back to back after ONE human "start": task 1 gets a corrective, is fixed, PASS; tasks 2, 3, (4) PASS;
    faults: process killed right after a label, 5 injected GitHub read failures, duplicated webhooks, one task that
    must be isolated (needs a human merge) while the others continue, a stale controller coming back (no new slot,
    no second label);
  * session ends mid-campaign -> new controller objects resume from GitHub only;
  * budget cap 2 -> visible `BUDGET_EXHAUSTED`; human raises the cap -> the same loop continues to 4 PASS;
  * subscription usage exhausted -> WAIT (`QUOTA_EXHAUSTED`), after the reset -> 3 PASS;
  * stop switch -> nothing starts; removed -> 3 PASS;
  * production templates invalid as committed, valid after one approval fill-in; GitHub signal issues.
* durable budget unit tests now 37 (TOCTOU: fails without the fresh re-check; V2 declaration; loser advances).
* Full suite: see `checkpoint-batch27.json`.

## Still not proven (UNKNOWN)

* Pushing slot files to the data branch from a Routine cloud session (git proxy permissions). If refused, the slot is
  UNKNOWN and nothing starts (safe); fallback: another data branch or pre-written slots.
* Real Jules behaviour on a duplicate label add at the same instant; real Routine wake behaviour for Draft PRs.
* Real usage-limit messages from Jules (no text pattern is invented; the quota record is written when one is seen).
* Any real multi-task LIVE run (the target proof: 3 consecutive LIVE tasks).

## Deferred (P1)

Parallel tasks (> 1 concurrent), several providers at once, UI, automatic quota detection from provider text,
`GitLiveClient` classifying `cannot lock ref` as a definite rejection (today: "ambiguous" -> readback decides, safe),
CI-failure signals collected automatically.
