# G5 — Official Symphony production observation bridge

Status: **G5.1 worker-lifecycle STATIC fix present; Local G5 #341 remains FAIL / STARTED_UNRESOLVED**.
See [Issue #341 Local result](SYMPHONY_G5_LOCAL_LIVE_RESULT_ISSUE_341.md). Official Symphony pin:
`be10a1b79df723d6d7612b5651c8522704dafb2e`.

## Boundary

The `automation/command_bus/symphony_g5_observer.patch` applies to the clean
pin's `agent_runner.ex`, `orchestrator.ex`, and new `g5_observer.ex` only.
The Orchestrator generates the optional lifetime ID and passes just that ID to
AgentRunner. AgentRunner adds the ID to its existing workspace runtime message;
it performs no observation file I/O and no terminal emission. The Orchestrator
binds STARTED to the matching first runtime workspace, then observes TERMINAL
at `:DOWN`, `terminate_running_issue` after `stop_running_task`, or the existing
`stop_and_block_issue` stop boundary. `Process.demonitor(ref, [:flush])` remains
unchanged. Removing the running entry and the writer's one-shot terminal
handling prevent a later DOWN/duplicate end from emitting a second terminal.

Statuses distinguish `WORKER_COMPLETED` (natural normal process exit),
`WORKER_FAILED` (abnormal DOWN) and `WORKER_STOPPED` (explicit upstream stop,
including tracker terminal/stall/operator-input block). They describe a worker
lifetime only. A tracker-close stop must never be called WORKER_COMPLETED.
Concurrent natural return versus an already chosen explicit stop can
conservatively record STOPPED; there is one Orchestrator observation authority.
The receiver preserves exact same-event NOOP_DUPLICATE and rejects a conflicting
status, full worker ID or workspace without overwriting the canonical record.

One opt-in unlinked local writer per observed lifetime appends signed JSONL.
Orchestrator calls send messages without file I/O or acknowledgements; no
observer failure gates worker work, cleanup, continuation or retry. The writer
snapshots the parent-only MAC key and event path, preserves STARTED-before-TERMINAL
order from the same sender, emits at most one terminal and exits. An owner
monitor discards it when its Orchestrator disappears. Invalid/missing config
disables the observation only; missing/nonregular paths are rejected in the
writer. There are no producer write retries or new scheduler/store semantics.
Pre-create the private regular event file before starting Symphony. There is
no flush guarantee if the parent is killed before queued observations finish.
A stop before a matching workspace runtime message or owner death can still
leave no signed STARTED/TERMINAL; do not manufacture missing evidence. Drain
and read back the actual terminal before operator process cleanup.

Polling, issue selection, Codex turns, continuation, retry/backoff, stall,
concurrency, Task.Supervisor termination and workspace cleanup are unchanged.
The STATIC result and seven requested regression cases are documented in
[the G5.1 checkpoint](SYMPHONY_G51_STATIC_CHECKPOINT.md).

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

The Orchestrator observation helper generates a random 128-bit worker run ID. The ledger's positive
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
command must remove `SYMPHONY_G5_OBSERVER_KEY_HEX`, `SYMPHONY_G5_OBSERVER_EVENTS`,
`GITHUB_TOKEN`, `GH_TOKEN`,
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

The proof Issue stays open while Codex works. The Local operator may close it
only after preserving and verifying the single allowed artifact under a new
single-LIVE approval. In G5.1, a continuation check may return naturally
(WORKER_COMPLETED), or periodic tracker reconciliation may stop the active
worker (WORKER_STOPPED). Both are real Orchestrator lifecycle observation paths.
Read back the signed event and durable terminal; a closed Issue, stopped child
or deleted workspace alone is not signed terminal evidence. If the parent is
killed first, the observation is unavailable, or workspace identity was not
bound, preserve STARTED_UNRESOLVED/UNKNOWN. Never invent a terminal or launch a
second LIVE to repair it. The historical #341 result remains unchanged.
See [the fresh G5.1 Local LIVE plan](SYMPHONY_G51_LOCAL_LIVE_PLAN.md); this batch
creates no Issue/campaign/proof workspace and starts no LIVE.

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
