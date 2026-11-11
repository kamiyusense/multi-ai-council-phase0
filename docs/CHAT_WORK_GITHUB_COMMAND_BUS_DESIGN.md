# Chat ⇄ Work GitHub Command Bus Design / Recovery Report

Updated: 2026-09-22  
Repository: `kamiyusense/multi-ai-council-phase0`  
Document branch: `docs/chat-work-command-bus-design`  
Status: DESIGN / RECOVERY CHECKPOINT ONLY  
Merge: **NOT AUTHORIZED / NOT PERFORMED**

---

## 0. Purpose

This document is the recovery-safe design checkpoint for removing the human from the relay path between Chat, Work, Jules, and GitHub.

The target is not merely "automate some messages". The target is:

```text
Jules produces evidence/work
  -> GitHub records it
  -> Work/Chat detect it
  -> review happens
  -> next instruction is emitted
  -> Work receives the instruction
  -> Work drives Jules
  -> repeat
```

without requiring the user to copy/paste every round.

This document must be sufficient to recover the design if the current Chat dies or reaches a context limit.

---

## 1. Current verified project state

### 1.1 Relay long-lived workbench

Repository:

`kamiyusense/multi-ai-council-phase0`

Relay long-lived PR:

`PR #4`

Head branch:

`feature/relay-transport-7070955470193506982`

Current verified head:

`62f341b04f9d6e19dd003b42304bb896e4db45ef`

Current PR base:

`main`

Main checkpoint:

`230026f53f412cd52d8e2eac45457236c916b64d`

Verified relationship at this checkpoint:

```text
main
  -> PR #4
```

with PR #4 ahead of main and not behind at the time of verification.

### 1.2 Static/mock verification

The exact command:

```bash
PYTHONPATH=src python -m pytest -q tests
```

was independently reconstructed from the exact PR #4 GitHub blobs and executed outside Jules.

Observed result:

```text
22 passed
exit code 0
```

Additional syntax verification:

```bash
python -m compileall -q src tests
```

Observed result:

```text
exit code 0
```

This evidence is independent of Jules' self-report.

### 1.3 Relay safety foundation currently present

PR #4 contains, among other items:

- deterministic canonical JSON + SHA-256 dispatch hashing
- duplicate/conflict guard
- mock transport
- relay lifecycle
- provider policy
- automatic retry = 0
- fallback disabled
- live_ready = false
- API-key route disabled by policy
- Claude dangerous bypass false
- Antigravity ACP policy
- malformed/UNKNOWN non-success handling
- static/mock provider integration tests

Live provider execution remains separately blocked and is **not authorized by this document**.

---

## 2. Current Jules continuity blocker

Existing Jules task:

`7070955470193506982`

A continuity probe attempted to reuse the same task and the existing PR #4 branch.

Jules returned UNKNOWN and reported:

- the expected branch `feature/relay-transport-7070955470193506982` was not present in its local sandbox
- remote fetch was blocked by a permission error
- Jules-reported local HEAD was `af9c5517ed8678bdff3af60fd298dd586d5a6786`
- expected GitHub HEAD was `62f341b04f9d6e19dd003b42304bb896e4db45ef`
- no file/code changes were made
- Jules stopped rather than guessing

Therefore:

```text
same Jules task
  -> same current GitHub branch
  -> same PR #4 continuation
```

is currently:

`UNKNOWN / BLOCKED BY STALE SANDBOX OR FETCH ACCESS`

Do not reinterpret this as a failure of PR #4 itself.

Do not assume the Jules-reported local commit exists on GitHub.

Do not retry an ambiguous write/send automatically.

---

## 3. Why a GitHub command bus is being designed

The originally desired route was:

```text
Jules
  -> GitHub
  -> Work monitors/reviews
  -> Work asks Chat
  -> Chat returns next instruction
  -> Work reads Chat response
  -> Work sends it to Jules
```

Work has exposed thread tools such as:

- `send_message_to_thread`
- `read_thread`
- `list_threads`

but Chat-side direct Work messaging has not been consistently exposed.

A Work -> Chat -> Work experiment proved that message delivery and Chat response can occur, but reply-selection/correlation handling was not fully reliable.

Therefore two controller paths are retained.

### Path A — direct thread loop

```text
GitHub event
  -> Work
  -> send_message_to_thread(Chat)
  -> Chat response
  -> Work read_thread()
  -> correlation-verified instruction
  -> Jules
```

Preferred when reliable.

### Path B — GitHub command bus fallback

```text
Chat
  -> writes command object to GitHub command-bus PR
  -> GitHub event
  -> Work wakes
  -> Work reads command object
  -> Work acts / drives Jules
  -> Work writes receipt
```

Path B does not depend on Chat exposing `send_message_to_thread`.

---

## 4. Design principle

GitHub is used as:

- durable shared state
- append-only message log
- evidence store
- wake-up trigger source
- recovery checkpoint

It is **not** used as an unbounded self-triggering loop.

Every action must be:

- uniquely identified
- correlated to one loop/round
- bounded by a round limit
- expiry-bounded
- duplicate-guarded
- fail-closed on UNKNOWN
- auditable after the fact

---

## 5. Proposed repository layout

The command bus should be isolated from product code.

Recommended long-lived branch:

`relay/chat-work-command-bus`

Recommended long-lived Draft PR:

`chore: Chat ⇄ Work command bus`

Recommended tree:

```text
automation/command_bus/
  README.md
  schema/
    command.schema.json
    receipt.schema.json
    state.schema.json
  state/
    relay-dev-001.json
  commands/
    relay-dev-001/
      000001.json
      000002.json
      ...
  receipts/
    relay-dev-001/
      000001.json
      000002.json
      ...
  evidence/
    relay-dev-001/
      round-000001.md
      round-000002.md
      ...
```

The command-bus PR must stay separate from PR #4.

Reason:

```text
PR #4
  = Relay implementation workbench

command-bus PR
  = Chat/Work communication and audit workbench
```

Do not mix message traffic into Relay product diffs.

---

## 6. Append-only rule

Do not use a single mutable `command.json` as the only message channel.

Commands and receipts should be append-only.

Bad:

```text
latest_command.json
  overwritten every round
```

Preferred:

```text
commands/relay-dev-001/000001.json
commands/relay-dev-001/000002.json
commands/relay-dev-001/000003.json
```

Benefits:

- old instructions cannot silently disappear
- one command maps to one receipt
- duplicate execution can be detected
- Git history becomes an audit trail
- recovery can determine the exact last completed round

Only the loop state object is intentionally mutable.

---

## 7. Loop state model

Example:

```json
{
  "schema_version": 1,
  "loop_id": "relay-dev-001",
  "state": "RUNNING",
  "round": 2,
  "max_rounds": 6,
  "expires_at": "2026-09-23T12:00:00+09:00",
  "stop_requested": false,
  "last_command_id": "000002",
  "last_receipt_id": "000002",
  "expected_target": "work",
  "retry_policy": 0
}
```

Required lifecycle states:

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

Only `RUNNING` may create or execute the next command.

---

## 8. Hard stop conditions

Work must inspect state **before doing anything external**.

Stop immediately if any of the following is true:

1. `round >= max_rounds`
2. `expires_at` has passed
3. `stop_requested == true`
4. state is `COMPLETE`
5. state is `HALTED`
6. state is `FAILED`
7. state is `UNKNOWN`
8. state is `EXPIRED`
9. command correlation does not match the active loop
10. the same command ID already has a terminal receipt
11. thread/round/correlation readback cannot be verified
12. ambiguous external send result cannot be disambiguated by readback
13. same external operation would require automatic retry
14. a safety boundary becomes UNKNOWN

Current project default:

`max_rounds = 6`

Six is a ceiling, not a target.

---

## 9. Explicit STOP command

Example:

```json
{
  "schema_version": 1,
  "command_id": "STOP-000001",
  "loop_id": "relay-dev-001",
  "type": "STOP",
  "target": "work",
  "reason": "user requested stop"
}
```

On receipt, Work must set:

```json
{
  "state": "HALTED",
  "stop_requested": true
}
```

and perform no further Jules/provider dispatch.

A later resume must be an explicit new command and must not silently reuse an expired/unknown round.

---

## 10. Command object

Example:

```json
{
  "schema_version": 1,
  "command_id": "000003",
  "loop_id": "relay-dev-001",
  "round": 3,
  "correlation_id": "relay-dev-001-round-3",
  "target": "work",
  "action": "REVIEW_PR4_AND_PREPARE_JULES_INSTRUCTION",
  "expected_repo": "kamiyusense/multi-ai-council-phase0",
  "expected_pr": 4,
  "expected_head": "62f341b04f9d6e19dd003b42304bb896e4db45ef",
  "retry": 0,
  "fallback": "disabled",
  "requires_live_model": false,
  "requires_github_write": false,
  "instruction": "Review the exact PR #4 head and prepare the next safe Jules instruction."
}
```

The command is immutable after commit.

If it needs correction, create a new command with a new ID.

---

## 11. Receipt object

Example:

```json
{
  "schema_version": 1,
  "receipt_id": "000003",
  "command_id": "000003",
  "loop_id": "relay-dev-001",
  "correlation_id": "relay-dev-001-round-3",
  "state": "DONE",
  "executed_once": true,
  "github_head_before": "62f341b04f9d6e19dd003b42304bb896e4db45ef",
  "github_head_after": "62f341b04f9d6e19dd003b42304bb896e4db45ef",
  "jules_message_sent": false,
  "retry_count": 0,
  "fallback_used": false,
  "evidence_refs": []
}
```

Terminal receipt states should include:

```text
DONE
BLOCKED
FAILED
UNKNOWN
CANCELLED
```

A terminal receipt prevents the same command from executing again.

---

## 12. Event-trigger loop

Target event flow:

```text
[1] Jules/Work updates PR #4
       |
       v
[2] GitHub PR event
       |
       v
[3] Work wakes
       |
       v
[4] Work reads exact PR #4 head/diff/evidence
       |
       v
[5] Work reviews or asks Chat
       |
       +---------------------------+
       | Path A                    | Path B
       v                           v
 send_message_to_thread      Chat writes command
       |                      to command-bus PR
       v                           |
 Chat response                    v
       |                      GitHub event
       v                           |
 read_thread + correlation         v
       |                         Work wakes
       +-------------+-------------+
                     |
                     v
[6] Work prepares next Jules instruction
                     |
                     v
[7] Work sends once to Jules
                     |
                     v
[8] Jules produces result / GitHub evidence
                     |
                     v
[9] receipt + round increment
                     |
                     v
[10] stop condition check
```

No automatic retry is permitted for an ambiguous external send.

---

## 13. Preventing receipt-trigger loops

A receipt commit may itself trigger GitHub automation.

Therefore an event must not mean "execute something" by itself.

Work must run:

```text
event arrived
  -> read state
  -> discover unprocessed command
  -> verify command target
  -> verify no terminal receipt
  -> verify RUNNING
  -> only then execute
```

A receipt-only commit with no new command must result in:

`NO-OP`

and must not generate another receipt.

---

## 14. Stagnation detection

The loop should halt rather than spin if it is not making progress.

Recommended stop heuristics:

- same PR head SHA observed for two consecutive implementation rounds where a new head was expected
- same FAIL signature observed twice
- same UNKNOWN signature observed twice
- Jules reply retrieval unavailable
- Chat reply retrieval unavailable/unverified
- correlation mismatch
- expected evidence missing
- requested branch cannot be synchronized
- same command becomes eligible twice
- remote write result ambiguous

When triggered:

`state = UNKNOWN` or `HALTED`

No automatic resend.

---

## 15. Work controller responsibilities

Work is the controller.

Work should:

- receive GitHub event wakeups
- read the exact current GitHub state
- verify loop state before action
- perform review/evidence gathering
- contact Chat when judgment/design review is needed
- retrieve Chat response when possible
- use correlation IDs
- send one verified instruction to Jules
- perform readback after external actions
- write receipts/checkpoints
- stop on ambiguity

Work must not:

- treat Jules self-report as sufficient evidence
- auto-retry ambiguous sends
- invent PASS
- bypass system approvals
- change billing/credits/permissions
- create API keys
- start unapproved live provider/model execution
- merge without human approval

---

## 16. Chat responsibilities

Chat is the design/review authority, not the loop clock.

Chat should:

- inspect exact GitHub evidence
- review architecture/safety
- issue the next bounded instruction
- include `loop_id`, `round`, `correlation_id`, expected PR/head when possible
- write a GitHub command only when direct Work return-path is unavailable
- produce STOP/HALT commands when required

Chat should not:

- depend on memory alone
- assume Work saw an instruction without receipt/readback
- overwrite an old command
- issue a second command for the same round when delivery is ambiguous

---

## 17. Jules responsibilities

Jules is an implementation worker.

Jules should:

- modify code/tests/docs within approved scope
- produce normal commits/evidence
- avoid live provider execution unless separately approved
- stop when repository state cannot be verified

Jules must not be treated as the canonical state store.

GitHub is canonical.

### Current known Jules limitation

The existing Jules task currently cannot prove synchronization to the latest PR #4 head.

Therefore the future controller must require:

```text
expected_head readback
  -> workspace sync proven
  -> only then mutate
```

If sync cannot be proven:

`UNKNOWN / HALT`

The command bus must not depend on one permanent Jules sandbox.

---

## 18. Executor replacement boundary

The command bus design intentionally separates:

```text
controller
from
executor
```

so the loop can survive a dead/stale Jules task.

Possible future executors may include:

- the same Jules task, if synchronization is restored
- a new Jules task, if explicitly authorized
- Work/local git-capable executor
- another approved implementation agent

Switching executor is not automatic when permissions, billing, GitHub writes, or live execution boundaries differ.

If executor replacement is required and not pre-authorized:

`HALT + user decision`

---

## 19. GitHub write policy for the command bus

The command-bus branch is intended to be writeable by Chat/Work only within its narrow mailbox scope.

Recommended allowed paths:

```text
automation/command_bus/**
```

Recommended prohibited paths for bus-runtime writes:

```text
src/**
tests/**
docs/**
.github/**
main
PR #4 implementation branch
```

The command bus should never become a side channel for arbitrary source edits.

---

## 20. Security / safety boundaries

Mandatory defaults:

- no Merge without explicit human approval
- no force push
- no branch deletion
- no API key creation/use as a workaround
- no Billing/Credits/Overages mutation
- no settings/permissions mutation
- no permission bypass
- no hidden fallback
- automatic retry = 0
- live provider execution separately approved
- UNKNOWN => fail closed
- command target/repo/PR/head must be validated
- untrusted text must not become arbitrary shell
- receipt/evidence must not fabricate backend success

---

## 21. Recovery procedure if the current Chat disappears

A fresh Chat/Work must recover in this order.

### Step 1 — read canonical documents

Read:

1. `AGENTS.md`
2. `HANDOVER_CURRENT.md`
3. `docs/CHAT_WORK_AUTONOMY_RULES.md`
4. this document
5. PR #4 current GitHub state

Do not trust the old conversation summary over GitHub.

### Step 2 — verify implementation workbench

Verify:

- repository
- PR #4 state
- PR #4 base
- PR #4 head branch
- exact head SHA
- Merge state

Expected checkpoint at document creation:

`62f341b04f9d6e19dd003b42304bb896e4db45ef`

If moved, use current GitHub state and mark this checkpoint historical.

### Step 3 — verify command-bus state

If a command-bus PR exists, read:

```text
automation/command_bus/state/*.json
automation/command_bus/commands/**
automation/command_bus/receipts/**
```

Find:

- active `loop_id`
- latest round
- latest command
- latest terminal receipt
- stop/expiry state

### Step 4 — never replay blindly

If the newest command has no verified receipt:

do not resend automatically.

First determine whether the external action may already have succeeded.

If not verifiable:

`UNKNOWN / HALT`

### Step 5 — resume only from verified checkpoint

Resume from the last command/receipt pair whose correlation and GitHub evidence are proven.

---

## 22. Proposed implementation phases

### Phase A — static schema only

Implement:

- directory structure
- JSON schemas
- parser/validator
- state machine
- duplicate guard
- stop conditions
- mock event processor
- receipts
- fixtures

No webhook/live event required.

### Phase B — local/mock six-round simulation

Simulate:

```text
command
 -> work mock
 -> receipt
 -> command
 -> ...
```

Verify:

- maximum six rounds
- STOP
- expiry
- duplicate command
- duplicate event
- receipt-only event no-op
- same-UNKNOWN halt
- stale expected head
- correlation mismatch
- retry remains zero

### Phase C — one real GitHub event, no Jules mutation

Create one harmless command-bus commit.

Verify only:

```text
GitHub event
 -> Work wakes
 -> command recognized
 -> receipt/evidence generated
 -> stop
```

No Jules send yet.

### Phase D — Work -> Chat -> Work one-round validation

If direct thread route is available:

```text
Work -> Chat -> Work
```

must verify exact correlation and assistant turn identity.

### Phase E — one Jules instruction

Only after A-D pass:

```text
Work
 -> one Jules instruction
 -> GitHub/readback
 -> stop
```

No recurring autonomous loop yet.

### Phase F — bounded closed loop

Enable:

`max_rounds <= 6`

with explicit expiry and STOP support.

---

## 23. Required tests before bounded live orchestration

At minimum:

- command schema validation
- receipt schema validation
- state schema validation
- monotonic round increment
- max_rounds=6 hard stop
- STOP hard stop
- expiry hard stop
- duplicate command ignored
- terminal receipt prevents replay
- receipt-only event is no-op
- expected_head mismatch blocks
- correlation mismatch blocks
- unknown target blocks
- wrong repo/PR blocks
- ambiguous send => UNKNOWN
- retry remains 0
- fallback remains disabled
- stale Jules workspace blocks
- command history remains append-only
- recovery discovers last verified round

Do not call this PASS without executable evidence.

---

## 24. Evidence checklist per round

Record as much as available:

- loop_id
- round
- command_id
- correlation_id
- source event
- repository
- PR number
- expected head
- observed head before
- observed head after
- command commit SHA
- receipt commit SHA
- Work task/thread identity
- Chat thread identity
- Jules task identity
- exact instruction hash
- send attempted YES/NO
- send readback verified YES/NO/UNKNOWN
- retry count
- fallback state
- live model/provider execution
- API key used
- GitHub write scope
- result PASS/FAIL/UNKNOWN
- next safe action

---

## 25. Open questions / deferred decisions

### DD-001 — direct thread route reliability

Question:

Can Work reliably select the exact new Chat response by correlation/turn identity?

Current state:

`UNKNOWN`

Safe default:

Use GitHub command bus when direct reply retrieval is not provably correct.

### DD-002 — Work GitHub event trigger exact production configuration

Question:

Which GitHub PR event(s) and path filters should be enabled for the command-bus PR?

Current state:

Design known; final configured trigger must be verified at implementation time.

Safe default:

Trigger broadly, then fail closed in Work unless a new unprocessed command exists.

### DD-003 — existing Jules task continuity

Question:

Can task `7070955470193506982` synchronize to the current PR #4 head and keep updating the same branch?

Current state:

`UNKNOWN / currently blocked`

Safe default:

Do not let it modify until expected head is verified.

### DD-004 — executor replacement

Question:

If existing Jules task remains stale, should a replacement Jules task be allowed?

Current state:

Human decision required before new external task/branch/PR behavior is allowed.

Safe default:

HALT.

---

## 26. Completion criteria for the command-bus project

The command bus is not complete merely because files exist.

Complete only when evidence proves:

1. command schema works
2. receipt schema works
3. state machine works
4. max-six hard stop works
5. STOP works
6. duplicate guard works
7. receipt-only events do not loop
8. GitHub event wakes Work
9. Work reads exact command
10. Work does not replay terminal command
11. one Chat review round can be correlated
12. one Jules round can be correlated
13. GitHub readback proves result
14. recovery from a fresh Chat can find the last verified round
15. live provider/model execution remains separately gated

---

## 27. Current recommended next move

Do not build a fully live self-loop immediately.

Next safe batch should be:

```text
static command-bus schema
 -> state machine
 -> duplicate guard
 -> STOP/max6/expiry
 -> fixtures
 -> unit/regression tests
 -> mock six-round loop
 -> checkpoint
```

Then stop before the first real event-driven Work/Jules loop unless explicitly authorized.

---

## 28. Final checkpoint summary

At this document checkpoint:

- Relay PR #4 static/mock workbench: READY
- PR #4 head: `62f341b04f9d6e19dd003b42304bb896e4db45ef`
- PR #4 base: `main`
- Relay pytest: 22 PASS
- live Relay/provider execution: NO
- command-bus implementation: NOT STARTED
- command-bus live event POC: NOT STARTED
- existing Jules same-task continuation: UNKNOWN / BLOCKED
- API key route: NO
- automatic retry: 0
- fallback: disabled
- Merge performed by this report task: NO

This document is the recovery anchor for the next Chat/Work session.
