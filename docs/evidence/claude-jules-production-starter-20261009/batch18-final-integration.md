# Batch 18 (2026-10-09 JST): final integration: Routine → Starter wiring, label history, LIVE write adapter, recovery

In this batch there was no LIVE run:

* no label was added and no Jules task was started;
* #338 is unchanged and slot 10 is unused;
* the Routine, its triggers and its schedule are unchanged (v1.5.1);
* nothing touched usage credits, Billing, settings or an API key;
* there was no Merge and no force push.

## 1. Fresh readback

* main is `702497c`.
* #340 is a Draft at `ecac6d9`; CI `offline-validation` pass; MERGEABLE.
* #338 is unlabeled and was last updated 2026-10-08T18:04:22Z.
* The ledger has 9 slots. The data branch is at `7e77885`.
* The Routine has had no run after GRD-001.
* `jules-chat-semiauto.yml` is still `177c614`.
* The repository is **PRIVATE**.

## 2. Routine → Starter wiring (what is known, and how)

**Official documentation** (code.claude.com/docs/en/routines):

* GitHub triggers are Pull request and Release only.
* Events over the caps are dropped.
* The schedule minimum is 1 hour.
* A run is a full cloud session that runs shell commands in the cloned default branch.
* With usage credits on, routines can continue on metered overage.

**Observed** in the earlier Routine run logs (read-only):

* the runs used `python3`, `git` and `date` in Bash;
* GitHub reads and writes went only through the GitHub MCP tools;
* no MCP call read issue events;
* the trigger context recommends `gh api …`, but no run used it.

**Design** (`routine-prompt-v1.6-draft.md`, the final apply candidate):

* the same reviewer run continues with **LAYER 4**: one deterministic command
  (`claude_jules_starter_gh tick --live-authorization …`);
* the reviewer never chooses a label write;
* the command writes only what the starter and loop decide, under a human-approved authorization;
* LAYER 4 first checks `gh auth status`. Without it there is no label history, so nothing starts.

**Result:** the wiring is complete as code and prompt. **Whether it runs inside a Routine is UNKNOWN until a
probe run** (checklist step 3).

## 3. Label history

* **Locally (real, read-only):** `gh api --paginate repos/…/issues/335/events` and `…/timeline` both return the
  `labeled jules` event of #335 (17:53:06Z). #338 has 2 events and no label event.
* **No token:** an unauthenticated GET returns 404 (private repository). There is no token-less path.
* **Routine:** a `gh` path is UNKNOWN. The MCP tools seen expose no events read. So `gh` (or another
  authenticated GET of the events API) is required.
* **Changes in code:**
  * `gh_get` now separates `NotFound` (404) from `ReadFailed` (auth, permission, 5xx, timeout). A permission
    error can no longer look like "issue missing" or "no history".
  * Every page is read (`--paginate --slurp`).
  * The snapshot carries `label_events_complete: true` only after a complete read.
  * The starter returns `DEFER LABEL_HISTORY_UNKNOWN` without it. That issue waits and other work continues.
* **No substitute proof exists:** "no label now + no intent + no Jules comment" does not prove the label was never
  added and removed, so it is not accepted.

## 4. LIVE write adapter (`claude_jules_starter_live.py`)

`GhLiveWritePort` = `GhLoopPort` reads plus the writes the loop needs: intent / start receipt / checkpoint
comments, `jules` on an authorized campaign issue, and campaign task issues.

**Prepare-only by default.** It sends only under a valid `CLAUDE_JULES_LIVE_AUTHORIZATION_V1` record:

* the campaign and repository match;
* a named human approved it, with an approval reference;
* it has not expired, and it is re-checked before every write;
* it names the GitHub-native subscription route;
* it carries `usage_credits_confirmed_off: true`;
* it limits the writes: allowed kinds, allowed issues, a label budget and a write budget.

**Refused writes:**

* any comment that is not a loop record, including any `@`-mention;
* any label other than `jules`;
* any issue outside the authorization;
* an issue body without this campaign's task block.

**Sending:**

* a timeout or a failed exit gives `WriteOutcomeUnknown`, and it is never retried;
* the cache is dropped after each write, so the readback is fresh.

**The template** `live-authorization-prd-c2.TEMPLATE.json` is invalid by construction: no approver, and credits
not confirmed. A real read-only tick with it gives `live: false`, `sent: []`, and names both reasons
(`live-readonly-tick-prd-c2-b18.json`).

**Tests** (`test_claude_jules_starter_live`, 9) use a fake runner that applies the POSTs to the mock GitHub:

* the real adapter code runs intent → label → receipt with exactly one label;
* a duplicate wake sends nothing new;
* a label timeout is never retried, and a fresh run within the lease sends nothing;
* the authorization limits, expiry and budgets hold;
* gh exit codes are classified.

## 5. Recovery: no dependence on "the next PR"

* **The PR event is the heartbeat.** `pull_request.closed` (merged) resumes merge-dependent work. An hourly
  schedule recovers what no event will ever wake:
  * a dead run after PASS, an issue creation, an intent or a label;
  * a dropped event;
  * a quota reset;
  * an outage end;
  * a lease expiry.
* **Proven in the mock:** `test_no_new_pr_event_after_a_crash_needs_the_recovery_wake`.
  * With the schedule, B starts and passes.
  * Without it, B stays unstarted with exactly 1 Jules start: the loop waits for a human "Run now".
  * **So the production recovery wake is not connected: UNKNOWN, and production is not complete.**
* **Found and fixed:** a running task whose review cannot proceed (unreadable receipt) or whose PR never comes
  looked like "running" forever. Now every running task gets an in-flight record:
  * `JULES_PENDING`, `REVIEW_PENDING`, or `RECORD_UNREADABLE` (human);
  * it escalates after `stall_escalate_minutes` (default 720) even while other work continues.
* Every isolated task is now listed in `human_actions`.

## 6. PRD-C2 fault matrix (`test_claude_jules_prd_c2_faults`, 19 scenarios, all PASS)

In every scenario, A PASS → B created → B started → B PASS without a human step and without a Merge, exactly 2
Jules starts, and no issue labeled twice. The faults:

* the reviewer dies before reviewing A;
* a restart after the PASS receipt (no tick in that run);
* Claude dies after creating B;
* the starter dies after B's intent;
* a death before B's label;
* B's label response is lost;
* B's intent response is lost;
* B's start receipt response is lost;
* a restart after B's label, and after A's label;
* duplicate PR events and duplicate wakes;
* a lost PR event;
* a GitHub read outage;
* a GitHub write outage;
* quota exhausted, then reset, with no new PR event.

Plus the cases that must not run to the end:

* **edited B issue:** isolated, reported in `human_actions`;
* **malformed receipt on A:** nothing written over it; `RECORD_UNREADABLE`, human-required;
* **merge dependency variant:** B waits `MERGE_WAIT`, and the merged event alone resumes it;
* **no new PR event after a crash:** the recovery wake is required, as above.

Stale controller and stale generation are covered at the starter level (`RecoveryTests`,
`NegativeTests.test_stale_generation_wake`).

## 7. Endurance (re-run after the loop changes; `e2e-loop-stats.json`)

| Rounds | Merged | Jules starts | Max labels per issue | Correctives | Loop crashes | Faults fired |
|---|---|---|---|---|---|---|
| 40 | 40/40 | 40 | 1 | 8 | 10 | 20/20 |
| 100 | 100/100 | 100 | 1 | 18 | 27 | 50/50 |
| 300 | 300/300 | 300 | 1 | 64 | 67 | 150/150 |

## 8. Tests

| Suite | Result |
|---|---|
| WSL full suite | **2164 tests, OK (skipped=1)** |
| Focused | PRD-C2 faults 19, live adapter 9, loop 31, starter 61, starter E2E 5, gh adapter 3, route separation 13, review 25, protocol 22, provider route 23 |
| Windows | 188 OK |

## 9. STATIC vs live

| Item | Status |
|---|---|
| Jules → PR → review → corrective → PASS | live-proven earlier |
| PASS → next Jules automatically | **mock only** |
| Routine running LAYER 4 | **UNKNOWN** (`gh` in Routine) |
| Recovery wake | **not connected** (human) |
| Usage credits setting | **UNKNOWN** (human) |
