# Chat ⇄ Work ⇄ Jules Autopilot Implementation Handoff

Updated: 2026-09-22
Repository: `kamiyusense/multi-ai-council-phase0`
Recovery design PR: #5
Status: IMPLEMENTATION HANDOFF / DO NOT MERGE YET

## 0. Architecture decision

Use this architecture as the working target:

```text
GitHub
= canonical durable state / control plane

PR #4
= persistent Relay implementation workbench

Jules
= disposable implementation executor

Work
= controller / executor manager

Chat
= reviewer / planner

GitHub command-bus
= durable inter-agent control channel

Work GitHub event-triggered task
= primary wake-up mechanism

Direct Work -> Chat -> Work thread path
= optional fast path, not required for correctness

state / command / receipt / evidence ledger
= durable checkpoint + idempotency + recovery

Human
= exception / approval boundary only
```

Important refinement from the earlier draft:
The GitHub command-bus is not merely a last-resort fallback. It is the durable source of inter-agent control state.
A direct thread round-trip may be used as a fast path only when correlation/readback is provably correct.

## 1. Current anchors

Relay implementation workbench:
- PR: #4
- branch: `feature/relay-transport-7070955470193506982`
- verified head at this checkpoint: `62f341b04f9d6e19dd003b42304bb896e4db45ef`
- base: `main`
- static/mock test evidence: 22 passed, exit 0
- compileall: exit 0

Recovery design:
- PR: #5
- branch: `docs/chat-work-command-bus-design`
- design file: `docs/CHAT_WORK_GITHUB_COMMAND_BUS_DESIGN.md`

Existing Jules task:
- task id: `7070955470193506982`
- continuity status: UNKNOWN/BLOCKED
- stale local sandbox head reported by Jules: `af9c5517ed8678bdff3af60fd298dd586d5a6786`
- do not retry that same stale-sandbox continuation automatically

## 2. Work mission

Work is the controller.

Execute the largest safe batch possible without returning to the user for ordinary progress checkpoints.

Order:

```text
inspect
-> implement static command-bus
-> tests
-> fix
-> retest
-> create implementation PR
-> configure/prepare GitHub event trigger
-> perform one harmless event round if supported
-> readback
-> checkpoint
-> stop only at a real blocker or approval boundary
```

Do not ask "continue?" at intermediate stages.

## 3. Implementation PR

Keep PR #5 as design/recovery documentation.

Create a separate implementation branch and PR:

- branch: `feature/chat-work-command-bus`
- base: `main`
- PR title: `feat: add bounded Chat-Work GitHub command bus`

Do not merge.

No force push.
No branch deletion.
No main direct write.

## 4. Static implementation scope

Implement under:

```text
automation/command_bus/
  README.md
  schema/
    command.schema.json
    receipt.schema.json
    state.schema.json
  state_machine.py
  ledger.py
  validator.py
  event_processor.py
  fixtures/
  tests/
```

Use Python unless the repository architecture gives a stronger reason otherwise.

No live provider/Jules execution is required for the static implementation.

## 5. Required state model

Required fields:

- schema_version
- loop_id
- state
- round
- max_rounds
- expires_at
- stop_requested
- last_command_id
- last_receipt_id
- expected_target
- retry_policy

Required states:

```text
PREPARED
RUNNING
WAITING_FOR_EVIDENCE
COMPLETE
HALTED
FAILED
UNKNOWN
EXPIRED
```

Only RUNNING may execute a new non-STOP command.

Default maximum:
`max_rounds = 6`

Six is a hard ceiling, not a target.

## 6. Command rules

Commands are append-only and immutable after commit.

Required command identity:

- command_id
- loop_id
- round
- correlation_id
- target
- action
- expected_repo
- expected_pr
- expected_head
- retry = 0
- fallback = disabled
- requires_live_model
- requires_github_write

A correction creates a new command ID.
Never overwrite an already committed command.

## 7. Receipt rules

Receipts are append-only.

Terminal states:

```text
DONE
BLOCKED
FAILED
UNKNOWN
CANCELLED
```

One terminal receipt permanently prevents automatic replay of the same command_id.

Receipt must preserve:

- receipt_id
- command_id
- loop_id
- correlation_id
- result state
- executed_once
- GitHub head before/after where relevant
- external send attempted YES/NO
- external send readback verified YES/NO/UNKNOWN
- retry_count
- fallback_used
- evidence_refs

## 8. Hard-stop rules

Before any external side effect, halt if:

- round >= max_rounds
- expired
- stop_requested
- state is COMPLETE/HALTED/FAILED/UNKNOWN/EXPIRED
- correlation mismatch
- wrong repository/PR/target
- expected_head mismatch
- terminal receipt already exists
- external send result is ambiguous
- readback cannot verify success
- same operation would require retry
- permission/auth/billing/safety state is UNKNOWN

Ambiguous delivery is UNKNOWN.
Automatic retry remains 0.

## 9. Receipt-event recursion guard

A GitHub event alone must never cause execution.

Process:

```text
event
-> read state
-> discover new unprocessed command
-> verify state RUNNING
-> verify target/correlation/head
-> verify no terminal receipt
-> execute once
```

If an event was caused only by a receipt/evidence write and no new command exists:

`NO-OP`

Do not write another receipt for a NO-OP event.

## 10. Required static tests

At minimum prove:

- command schema valid/invalid cases
- receipt schema valid/invalid cases
- state schema valid/invalid cases
- monotonic round progression
- max_rounds=6 hard stop
- STOP hard stop
- expiry hard stop
- duplicate command ignored
- terminal receipt prevents replay
- receipt-only event is NO-OP
- expected_head mismatch blocks
- correlation mismatch blocks
- wrong repo/PR blocks
- ambiguous send -> UNKNOWN
- retry remains 0
- fallback remains disabled
- stale executor workspace blocks
- command files remain append-only
- recovery finds last verified command/receipt
- six-round mock loop halts deterministically

Do not call PASS unless tests actually ran.

## 11. Event-triggered Work task

Official ChatGPT Work supports event-triggered tasks from connected GitHub pull-request activity, including supported PR commit-update activity depending on the selected trigger.

If this Work environment exposes creation of an event-triggered GitHub task, configure one for the command-bus implementation PR.

Trigger intent:
- authorized repository: `kamiyusense/multi-ai-council-phase0`
- target: command-bus implementation PR activity
- preferably commit updates
- broad trigger is acceptable if Work always fail-closes unless a new unprocessed command exists

Task prompt behavior:

```text
Read the exact command-bus state and latest unprocessed command.
If no new valid command exists, do nothing.
If state is not RUNNING, do nothing.
Validate loop_id/round/correlation/repo/PR/head.
Never retry an ambiguous external action.
Write a terminal receipt only for a command that was actually processed.
Do not merge.
Do not create API keys.
Do not change billing/settings/permissions.
Do not execute a live provider/Jules task unless separately authorized.
```

If trigger creation requires an account/system approval UI, stop at that approval boundary and report it.
Do not bypass it.

## 12. One harmless real event test

Only after static tests pass and the event-triggered Work task is configured:

Create one harmless command-bus test command that requires no Jules/model execution.

Example action:
`ECHO_AND_RECEIPT`

Expected behavior:

```text
GitHub command commit
-> Work event trigger fires
-> Work reads exact command
-> validates it
-> creates/verifies one receipt
-> stops
```

Evidence required:
- command commit SHA
- event/task run identity if available
- receipt commit SHA or equivalent durable receipt
- exactly one processed command
- retry_count = 0
- no Jules task created
- no live model/provider execution caused by the command
- no merge

If delivery/write result is ambiguous, UNKNOWN and stop.
No retry.

## 13. Direct Work -> Chat -> Work path

This path is optional optimization.

If available, test only after the durable command-bus static/event path is healthy.

Requirements:

- unique correlation_id
- Work sends one message
- Work retrieves only assistant output after that send
- exact thread identity verified
- exact round/correlation verified
- empty/unavailable/mismatch => UNKNOWN
- no resend

Do not make closed-loop correctness depend on this path.

## 14. Jules executor policy

Jules is disposable.

Do not depend on task `7070955470193506982` remaining alive.

Persistent identity is:

```text
GitHub repository
+ PR #4
+ PR #4 head branch
+ verified head SHA
```

Future Jules task flow should be:

```text
read current PR #4 head
-> create fresh Jules executor from that branch
-> verify executor sees expected head
-> issue one bounded implementation instruction
-> publish/commit back to the same PR #4 branch if supported
-> GitHub readback
-> task may be discarded
```

However, do NOT create a new Jules task during the command-bus infrastructure test unless the current user authorization explicitly covers that external model execution and the environment has no approval boundary.

If uncertain:
stop before Jules creation and report the exact remaining step.

## 15. Safe-work exhaustion

Before returning to the user, finish all independent safe work:

- static implementation
- fixtures
- unit/regression tests
- mock six-round test
- docs/readme
- recovery/checkpoint
- implementation PR
- hashes/SHAs/readback
- event-trigger setup if no approval blocker
- one no-Jules harmless event test if configured

One blocker must not stop unrelated safe tasks.

## 16. Final report format

Return one consolidated report:

- architecture used
- implementation PR number/url
- branch
- base
- head SHA
- changed files
- tests actually run
- exact PASS/FAIL/UNKNOWN counts
- six-round mock result
- event trigger created: YES/NO/UNKNOWN
- harmless real event test: PASS/FAIL/UNKNOWN/NOT_RUN
- direct Work->Chat->Work test: PASS/FAIL/UNKNOWN/NOT_RUN
- new Jules task created: YES/NO
- live provider/model execution: YES/NO
- API key used: YES/NO
- GitHub write performed: YES/NO
- retry count
- fallback used
- blockers
- deferred decisions
- user action required
- Merge performed: NO

Do not merge anything.
