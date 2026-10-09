# G5 — Official Symphony production observation bridge

Status: **STATIC integration present; first Local G5 LIVE FAIL / STARTED_UNRESOLVED**.
See [Issue #341 Local result](SYMPHONY_G5_LOCAL_LIVE_RESULT_ISSUE_341.md). Official Symphony pin:
`be10a1b79df723d6d7612b5651c8522704dafb2e`.

## Boundary

The small `automation/command_bus/symphony_g5_observer.patch` applies to the
pinned upstream `elixir/lib/symphony_elixir/agent_runner.ex`. It adds two
best-effort emissions at the existing worker lifetime boundary: `STARTED`
after workspace creation, and `TERMINAL` after the worker returns normally or
with an error result. It changes no polling, dispatch selection, workspace,
Codex turn, same-thread continuation, retry, backoff, stall, or concurrency
logic. A process exception before the terminal hook can leave STARTED
unresolved; the ledger must not invent a terminal event.

`symphony_g5_observer_cli.py` is a separate, opt-in, local file observer. It
verifies each JSONL record with an HMAC shared by the local upstream hook and
sidecar, binds the Issue to a configured campaign/task/expected HEAD, then uses
`GitHubAutonomousAttemptStore` to append an INTENT and STARTED or TERMINAL to
a **separate non-default ledger branch**. The INTENT explicitly does not grant
dispatch. The observer cannot start/stop a worker or adopt Git changes. Its
only side effect is create-only ledger evidence with post-write readback; an
ambiguous write is not blindly resent. Complete lines are replayable after a
reader restart. A partial final line waits for completion. Conflict remains
local to that attempt and does not control Symphony's scheduler.

The producer generates a random 128-bit worker run ID. The ledger's positive
`attempt_number` is deterministically derived from its first 60 bits; it is an
opaque identity, **not a chronological retry counter**. This avoids collisions
when upstream's retry counter returns to 1 for normal active-Issue
continuation. The full run ID and hashed workspace path bind STARTED to
TERMINAL. Thread/turn IDs are optional and are not claimed by this hook.

`TERMINAL` means that **one worker lifetime ended**. It does not prove the
tracker Issue or development task is complete. The ledger records
`UNKNOWN / RECOVERABLE_UNKNOWN`, `model_started=null`, and a digest of the
signed observation. This is intentionally not passed into the autonomous
campaign result reconciler in G5. G6 must read actual result evidence, fresh
canonical HEAD, current task validity and mutation class before any adoption.

`WORKER_UPDATE`, `RETRY_SCHEDULED`, `STALLED`, and `STATUS_AVAILABLE` remain
read-only hints. The G5 producer need not emit them to prove STARTED/TERMINAL;
the Python receiver handles them without a ledger write. Official Symphony
retains all internal retry and same-session authority.

## STATIC validation

- Pinned upstream patch: `git apply --check` PASS against the unmodified pin.
- Signed fixture tests cover STARTED, reader death/restore, terminal before a
  campaign checkpoint, duplicate STARTED and TERMINAL, conflicting terminal,
  wrong worker/workspace, invalid MAC, unbound Issue, read-only hints, complete
  line replay with a partial tail, and stale HEAD decision at the separate
  result adoption boundary.
- Existing attempt fault tests retain controller crash/restart, no duplicate
  model start, independent task continuation, and stale replan behavior.
- None of these fixtures launch a provider/model or prove the hook on a real
  Symphony process.

## Next single G5 LIVE candidate — prepare only

Purpose: observe one naturally finishing, small Official Symphony worker on a
new isolated proof Issue/branch/workspace. Use the prepared Issue in
`docs/SYMPHONY_G5_LIVE_PROOF_ISSUE.md`. Prefer a task that needs more than
one turn, but do not force artificial retry or stall. Do not reuse G4's
consumed work item as a new LIVE authorization.

Start conditions: separate explicit LIVE approval; fresh PR #320/main/Issue
readback; isolated non-default proof branch and empty workspace; pinned
upstream checkout clean before `git apply --check`/apply; ChatGPT/Codex login
confirmed; no API-key/custom-endpoint/paid fallback; separate non-default
ledger branch; observer config bound to exactly one Issue and expected proof
HEAD; 32-byte random MAC key generated locally and never logged; JSONL path
outside the model workspace with restrictive file permissions. The Codex child
command must remove `SYMPHONY_G5_OBSERVER_KEY_HEX`, `GITHUB_TOKEN`,
`OPENAI_API_KEY`, `CODEX_API_KEY`, `AZURE_OPENAI_API_KEY`, `OPENAI_BASE_URL`,
and `OPENAI_API_BASE` from its environment. The producer and observer share
the key only in their parent processes. Check child selector **names**, never
print secret values. Quota numbers unreadable alone do not imply exhaustion.

The observer configuration format is:

```json
{
  "repository": "kamiyusense/multi-ai-council-phase0",
  "ledger_branch": "codex/symphony-g5-proof-ledger",
  "campaign_id": "symphony-g5-proof-issue-NUMBER",
  "issues": {
    "NUMBER": {
      "task_id": "issue-NUMBER",
      "generation": 1,
      "expected_target_head": "40-character-proof-branch-head",
      "runner_generation": 1,
      "scope": {"issue": "NUMBER", "allowed_paths": ["one-approved-path"]}
    }
  }
}
```

Only after LIVE approval, run the sidecar as
`python -m automation.command_bus.symphony_g5_observer_cli --config <local-config> --events <local-jsonl> --follow`,
then start the patched pinned Symphony with its normal CLI and the G5 proof
workflow at `docs/SYMPHONY_G5_LIVE_PROOF_WORKFLOW.md`. The sidecar has no
provider dispatch capability. After TERMINAL is observed and read back, stop
both processes with Ctrl+C; read back the exact ledger paths, proof
workspace diff, Issue state, PR/main refs and child environment selector names.
If a write response is ambiguous, read back the exact ledger path before any
new action. Do not recreate the Issue, retry a push blindly, or auto-adopt the
artifact.

The proof Issue stays open while Codex works. For a **normal worker terminal**,
the Local operator may close that Issue after the allowed artifact is observed
and checked, under the separate LIVE approval. Official Symphony may see the
tracker terminal state at its next continuation check and let its worker
return, allowing TERMINAL. This is not guaranteed: its independent periodic
reconciliation can terminate an active task and remove its workspace before
that worker return hook runs. Local Issue #341 demonstrated this path.
Preserve the verified artifact/readback before closing; a closed Issue, stopped
child, or deleted workspace must never be substituted for a signed TERMINAL. If the worker instead crashes
or is stopped with Ctrl+C first, preserve STARTED_UNRESOLVED and report that
TERMINAL was not captured. Do not manufacture a terminal from a stopped
process or treat the G5 proof as PASS.

Success evidence: real worker and signed STARTED captured durably; real
terminal observation captured; reader restart replay produces only duplicate
NO-OP; same-session continuation remains upstream-owned; no API-key/paid
route, no Git auto-adoption, no main mutation. Save event-file SHA-256,
observer statuses, exact ledger paths and record digests, process/log evidence,
child selector-name inspection, starting/ending refs and workspace diff.
Unseen retry/backoff/stall remains `NOT_OBSERVED`, not PASS. Stop on paid-route
or destructive Git risk, wrong Issue/branch, broken event binding, unexpected
workspace mutation, or loss of trustworthy canonical lineage. An isolated
attempt observation conflict is recorded and does not itself stop independent
Symphony work.

## Remaining production boundary

The MAC proves possession of the local observer key; it is not a remote
attestation of the Codex process and does not protect against an adversarial
same-user process that can read the parent environment. Local LIVE must still
verify process/workspace isolation. No real G5 producer, ledger write, reader
restart, subscription route, or terminal capture has run in this Cloud batch.
G6 automatic Git result adoption remains disconnected.

## 2026-10-09 Local G5 — real unresolved start, not a completed proof

One explicitly authorized Official Symphony launch selected new Issue #341.
The signed STARTED was authenticated and persisted as create-only INTENT and
STARTED on the separate ledger branch. One real ChatGPT-authenticated Codex
session started three turns, completed two and naturally continued twice.
Only the approved artifact changed; its verified content was preserved before
the operator closed the Issue under the authorization.

At `2026-10-09T02:53:18.569607Z`, upstream periodic reconciliation reported
`Issue moved to terminal state ... stopping active agent`. It interrupted turn
3 and invoked normal upstream workspace removal. The `run_on_worker_host`
return hook did not execute: one real STARTED exists and no real TERMINAL.
The local observation must remain STARTED_UNRESOLVED. Do not synthesize a
terminal or call this G5 PASS. This is a lifecycle observation gap, not proof
that the MAC or create-only store rejected a real terminal event.

After Symphony/App Server/observer stopped and port 4000 closed, the observer
alone restarted once. Replaying that actual STARTED returned NOOP_DUPLICATE;
ledger HEAD and event digest were unchanged and new worker/model dispatches
were zero. TERMINAL duplicate replay could not be tested. This is partial
restart evidence, not the full durable restart proof.

No scheduler/continuation/retry/backoff/stall code was changed. No second G5
LIVE, G4/provider LIVE, automatic Git adoption, main mutation or G6 LIVE was
performed. A future observation-only correction must address the real
upstream termination boundary without changing lifecycle authority, and needs
separate LIVE authorization. Static fixtures do not complete this failed run.
