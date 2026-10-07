# Batch 5 (2026-10-08 JST): #329 merged, one-GET readback measured on the real workflow

STATIC except the #329 merge, which the user explicitly approved for #329 only.
No Jules status GET, no Jules dispatch, no LIVE provider/model turn, no Routine,
no budget, owner, permission, secret or carrier-workflow change.

## 1. Fresh readback before the merge (2026-10-07 16:01Z)

| Item | Read back |
| --- | --- |
| main | `4007f0c334c31ee73c68e3a9becd35b2ea5f9b6d` |
| #329 | head `47e2af3ba6c3fe55ff1d3438b4f7c8f20fefd5d9`, base main, Draft, `mergeable_state: clean`, 52 files, 0 reviews |
| #329 head checks | `offline-validation` success, `test` success, `refresh-development` skipped |
| code head vs. head | `git diff --name-only ef68069 47e2af3` = batch 4 note, `checkpoint-batch4.json`, evidence README only |
| code head exact-head | run 37610080307 / job 112754949185: `Ran 1911 tests`, `OK (skipped=1)` (batch 4) |
| carrier | `a21a326d9515d759c3ae2e10cd44179c5538802a` |
| data branch | `5227589bbeeb1db5619b6f3ffff3fed8634428cb` (unchanged) |

## 2. Merge of #329

* Draft cleared, state re-read (head still `47e2af3`, clean), then merged with
  `merge_method: merge` and `expectedHeadSha: 47e2af3…`. The source branch was
  kept.
* Result: merged, merge commit `8fbbef941732219e4ad43ce0d32e22922275d040`
  (parents `4007f0c`, `47e2af3`). `origin/main` read back = `8fbbef9`.
* main's tree after the merge is `cff593fb6aa5a7445785049eef7fd0a865e3a053`, which
  is the exact tree of the validated #329 head, so main contains exactly what
  was tested.
* Not touched: #326, #327, #328, #325, #324, #322, #220.

## 3. How many GETs the readback really makes

The readback runs from the workflow file on the carrier branch
(`feature/chat-work-command-bus`, push trigger on
`automation/command_bus/jules_api_status_requests/*.json`), not from main.

| Copy | Blob | `include_activities` handling |
| --- | --- | --- |
| main (`8fbbef9`) | `a4f0189922c7cd27c80ffa541f5d5a534e26562e` | parsed before any call; non-boolean refused; activities GET only when true |
| carrier (`a21a326`) | `3672250be2b4bcfe94ebb33547ed0ce479cd9f8e` | ignored; session GET and activities GET always |

Measured by running each copy's real `Read Jules session once` step with a
recording `curl` stub (`jules_readback_workflow_probe`):

| Request | main: session / activities GETs | carrier: session / activities GETs |
| --- | --- | --- |
| `include_activities: false` | **1 / 0** | 1 / 1 |
| omitted | 1 / 1 | 1 / 1 |
| `true` | 1 / 1 | 1 / 1 |
| `"false"`, `"true"`, `null`, `0`, `1`, `""`, `[]`, `{}` | 0 / 0, step fails (exit 5) | 1 / 1, step succeeds |
| session GET returns 500 (`false`) | 1 / 0, step fails, no retry | 1 / 0, step fails |

Verdict: main = `ONE_GET_CONFIRMED`; carrier = `NOT_ONE_GET`. A status request
pushed to the carrier today would cost two provider GETs whatever it says.
The batch 3 description of the prepared request as "exactly one GET" was true
only for main's copy.

## 4. Change on `claude/project-thread-9ygz7v` (Draft PR to main)

* `automation/command_bus/jules_readback_workflow_probe.py`: extracts the real
  step, runs it with a recording stub, proxies pointed at a closed port, a
  sentinel key, and refuses a step that uses another HTTP client.
  `one_get_preflight` returns `ONE_GET_CONFIRMED` / `NOT_ONE_GET` with the blob
  it judged. CLI `--ref <git ref>` or `--file <path>` reads only; exit 0 or 3.
* `claude_jules_settlement.prepare_status_request` now returns
  `requires_preflight: "ONE_GET_CONFIRMED"`; module docs record the carrier gap.
* Test fixture: byte-exact carrier workflow (blob `3672250`).
* 15 tests (`test_jules_readback_workflow_probe.py`). They cover: false = 1/0;
  omitted and true keep 1/1; eight non-boolean values refused with 0 calls;
  a failing GET is one call with no retry; the carrier fixture fails; removing
  the gate from main fails; the step prints exactly the line
  `readback_lines` accepts; a forged readback line inside a Jules agent
  message is not counted; session mismatch fails closed; the key sentinel never
  appears; the CLI exit codes are right.

The main workflow already had the right behaviour, so no workflow file changes.

## 5. What the carrier needs (not done: carrier production change)

One carrier commit replacing `.github/workflows/jules-session-readback.yml`
with main's blob `a4f0189…`. Facts checked for that step:

* `automation/command_bus/jules_session_acceptance.py`, which main's step calls,
  is already identical on the carrier (blob `c9f5f2c9…`).
* A workflow-only push to the carrier triggers no provider workflow: every
  carrier push workflow is path-filtered to its own request directory.
* Push-triggered runs use the workflow from the pushed commit, so the sync
  must land in an earlier commit than any status request.
* Main's step also writes and uploads a sanitized evidence artifact
  (`actions/upload-artifact`), which the carrier copy does not; permissions stay
  `contents: read`.
* Before any status request: run
  `python -m automation.command_bus.jules_readback_workflow_probe --ref origin/feature/chat-work-command-bus`
  and require `ONE_GET_CONFIRMED` for the carrier blob at that moment.

## 6. Loop 139 one-GET trial: prepared, not sent

* Re-read from GitHub: data branch dispatch receipt `DISPATCHED`, command
  `relay-dev-loop-139-live-proof-3-note`, J-GREEN, target
  `claude/autoloop-live-target` @ `53f2caf`, retry 0, fallback false. The dispatch
  observation names run 37417380878 / job 112118884171. That job's log, read in
  this session through the GitHub MCP job-log tool, prints `Jules session timing
  read back: sessions/12043323850985900453 at 2026-10-06T14:12:33+09:00`. The
  cloud session can read completed job logs this way.
* `prepare_status_request(attempt=1)` against the carrier's current status
  directory (no `settle-*` file exists) gives
  `automation/command_bus/jules_api_status_requests/settle-dfcd5c4061f53c45-a1.json`:

  ```json
  {
    "command_id": "relay-dev-loop-139-live-proof-3-note",
    "include_activities": false,
    "purpose": "settlement-readback-relay-dev-loop-139-live-proof-3-note-a1",
    "session_id": "12043323850985900453"
  }
  ```

  `provider_get_count: 1`, `requires_preflight: ONE_GET_CONFIRMED`, status
  `PREPARED_NOT_AUTHORIZED`. Not written anywhere on the carrier.
* The code's limit of three attempts is a ceiling, not a permission. The trial
  being prepared is one request, one GET.

## 7. Validation

| Check | Result |
| --- | --- |
| Focused: probe + readback workflow + settlement + timing + output tests | `Ran 73 tests`, OK |
| Local full regression on code head `77ad178b9e696e97f58039327bfa6f394e7592e2` (tree `f66ece2b8c43168870cd193f49681bbcc45c7603`) | `Ran 1926 tests`, `OK (skipped=1)` (1911 + 15 new) |
| compileall / `git diff --check` | OK / OK |
| Exact-head Actions on `77ad178…` (carrier request commit `d5baadc230ed33819390e910c0f65ccaa4aa193a`, request `autoloop-static-20261008-77ad178b9e69`) | [run 37649836308](https://github.com/kamiyusense/multi-ai-council-phase0/actions/runs/37649836308) / job 112889967306: success; job log `Ran 1926 tests`, `OK (skipped=1)`, summary `target_sha: 77ad178b9e696e97f58039327bfa6f394e7592e2`; compile and diff-check steps success |
| Draft PR #330 checks on `77ad178` | check suite completed green (16:13Z) |
| Remote readback after CI (16:15Z) | main `8fbbef9`; #329 branch `47e2af3` kept; carrier `d5baadc` (only the one validation request added); data branch `5227589`; live target `53f2caf`; budget slots 6 (6/10); owner a-003 events 2 (generation 2); carrier `settle-*` status requests 0 |
| #326 / #327 / #328 | heads `2d71c57` / `97b3e39` / `9f06a8f` are not in main; not merged, not closed; full containment still UNKNOWN |

## 7a. Stop and resume during this batch

The user asked to stop at 16:02:33Z to rewrite the instructions. That request
reached this session at 16:11Z. The #329 merge had finished at 16:01:42Z, before
the stop. Three writes happened after the stop was sent but before it arrived:
the push of `claude/project-thread-9ygz7v` (`77ad178`), Draft PR #330 and the one
carrier validation request `d5baadc`. Nothing was undone or resent. The
rewritten instructions (16:14Z) keep the same scope; work resumed from those
GitHub states.

## 8. Counters for this batch

Jules status GETs 0, new Jules sessions 0, provider/model execution 0, Routine
changes 0, budget consumption 0 (Loop A 6/10), owner changes 0 (a-003,
generation 2, SEMI_AUTO), permission/secret changes 0, carrier workflow
changes 0. Carrier writes: one append-only validation request.
