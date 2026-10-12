# Claude takeover V1: two Jules attempts, then one stronger Claude attempt

Owner decision, 2026-10-12 JST (chat with Claude Code): Jules gets two attempts at a task; if both fail, a second
routine ("takeover worker", a stronger model) gets one attempt; the reviewer routine judges it as usual. Nothing is
merged without the owner.

```text
round 1: Jules PR  -> reviewer NEEDS_CORRECTION -> @jules corrective (and the Jules API resend if ignored)
round 2: Jules     -> reviewer NEEDS_CORRECTION -> receipt decision TAKEOVER_REQUESTED, no PR comment
         LAYER 4 tick opens branch claude/takeover-<task_id> at the reviewed Jules head + one PR ("Fixes #N")
         -> pull_request.opened on that branch wakes the takeover worker (and only it)
round 3: worker commits on that branch -> reviewer: PASS -> next task / anything else -> TASK_BLOCKED (owner)
```

## Owner rules

1. Jules ignoring the corrective and its Jules API resend (a same-content commit after the resend, or nothing for
   the ack timeout) goes to the takeover at once instead of waiting for round 2.
2. BLOCKED reasons (permission, billing, secrets, another repository, destructive operations, contradictory or
   out-of-scope requirements) are TASK_BLOCKED for the owner, never a takeover.
3. The reviewer judges the takeover PR more strictly: a deleted, skipped or weakened test and any change outside
   `allowed_paths` is a major finding, and anything but PASS ends the task (no further round).

## Pieces

| Piece | Where |
|---|---|
| Reviewer v1.8 (three changed lines) | `docs/evidence/claude-jules-production-starter-20261009/routine-prompt-v1.8.CANDIDATE.txt` |
| Takeover worker prompt | `docs/evidence/claude-jules-production-starter-20261009/takeover-routine-prompt-v1.CANDIDATE.txt` |
| Tick: open / track the takeover PR | `claude_jules_loop.takeover_wanted`, `_takeover` (stall after 120 minutes -> owner) |
| Ports | `GhLoopPort.takeover_state` / `takeover_request`, `GhLiveWritePort.open_takeover` (write kind `takeover`) |
| Authorization | `takeover` added to `writes` in `docs/claude-jules-loop/active/authorization.json` |

## Owner setup after merge

1. Reviewer routine: replace its prompt with reviewer v1.8 (model stays Sonnet).
2. New routine "Claude takeover worker": prompt = takeover worker prompt; model = Opus; repository =
   kamiyusense/multi-ai-council-phase0; same environment as the reviewer; trigger = GitHub event
   `pull_request.opened` with the filter **Head branch starts with `claude/takeover-`**; no schedule; remove
   connectors it does not need.

## UNKNOWN until first use

- GitHub event delivery is capped per routine and per account each hour; a dropped `opened` event leaves the
  takeover PR without a worker commit, which the tick reports as TAKEOVER_STALLED after 120 minutes.
- How often the stronger model passes where Jules failed twice.
