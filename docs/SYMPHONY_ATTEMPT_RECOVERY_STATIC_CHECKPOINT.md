# Symphony autonomous attempt recovery — STATIC checkpoint

Date: 2026-10-07. Repository: `kamiyusense/multi-ai-council-phase0`.
Workbench: Draft PR #320, `codex/symphony-inspired-minimal-controller`.
Parent readback: `052ccdd37810cf99f527616e4b45c0014910af76`.

**Safety protects continuation. Safety is not the goal of stopping.**

## Implemented recovery

`symphony_attempt_reconciler.py` connects the append-only attempt store to the
campaign kernel. Fresh STATIC controllers restore both stores and checkpoint
reconciliation before selecting more work. This closes the crash gap between
durable TERMINAL and the campaign result checkpoint.

| Durable evidence | Recovery |
| --- | --- |
| Current TERMINAL | Apply verified result once; checkpoint; continue |
| Late TERMINAL after unresolved isolation | Matching attempt blocker required; no model start |
| STARTED_UNRESOLVED | Isolate even if stopped/fenced; continue independent tasks |
| Unstarted intent, no fence | Isolate; missing STARTED or timeout is not a fence |
| Unstarted intent, explicit bound stop/fence | Append retirement; checkpoint reclaim; use new attempt number/ID |
| Older generation | Historical; never apply to the current generation |
| Future generation / contradictory lineage | Campaign authority HARD_UNKNOWN |
| Old target HEAD terminal | Do not adopt on new HEAD; record historical result; replan |
| Duplicate processed result | NO-OP; no new result round or dispatch |
| Temporary transport read failure | UNKNOWN_DURABILITY; preserve authority; no blind write retry |

UNKNOWN requires `unknown_class`; non-UNKNOWN rejects a non-null class.
`affects_campaign_authority` survives restart. A known STARTED cannot be
contradicted by `model_started=false`. Campaign checkpoints retain
result-to-attempt bindings and retired attempt IDs. Old checkpoints without
these optional fields remain readable without invented historical bindings.

## Write/start order

Restore campaign and attempt chains -> reconcile -> checkpoint changes -> next
safe task -> INTENT with exact readback -> RUNNING checkpoint with revision
fencing -> simulate STATIC start -> STARTED readback -> fixture execution ->
TERMINAL readback -> campaign result apply -> result checkpoint -> next task.

All writes are create-only. Ambiguous responses get readback, never blind resend.
A crash after INTENT or RUNNING cannot cause implicit redispatch. A crash after
TERMINAL but before the campaign checkpoint is recovered from durable evidence.
This is duplicate-suppression evidence, not an exactly-once network guarantee.

Observation recovery uses its own predecessor-linked
`observation-NNNNNNNN.json` chain. It never overwrites TERMINAL or starts model
work. A successful observation result survives a missing campaign checkpoint.
Read acquisition exceptions consume bounded observation retries; ordinary runner
exceptions preserve STARTED_UNRESOLVED and isolate only that task.

Unstarted retirement uses create-only `retired.json`, binding the intent digest,
attempt ID, runner generation, explicit STOPPED/FENCED state and evidence ref.
Retired intent cannot become STARTED/TERMINAL. Retirement-before-checkpoint
crashes recover without repeating retirement; a new number changes identity.

## Verification

- Focused suite: 120 tests, PASS.
- Full command-bus regression: 1879 tests, OK with 1 inherited platform skip.
- Compile and diff whitespace checks: PASS.
- All twelve requested reconciliation acceptance cases plus identity collision,
  tampering, unrelated-blocker rejection, transport failure and retirement recovery.
- Crash before/after INTENT, after RUNNING, before/after STARTED, before/after
  TERMINAL, after in-memory result apply and after result checkpoint.
- Ambiguous INTENT/STARTED/TERMINAL/RUNNING/result/retirement writes: each audited
  fixture path has at most one create; no blind retry.
- Late result, observation crash, stale HEAD, exhausted quota with non-model
  recovery, runner faults and bounded observation faults.
- Thirty distinct rounds across five fresh controller sessions; thirty distinct
  simulated starts; no intermediate human gate or duplicate starts.
- Completion at the configured round limit reports CAMPAIGN_COMPLETE when all
  work is complete, rather than misreporting a successful campaign as limited.

Evidence: `automation/command_bus/evidence/symphony-attempt-recovery-static.json`.
Exact-head CI artifacts also include focused/full test logs and evidence digests.

## Upstream seam

Inspected pin: `openai/symphony@be10a1b79df723d6d7612b5651c8522704dafb2e`.
`agent_runner.ex` reuses `app_session` through successive turns and sends
`{:codex_worker_update, issue_id, message}` to the orchestrator.
`orchestrator.ex:reconcile_stalled_running_issues/1` detects stalls. Its ordinary
non-input-required path terminates the worker and schedules a retry.

Track B must intercept retry through durable reconciliation. Upstream local
termination/backoff alone does not authorize redispatch of a started provider.
Reuse the detector, workspace, same-session turn loop and scheduling; add this
durable admission overlay instead of rebuilding those mechanisms in Python.

`symphony_upstream_event_adapter.py` prepares recovery from an explicit envelope.
STALLED/STATUS_AVAILABLE/TERMINAL_AVAILABLE request read-only reconciliation.
Only bound STATIC STOPPED/FENCED for unstarted intent prepares a fence proof.
No event authorizes dispatch. Production authentication remains NOT_WIRED.

## Remaining production boundary / next LIVE state

**Autonomous production LIVE is NOT_READY and remains disabled.**
The controller still admits only exact built-in fixture runner/observer types.
The event adapter refuses unauthenticated captures as fence authority. No actual
upstream worker is launched by these modules.

Before an authorized multi-round LIVE proof, production integration must bind
authenticated worker/session events and current target identity, put the durable
start gate before upstream automatic retry/continuation entry points, and verify
the subscription-only authentication/quota route. Actual cancellation and
cross-process fencing require independent runtime evidence. This STATIC cloud
batch cannot supply that actual provider/runtime evidence.

Keep the consumed strict command consumed and its one-turn/one-start-per-task
proof profile unchanged. Real credentials, LIVE execution, merge and
billing/permission/Secret changes require explicit authorization. No new
authorization is implied by this checkpoint. The stopped Chat's orphan blobs
were not blindly adopted; work was rebuilt from fresh branch contents.
