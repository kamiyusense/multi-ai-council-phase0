# Batch 26: PR #340 merged, post-merge readback, Cross-Wake Durable LIVE Budget Guard (STATIC)

Date: 2026-10-10 JST. Executor: Claude. Independent reviewer: ChatGPT (not this session).
No Jules start, no `jules` label, no Routine / trigger / schedule change, no LIVE authorization file, no API key,
no billing / usage-credit / permission change, no second Merge.

## 1. PR #340 Merge (human-approved)

| Check before Merge | Observed |
|---|---|
| PR #340 head | `7bd799f9adf0ff567d769fb46d214e503c614df5` (= the reviewed head; batch 25 commits fast-forwarded locally and re-read) |
| CI on that head | run `38022808120` offline-validation **success** |
| mergeable_state | `clean`; base `main` = `702497c6b464a3b1ab09441b21fc6f96bd3bb2d0` |
| files | 64, all under `automation/command_bus/` or `docs/evidence/claude-jules-production-starter-20261009/`; no `.github/` change |
| main protection | `protected: false` (nothing to bypass; no `--admin`) |
| repo merge convention | merge commits (`Merge pull request #339 ...`); `delete_branch_on_merge: false` |

Actions: Draft -> Ready (normal API), then `merge` with `expectedHeadSha=7bd799f…`. Result `merged: true`.

| Post-merge readback | Value |
|---|---|
| merge commit = main HEAD | `4bb5cd72ee0d9912376b0bb3b989cbb028806392`, parents `702497c…`, `7bd799f…` |
| main tree | `d323ecaf81ade5af16e66d08742511181e7cde79` == PR head tree (byte-identical content) |
| files changed 702497c..main | 64 (same list) |
| branch `claude/production-starter-20261009` | still exists at `7bd799f…` (not deleted) |
| Issue #338 | OPEN, labels `[]` |
| workflow side effects | `loop-status-development` (`pull_request_target` closed) job `refresh-development` is gated to PR #4/#25 only; no Jules / model workflow is triggered by this merge |
| Routine wake on merge | `pull_request.closed` trigger was never added (checklist step 5); Routine run history is not readable from GitHub: UNKNOWN, but v1.5.1 writes nothing on a non-task PR |

## 2. The defect this batch fixes

`GhLiveWritePort` counted `labels_sent` / `sent` per instance, i.e. per Routine wake. `max_labels` was therefore not
a global limit: N wakes could send N x `max_labels`. Reproduced on old main `4bb5cd7`
(`old-main-per-wake-cap-hazard-reproduction.txt`): two wakes with `max_labels: 1` labeled #337 and #338 while the
ledger had one slot left.

## 3. Design (`automation/command_bus/claude_jules_durable_budget.py`)

* **Durable ledger = the existing create-only slot ledger** (`CLAUDE_AUTO_LIVE_BUDGET_SLOT_V1`, one file per slot on
  `claude/claude-jules-autoloop-data`, slots 01-09 used). The 9 real records are the test fixture (digests verified).
* **Cap from a human-merged declaration** (`CLAUDE_JULES_LIVE_BUDGET_DECLARATION_V1`), not a constant. Raising it needs
  a Merge. A slot written under a larger cap than the declared one makes the ledger UNKNOWN (lowering never frees).
* **Activation identity** bound into the slot: repository, campaign, issue, task, correlation, generation, task SHA-256,
  expected target head, route (`command_id` + `intent_sha256`). Same activation after restart = `RECOVERED` (no second
  slot); any other binding = `COLLISION`; a new generation needs a new slot.
* **Per-authorization maximum is durable too**: every slot carries `origin_loop_id = auth:<campaign>:<sha256(approval_ref)[:16]>`.
* **Readback decides**, never the write response. A lost response, lost readback, failed create or a race all end
  `ACQUIRED` only when the slot file reads back as our exact record; otherwise `UNKNOWN`, not re-sent.
* **Slot creation is DISABLED** (`SLOT_CREATE_ENABLED = False`). The race safety of creating a slot relies on git's
  non-force push being rejected when the remote ref moved (the git protocol carries the old value). That contract is
  documented for git but was NOT exercised against GitHub here, so the adapter never creates a slot. A start is still
  possible when an approved, pre-written slot record bound to exactly that activation exists (`prepared_slot_record`):
  that is the slot-10 pilot path.

`GhLiveWritePort.add_label` (the only Jules start) now requires, in order: valid unexpired authorization; label
`jules`; issue in scope (an unreadable issue refuses); no earlier unknown label outcome in this wake; per-wake cap
(secondary); a **V2** authorization (V1 = per-wake counters only -> refused); a durable budget whose `budget_id`
matches; a FRESH issue read with complete label history, never labeled `jules` before, no review receipt and no
start receipt for the correlation, readable base head, valid task block in this campaign, OPEN; then
`DurableBudget.reserve` = `ACQUIRED` or `RECOVERED`. After the label it re-reads the slot (`holds`). A lost label
response marks the wake ambiguous: no further label in that wake; the next wake reads back.

Loop: a label refused with `budget EXHAUSTED` becomes `ISOLATE BUDGET_EXHAUSTED` (human_required), re-checked every
wake, so the loop settles visibly instead of retrying silently. Other tasks are unaffected.

## 4. Tests (local, Python 3.11)

New `test_claude_jules_durable_budget.py` (33): 9/10 ledger; slot 10 once; 10/10 exhausted; slot 11 impossible;
restart RECOVERED (A, G, J); identity / generation / head / authorization collision; per-authorization maximum;
two controllers racing for the last slot (D, H); lost create response (C, I); lost readback; failed create;
unreadable / malformed / digest-edited / gap / stray-file ledger; larger-cap slot; creation disabled by default;
declaration validation; V1 authorization cannot label; no ledger no label; **cross-wake global budget** (wake 2 with
fresh counters is EXHAUSTED); 10/10 sends nothing; pilot via pre-written slot with creation disabled; label landed
but response lost (B, C, I); label not landed not re-sent; duplicate wakes (E); expired authorization (F);
historical label / terminal receipt / wrong issue; incomplete history; wrong budget / campaign; route UNKNOWN;
only allowed writes; templates invalid; CLI wiring keeps creation disabled; PRD-C2 loop with a new port per wake:
cap 10 -> A only and `BUDGET_EXHAUSTED`, cap 11 -> A and B, each labeled once.

Changed: `test_claude_jules_starter_live.py` now builds V2 authorizations and gives each port the shared mock ledger
(no assertion removed or weakened). Probe: the same first-page `rel="last"` fail-open batch 25 found in `gh_get` was
also in `readonly_label_history_probe.py`; fixed with a regression test that fails on the old script.

## 5. Not guaranteed (UNKNOWN), by design not claimed

* exactly-once Jules start: whether the Jules app starts twice when two controllers add the same label to one issue
  at the same moment is UNKNOWN. The budget still counts one slot (same activation); the starter's intent lease is the
  per-issue election.
* GitHub behaviour of the create-only slot push under real concurrency (hence creation disabled).
* starts made outside this adapter (a human labeling by hand) are only counted if recorded in the ledger.
* the Routine's saved configuration and run history (not readable from GitHub).

## 6. Human decisions still needed

Merge of this branch's PR; v1.6 apply; triggers / recovery schedule; the budget declaration file; the V2
authorization file; the pre-written slot-10 record; slot 10 start; any cap increase; enabling slot creation.
