# First Production Starter LIVE proof: PRD-001 (prepared, NOT started)

Nothing below has been executed. No label is on issue #338. Jules was not started. Slot 10 is not used.

## The task

| Item | Value |
|---|---|
| campaign | `prd-c1` (one task), manifest `campaign-prd-c1.json`, built by `build_campaign_prd_c1.py` |
| task | `prd-001`, kind `code_change`, generation 1, max corrective rounds 2, `live_slot` 0 (production, not a proof slot) |
| correlation | `prd-001-702497c` |
| task_sha256 | `f36a5d2b832583ae054c5983b5ad02405a52ec9f9f975b02021e7c6f728239d8` |
| expected base | `main` at `702497c6b464a3b1ab09441b21fc6f96bd3bb2d0`; base policy `descendant_untouched` |
| allowed path | `automation/command_bus/tests/test_claude_jules_dispatch_contract.py` (MODIFY) |
| issue | #338 (the issue named by GRD-001's PASS receipt `next_issue`) |
| expected predecessor | `grd-001`, correlation `grd-001-8fbbef9`, issue #335, PASS receipt for PR #337 head `2ce8caabb63df36c8fb7be1057344dceb7f732ab` |
| route | `jules-github-app-issue-label`, account OAuth, subscription (user decision D6) |

**Bug fixed (real, Windows only).** `test_vendored_carrier_validators_match_pinned_blob_shas` hashes raw bytes. A
Windows checkout with `core.autocrlf=true` has CRLF, so the test fails on Windows only. Verified: the
CRLF-normalized hash of both vendored files equals the pinned SHAs (`True 2` on Windows `w-702`).

**Acceptance criteria.**

1. The blob SHA is computed from CRLF-normalized content, so it matches git on Windows.
2. The pinned SHAs and the vendored files are unchanged, and a real content change still fails the test.
3. There is a regression test for CRLF vs LF, for equality with git's blob SHA, and for different content giving
   a different SHA.
4. No other file changes, and no test is weakened.

Tests: the dispatch-contract module and the full discover.

## Read-only dry run against live GitHub (`live-readonly-dryrun-338.json`)

* **#338 as it is now:** title "GRD-002 prepared next task", no task block → `IGNORE`. The Starter would not
  start it.
* **With the prepared PRD-001 title and body overlaid on the real snapshot:**
  * `WRITE_INTENT`: all 9 check groups pass, against the real #335 receipt and main `702497c`;
  * then `WRITE_LABEL` for the controller that wrote the intent;
  * `DEFER` for any other controller.
* Nothing was sent.

## LIVE activation: the operations, in order (each needs the human go)

1. **Prepare #338.** Set its title and body to the manifest's entry 1 (`gh issue edit 338 --title … --body-file
   …`), then read it back. The issue's task block must hash to the `task_sha256` above. No label. This write was
   refused by the auto-mode classifier in this batch, so it is listed here as a human-approved step.
2. **Starter step 1.** Read the snapshot with `claude_jules_starter_gh`, then `next_step` gives `WRITE_INTENT`.
   Post exactly that comment, then read back.
3. **Starter step 2.** With the same controller and its session nonce, `next_step` gives `WRITE_LABEL`. Add the
   label `jules` to #338 **once**. This is the single operation that starts Jules. Then read back: the label is
   present and there is exactly one `labeled` event.
4. **Starter step 3.** `next_step` gives `WRITE_START_RECEIPT`. Post it, then read back. A next `next_step` gives
   `NO_OP`.
5. From here the proven path runs: Jules opens a PR with `Fixes #338`, and Routine v1.5.1 reviews it (PASS, or an
   `@jules` corrective). The task has no `next_task`, so a PASS creates no further issue and the campaign ends.

Expected start receipt (`CLAUDE_JULES_STARTER_RECEIPT_V1`): campaign `prd-c1`, seq 1, `prd-001`, correlation
`prd-001-702497c`, generation 1, issue 338, the `task_sha256` above, attempt 1, `intent_comment` = the intent's
comment id, label `jules`, outcome `STARTED`.

## Recovery plan (the same rules the STATIC tests prove)

| Situation | What happens |
|---|---|
| Intent write times out or its response is lost | Read back. If the intent is there, wait for the lease (15 min), then take over as attempt 2. If it is not there, write the intent once more. |
| Label write: response lost | Read back. Label present → write the start receipt. Never a second label write. |
| Label write: timeout, label not visible | No retry in this run. After the lease, take over as attempt 2 (max 2 attempts, then BLOCKED for a human). |
| Crash after the label, before the receipt | The next run sees label + intent → writes the receipt. |
| Label removed later | BLOCKED. The label is never re-added. |

## LIVE stop conditions (stop at once, write nothing more)

* Any `HARD_STOP`: an API/metered route is observed, the policy is invalid, or the manifest is invalid.
* More than one `labeled jules` event on #338, or a second Jules task for #338.
* Jules does not acknowledge the label within 30 min (`jules_ack_timeout_minutes`): report it, do not re-label.
* The reviewer posts more than one corrective for one head, or anything other than a receipt or a corrective.
* Any Jules usage-limit or billing message: new starts stop (quota CONFIRMED_EXHAUSTED).
* Any request touching Billing / Credits / Overages, an API key, settings, Merge or the default branch.
