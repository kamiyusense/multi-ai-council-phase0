# First two-task LIVE proof: PRD-C2 (prepared, NOT started)

Nothing below has been executed. #338 is unchanged and unlabeled. No Jules task was started, and slot 10 is
unused. `campaign-prd-c1.json` and `live-plan-prd-001.md` are kept unchanged as history. Their batch-16 policy is
rejected by the batch-17 Starter (`POLICY_INVALID`), which is intended.

## Why two tasks

One task proves Jules → PR → review → PASS. A second task proves the part a human did until now:
**PASS → next task created and started automatically → next PR → next review**, with the first PR still unmerged.

## Campaign `prd-c2` (`campaign-prd-c2.json`, built by `build_campaign_prd_c2.py`)

| | Task A | Task B |
|---|---|---|
| task | `prd-001` (the same content as PRD-C1) | `prd-002` |
| task_sha256 | `14d494c50442f9c33e15fc0593e23a025b34a70ad76d4d5778d29844848600e2` | `0d62075b586a68346136c34cdca562e7721c3228b9bfc4fdf173c7e1062c163f` |
| correlation | `prd-001-702497c` | `prd-002-702497c` |
| generation | 1 | 1 |
| bug (real, Windows only) | the carrier blob-SHA test hashes CRLF bytes | `test_sf8_authority_issuer_candidate` reads files as cp932 |
| verified | CRLF-normalized hashes equal the pins (`True 2`) | fails with cp932; passes with `PYTHONUTF8=1` |
| allowed path | `automation/command_bus/tests/test_claude_jules_dispatch_contract.py` | `automation/command_bus/tests/test_sf8_authority_issuer_candidate.py` |
| operations | `bug_fix`, `test_add` | `bug_fix`, `test_add` |
| issue | #338 (named by GRD-001's PASS receipt) | created by the reviewer on A's PASS (`next_task.body_ref` → `render-next`) |
| predecessor | `grd-001` / #335 / PR #337 head `2ce8caa` | `prd-001` |
| depends on A's Merge | — | **no** (different file) |

Both tasks have base `main` at `702497c6b464a3b1ab09441b21fc6f96bd3bb2d0` and base policy
`descendant_untouched`. Acceptance criteria and test commands are in the manifest. Each task: a root-cause fix,
a regression test, no weakened test, no other file.

## Evidence that it is ready

* `live-readonly-dryrun-338-c2.json`: a read of live GitHub with A's body overlaid on #338 gives:
  * `WRITE_INTENT` with all 10 check groups;
  * then `WRITE_LABEL` for the same run;
  * `DEFER LEASE_HELD` for any other run.
* `live-readonly-tick-prd-c2.json`: a read-only loop tick on live GitHub gives `DEFER`: "manifest tasks
  not created or not finished yet". The loop does not call it complete, and nothing was written.
* `PrdC2RehearsalTests` runs the real manifest in the mock: A starts, A gets a PASS, B is created and started
  automatically while A is unmerged, and B gets a corrective round and then a PASS. The outcome is `MERGE_WAIT`.
  Exactly 2 Jules starts, and no issue was labeled twice.

## Activation (each step needs a human go; nothing here is automatic yet)

1. **Merge #340** (human). The Routine runs code from `main`: the loop, the starter and `render-next`.
2. **Confirm usage credits are off** (human, Billing). Then the Routine cannot continue on metered overage.
3. **Apply Routine v1.6** and add the `pull_request.closed` (merged) trigger. Optionally add the hourly recovery
   schedule. These are human-approved Routine changes; see `routine-prompt-v1.6-draft.md`.
4. **Prepare #338**: set its title and body to manifest entry 1, then read it back. Its task block must hash to A's
   `task_sha256`. No label.
5. **First start** (the single LIVE operation; human-approved "Run now", or this session with approval): one loop
   tick, which writes the intent, adds the `jules` label to #338 once, and writes the start receipt.

After that, nothing needs a human until `MERGE_WAIT`:

* Jules opens a PR, and the Routine reviews it.
* On PASS the Routine creates B's issue, the loop tick starts B, Jules opens a PR, and the Routine reviews it.

## Recovery plan

The rules are proven in the mock tests: `LoopRecoveryTests`, `RecoveryTests`, and the 40/100/300-round endurance
runs.

| Situation | What happens |
|---|---|
| The run dies after a receipt, before B starts | the recovery schedule (if approved) or a human "Run now" ticks; B starts once |
| A PR event is dropped (hourly cap) | the recovery wake reviews the unreviewed head, then ticks |
| A label write is lost or invisible | readback; an attempt only after the lease and a label-never-present check; after 5 attempts: backoff + escalation, never a second label |
| B's issue creation outcome is unknown | the next tick finds it by correlation or fingerprint; never created twice |
| A paid or API route is observed | `HARD_STOP_PROVIDER`: no new starts |

## LIVE stop conditions

* A second `labeled jules` event on any issue, or a second Jules task for one issue.
* Any `HARD_STOP` (paid or API route, invalid policy or manifest).
* Any usage-limit or billing message from Jules or the Routine.
* The reviewer posts more than one corrective for one head, or writes anything other than its allowed writes.
* Any request touching Merge, the default branch, keys, Billing, Credits, Overages or settings.
