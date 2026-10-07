# Batch 2: provider-settlement source and wake transport (STATIC, 2026-10-07)

Base: `16e84432df1e6d8b5ea342f150a083768e330199` (Draft #329). No LIVE provider/model execution, no Jules
session, no Routine, no owner change, no budget use (Loop A stays 6/10), no merge.

## Provider-settlement source (`automation/command_bus/claude_jules_settlement.py`)

| Piece | Rule |
|---|---|
| Source | The existing carrier workflow `jules-session-readback.yml`: one append-only status request -> one Jules session GET -> log line `Jules session readback: name=sessions/<id> state=<STATE> pr_url=...`. Adding a request is a provider read and is NOT done by this code. |
| Record | `CLAUDE_AUTO_PROVIDER_SETTLEMENT_OBSERVATION_V1`, create-only at `evidence/claude-auto-settlement-observations/<command>/<run>.json`, digest-sealed, bound to command, session, status-request path + commit, run, job and the exact log line. CLI: `record-settlement --file`. |
| Verification | the request path was added exactly once by that commit and names the same session; exactly one push run of the readback workflow for that commit, completed/success, with that job. |
| Mapping | `COMPLETED`/`FAILED` -> SETTLED; `QUEUED`/`PLANNING`/`IN_PROGRESS`/`AWAITING_*`/`PAUSED` -> RUNNING; anything else -> UNKNOWN. |
| Decision | only records of the accepted session, observed after the dispatch, on verified runs; the latest decides; unsettled after settled -> UNKNOWN; any invalid record, other session or verification failure -> UNKNOWN. No record -> UNKNOWN (unchanged production behaviour). |
| Wiring | `LiveResultFacts.timeout_reconciliation` now reports this status next to the PR readback. The controller already isolates a task only on SETTLED and never starts another provider on RUNNING/UNKNOWN. |

Tests: `test_claude_jules_settlement.py` (16).

## Wake transport and faults (`test_claude_jules_wake_transport.py`, 10)

Real `poll_results` / `wake_resume` against the e2e fakes:

- webhook then poll of the same head -> one durable result, no extra write;
- poll-only wake (webhook lost) restores and finishes; a repeated wake is a NO-OP;
- inverted delivery order (newer head first, older `opened` late) -> only the newer head is adopted;
- two controllers interleaved -> one adoption, one next dispatch, no duplicate command;
- repeated wakes while waiting write nothing;
- poll failing mid-way -> `poll_error` UNKNOWN, nothing resent; the next wake heals once;
- response lost after an inbox write -> resolved by readback (RECORDED), not resent;
- inbox write that never landed -> UNKNOWN, a later wake records it exactly once;
- closed PRs and PRs on foreign work branches are ignored;
- a conflicting record for the same result id is BLOCKED.

## Validation (cloud container, Python 3.11)

- full suite: 1853 tests, OK, 1 skipped (1827 before + 26 new)
- compileall and `git diff --check`: pass

## Still not done

- No production status-request producer: a provider GET needs its own approval and authority.
- Routine-level concurrency/idempotency and a long multi-round LIVE proof remain unproven; v1 concurrency is one.
