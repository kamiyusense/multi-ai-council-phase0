# Batch 16 (2026-10-09 JST): Production Starter, STATIC + mock

In this batch there was no LIVE run:

* no `jules` label was added, no Jules task was started, and no model or provider ran;
* slot 10 is unused;
* nothing touched an API key, Billing, Credits, Overages, settings or Reactive Mode;
* there was no force push and no branch deletion;
* the only Merge was #339, which the user approved for this batch.

## 1. Fresh readback and #339

* **Before:**
  * main `ca83d0e`;
  * #339 Draft, head `20ecbb6`, MERGEABLE, CI `offline-validation` pass, 3 docs files;
  * #330 and #337 merged; #332 and #334 closed;
  * #338 OPEN and unlabeled;
  * Routine v1.5.1 enabled, last run GRD-001 (18:01Z on 10-08);
  * ledger `slot-01`…`slot-09`; Actions idle.
* **#339:** marked ready, then merged with `--match-head-commit 20ecbb6`.
  * merge commit `702497c6b464a3b1ab09441b21fc6f96bd3bb2d0`, parents `ca83d0e` and `20ecbb6`;
  * tree `601f890` = the tree of `20ecbb6` (the CI-tested head);
  * diff against `ca83d0e`: the 3 docs files only;
  * `jules-chat-semiauto.yml` blob still `177c614`.
* **Windows full suite on main `702497c`:** 2034 tests, `failures=12, errors=27`. All of them are Windows-only
  environment problems that existed before: bash temp paths, the cp932 console, and CRLF. One of them is the
  PRD-001 task.

## 2. Architecture

```
reviewer Routine (meaning)             Production Starter (identity + policy, no judgement)
  PR event -> precheck -> semantic        wake: issues.opened / PASS receipt comment / labeled / schedule
  -> combine -> receipt                     -> snapshot (GitHub reads only)
  PASS: next issue from the manifest        -> next_step (pure function) -> one write
        (body_ref, render-next)             -> readback -> next_step ... until no write
  never labels                              writes only: intent comment, label "jules", start receipt
```

| Part | File |
|---|---|
| policy, campaign manifest, records, `next_step`, `wake_targets`, `run_starter`, CLI (`step`, `validate-campaign`, `render-next`) | `automation/command_bus/claude_jules_production_starter.py` |
| read-only `gh` snapshot and prepare-only writes (no send path exists) | `automation/command_bus/claude_jules_starter_gh.py` |
| mock GitHub, Jules and reviewer (real reviewer code) | `automation/command_bus/tests/starter_world.py` |

The Starter has no import of the provider-route guard or any dispatcher, and no network module. It only knows
`GitHub issue -> jules label`. A route observation that names an API key, REST or metered billing gives
`HARD_STOP`. An unobserved or different route gives `DEFER`, never a start. A policy with any fallback enabled
is invalid, which is a `HARD_STOP`.

## 3. Start conditions (all of them must hold, otherwise no start)

The policy and manifest are valid, and the route is GitHub-native with account OAuth and a subscription.

**The issue:**

* it exists and is OPEN;
* it holds exactly one task block with starter metadata for this campaign;
* the block hashes to the manifest's `task_sha256` (an edit is detected), and the title matches;
* repository, route, kind and base branch are allowed;
* no path is protected (`.github/`, `claude_jules_*`, `claude_closed_loop_*`);
* there is no human-boundary request (merge, default-branch write, destructive op, key, billing, settings);
* the corrective budget is within policy;
* the wake is not for an older generation.

**The records:**

* every starter record is readable;
* there is no start receipt;
* the label was never present (label history, not only the current labels).

**The predecessor:**

* it holds the expected predecessor task;
* there is exactly one trusted, strictly parsed v2 PASS receipt, with decision `ADOPT_RECORDED` and
  `next_issue` = this issue, and its identity matches;
* the predecessor PR head has not changed since PASS.
* Receipts by anyone other than the trusted writers are ignored.

**The base:** the base head is known; if main moved, none of the allowed paths changed (`descendant_untouched`;
`exact` is also available).

**Capacity:**

* within the round limit (none by default);
* fewer active Jules tasks than `max_concurrent_tasks` (default 1);
* quota is not confirmed exhausted. UNKNOWN quota follows the policy (`proceed` by default).

## 4. Durable records and duplicate resistance

All records are comments on the next issue, written by the trusted writer.

* **Intent** (`claude-jules-starter-intent v1`, `CLAUDE_JULES_STARTER_INTENT_V1`):
  * names the task, correlation, generation and `task_sha256`;
  * names the predecessor correlation and its PR head;
  * names the attempt, what it supersedes, the controller, a nonce, the policy version and the route;
  * is written **before** the label, so Jules is not engaged yet.
* **Start receipt** (`claude-jules-starter-receipt v1`): written after the label is observed. Outcome `STARTED`.
  It is terminal: any later wake is NO_OP.

| Danger | Rule |
|---|---|
| duplicate event, replay, terminal replay | the start receipt exists → NO_OP |
| label already present, or ever present | never added again (no second `labeled` event) |
| two controllers at once | the earliest attempt-1 intent wins; the other gets DEFER |
| stale controller | it re-reads before every write; another controller's intent → DEFER, a receipt → NO_OP. Even a write from an old view lands on a labeled issue, which creates no event |
| write outcome unknown | never re-sent in the same run; the next wake reads GitHub |
| intent without a label (crash, timeout) | taken over only after the lease (15 min), as attempt k+1 naming attempt k; at most 2 attempts, then BLOCKED |
| issue edited, metadata corrupt, record corrupt | BLOCKED or NO_OP for that task only, and nothing written over it |

## 5. Blocker isolation and campaign policy

* **Each decision names its scope:**
  * `task` covers bad metadata, a human boundary, a stale base, a blocked predecessor, a closed issue and
    exhausted attempts;
  * `global` covers concurrency, confirmed quota exhaustion, a paid route and an invalid policy;
  * `campaign` covers the round limit.
* A blocked task stops only its own successors, because their predecessor never PASSes. Other campaigns
  continue.
* The policy `CLAUDE_JULES_STARTER_POLICY_V1` is data, and every value can be changed:
  * concurrency, the campaign round limit (none), the corrective limit, the lease, label attempts, the ack
    timeout, read retries, allowed kinds, quota-unknown handling, the base policy, protected paths and trusted
    writers.
  * The proof slots (10-slot ledger) are not used by the Starter. Slot 10 stays in reserve.

## 6. Reviewer contract (Routine)

* **Routine v1.5.1 stays live and unchanged.** PRD-C1 is a single-task campaign, so it needs no change.
* **Multi-task campaigns need `body_ref`.** A task's `next_task` refers to the next manifest entry instead of
  inlining its body, so task blocks never nest.
* **v1.6 draft** (`routine-prompt-v1.6-draft.md`, not applied): on PASS the reviewer runs `render-next` and
  creates the issue verbatim. It still never adds a label.
* **Starter Routine draft** (`starter-routine-prompt-v1-draft.md`, not created).
* **UNKNOWN:**
  * whether the Routine webhook trigger accepts `issues` / `issue_comment` events;
  * whether the GitHub MCP can read label history. Without label history, the Starter returns DEFER and never
    starts.

## 7. Tests (counts in `checkpoint-batch16.json`)

| Area | What is tested |
|---|---|
| start sequence | intent, then label, then receipt, then NO_OP; checks named before any write; replay never relabels; issue-before-receipt DEFER, then the receipt event starts it |
| negative cases | the 22 required cases + forged receipt, receipt naming another issue, predecessor head changed, protected path, other route, unknown route, policy fallback, stale base (moved / unknown / untouched / exact), unrelated issue, task without metadata, corrupt record, corrupt manifest, label removed after start, unread label history |
| recovery | crash before or after the intent, intent response lost, label response lost, label timeout, restart before the label, crash after the label, bounded attempts, two controllers racing, a stale controller after takeover, duplicate events after restart, issue edited after the intent |
| capacity | concurrency, quota exhausted until reset, quota unknown follows policy, round limit, configurable policy |
| mock E2E | see the table below |
| adapter | the `gh` snapshot gives the same step as the mock; writes are prepared, never sent; only GET requests |
| route separation | the Starter is closed-loop code: no key or REST strings, no guard, dispatcher or network imports; the semi-auto workflow does not know it |

**Mock E2E** (`e2e-stats.json`):

| Scenario | Results | Faults and restarts |
|---|---|---|
| 12 rounds (campaign A) + campaign B | 15 PASS receipts, 2 NEEDS_CORRECTION; B2 human-boundary BLOCKED, B3 never prepared | 214 controller runs, 3 crashes, 5 injected faults all fired, a reviewer crash after the next issue, every 3rd webhook delivered twice, a stale controller on every issue |
| 40-round endurance | 41 PASS receipts (40 + seed), 8 correctives | 30 random faults (one per task) all fired, 13 crashes, 1277 controller runs, 322 events |
| others | quota exhaustion and reset; 2 campaigns sharing 1 concurrency slot (max 1 active); corrective budget exhausted → TASK_BLOCKED, successor never prepared | — |

In every scenario the invariant held: **no issue had more than one `labeled jules` event, and no Jules task was
started twice.**

## 8. LIVE-ready preparation

`live-plan-prd-001.md` holds the exact task, the expected predecessor and head, the correlation, the
generation, the acceptance criteria, the intent and receipt, the recovery plan and the stop conditions.

A read-only run against live GitHub (`live-readonly-dryrun-338.json`) gave:

* #338 as it is → IGNORE;
* with the prepared PRD-001 body overlaid → WRITE_INTENT, then WRITE_LABEL; nothing was sent.

Writing the PRD-001 body into #338 was refused by the auto-mode classifier (external write). It is the first
human-approved LIVE step.
