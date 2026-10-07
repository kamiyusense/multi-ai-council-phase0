# Symphony adoption bridge — STATIC checkpoint

Date: 2026-10-07. Workbench: Draft PR #320 on
`codex/symphony-inspired-minimal-controller`.
Starting remote HEAD: `483178a418e2832bba054fec8edeecba208f2330`.

This batch keeps Official Symphony responsible for polling, workspaces,
multi-turn sessions, continuation, retry/backoff, and stall detection. The new
issue-level hint receiver only requests read-only durable reconciliation. It
does not require a full worker/thread/turn identity for that harmless wake and
never authorizes dispatch or fencing. Attempt-bound evidence remains necessary
when a terminal result is adopted or an unstarted attempt is retired.

## Result adoption

The STATIC controller now rereads canonical HEAD after a fixture worker result
and before durable TERMINAL/checkpoint. The same decision runs when a terminal
is recovered after controller death. The decision checks:

- trusted current canonical HEAD against the attempt's expected target HEAD;
- current task validity (caller supplied); and
- declared mutation operations, currently only `ADD`/`MODIFY` as safe classes.

An intervening HEAD yields `STALE` without counting a completed round and the
task is replanned. An invalid task or destructive/unknown mutation class is
isolated while independent tasks continue. The original reported mutation
class is stored in terminal evidence, so a crash after TERMINAL cannot erase
the risk before campaign reconciliation. An actual Git ref adoption still needs
an atomic expected-HEAD check at the write; this STATIC work does not implement
or perform a Git ref write.

## Subscription route

The new-worker route classifier consumes the existing sanitized Codex account
summary shape from `src/relay/codex_account_readonly.py`. It rejects API-key or
custom API endpoint environment keys, non-ChatGPT account routes and configured
metered/paid-provider/credit fallback. `ordinary_usage_allowed=False` defers
new worker starts. An unreadable allowance value alone does not. This is a
STATIC compatibility decision, never LIVE dispatch authorization. The worker
launcher still needs to enforce the environment and account route in a real
runtime; no real account request was made in this batch.

## Verification and boundary

- Focused Symphony tests: 133 PASS.
- Full command-bus regression: PASS (one inherited platform skip).
- Command-bus compile: PASS.
- New cases cover mid-result HEAD advance and restart/replan, destructive
  mutation isolation with an independent task continuing, recovered terminal
  validity/risk checks, and subscription route classification.
- No model/provider LIVE, merge, default-branch write, billing, Secret or
  permission operation occurred.

The local read-only sandbox initially prevented temporary test files. The same
tests passed when run with normal test-file write permission; that infrastructure
failure was not a code failure.

Remaining STATIC work: connect an actual upstream transport envelope to durable
STARTED/TERMINAL evidence and run fake protocol/restart fixtures. A later LIVE
proof needs separately authorized real Symphony/Codex execution, verified
subscription-only launcher behavior, and expected-HEAD Git adoption. The strict
one-turn proof and consumed command remain unchanged.
