# Batch 4 (2026-10-07, STATIC): closing the cloud-doable remainder of batch 3

STATIC only. No LIVE Claude/provider/model turn, no Jules dispatch, no Jules
status GET, no Routine, no merge, no budget/owner/permission change.

## Fresh readback at start

Branch head `68e8fc52aaff1ef06c2af917ae4c08ed7b9fb896` (= remote), main
`4007f0c`, data branch `5227589`, carrier `e658f82`. Nothing moved since batch 3.

## Remainder taken from batch 3 §7 and what was done

| Batch 3 remainder | Batch 4 result |
| --- | --- |
| TEST_ENVIRONMENT cause not wired into the controller | Wired (opt-in v1). On same-head reinspection of `evidence missing: ['tests']`, a `RECOVERY_DECISION` is written first; one re-run is allowed, later re-runs only after `environment_digest()` changes (test command, Python version, platform); otherwise the task is isolated as "no progress". |
| PROVIDER_FAILURE cause not wired | Wired (opt-in v1). Timeout + verified settlement ending `: FAILED` + no result → one new distinct attempt through a durable `TASK_REPLAN` (fresh snapshot, new command, slot of the failed attempt stays consumed); a second FAILED isolates the task. `COMPLETED` without a result is isolated at once, as before. |
| Settlement producer that does not rely on transcription | `observation_from_readback_run` builds the record from GitHub itself (request commit → single run → single job → job log line) and verifies it. CLI `build-settlement` prints it and writes nothing. `record-settlement` now refuses (exit 2, no write) any record the job log does not confirm. |
| Read-only CLI for recovery history | `recovery-history` prints RECOVERY_DECISION / RECOVERY_ATTEMPT / TASK_BLOCKED / TASK_REPLAN events; `--recovery-policy v1` opts the CLI controller into reasoned recovery. Test proves it writes nothing. |

Not done, on purpose: running the producer inside a GitHub Actions job (so job
logs are readable without the user's PC). That needs a new workflow with
`actions: read`, i.e. a workflow/permission change on the carrier route; it is
left for an explicit decision.

## Tests added (11)

* `test_claude_jules_recovery_policy.py`: `WiredCauseTests` (unchanged
  environment → isolate; changed environment → PASS and adoption; provider
  FAILED → one new distinct command then isolate; COMPLETED without result →
  immediate isolation with no decision), `RecoveryHistoryCliTests` (read-only
  history, stable environment digest).
* `test_claude_jules_settlement.py`: `ProducerTests` (record built from the log;
  spoof / missing log / conflicting lines / re-added request refused),
  `CliTests` (contradicted record not written; verified record written once;
  build-settlement writes nothing and reports UNKNOWN when the log is
  unreadable).

## Validation

| Check | Result |
| --- | --- |
| Local full regression on code head `ef68069eb7a89df6e20514240a54ea7508ee94a3` (tree `a7e50ace8d7f5ee18119f728e7851f559b461479`) | `Ran 1911 tests`, `OK (skipped=1)` |
| compileall / `git diff --check` | OK / OK |
| Exact-head Actions on `ef68069…` (carrier request commit `a21a326d9515d759c3ae2e10cd44179c5538802a`) | [run 37610080307](https://github.com/kamiyusense/multi-ai-council-phase0/actions/runs/37610080307) / job 112754949185: success; job log `Ran 1911 tests`, `OK (skipped=1)`, summary `target_sha: ef68069eb7a89df6e20514240a54ea7508ee94a3`; compileall and diff check steps success |
| Remote readback after CI | branch = `ef68069…`; main `4007f0c`; data branch `5227589`; live target `53f2caf`; budget ledger 6 slots (6/10); owner chain a-003 = 2 events (generation 2 SEMI_AUTO); all unchanged |

## Remaining after batch 4

Implementation gaps (need a decision, not only code): the Actions-side
settlement producer workflow (permission change on the carrier route).

LIVE-unproven (need approval): one-GET settlement readback of Loop 139
(prepared in batch 3 §5.2); production Routine; GitHub-level race behaviour;
staged long LIVE campaign (needs a new budget; 4 Loop A slots left).
