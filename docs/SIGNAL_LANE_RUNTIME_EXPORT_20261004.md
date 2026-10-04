# Lane runtime export adapter and stable-id ownership (STATIC, 2026-10-04)

Owner decisions applied (typed by the project owner, 2026-10-04):

1. `chat-work-semi-auto` is a stable durable lane id **owned by the Chat-led SEMI_AUTO runtime**
   (Controller = Chat, Mode = SEMI_AUTO, Worker = Work, the same control shape as Chat -> Jules).
   Flow: `Chat controller / Chat-led semi-auto runtime -> chat-work-semi-auto -> state / owner generation / receipt /
   evidence -> Work carrier / worker_generation / result`. Work facts are worker evidence, never identity.
2. Claude -> Jules: build the smallest export adapter first (`claude-jules-auto` is only a reserved name until the
   registry row is DURABLE through its own approval); share proof/adoption code only where a second real consumer
   needs it ("second real consumer first, smallest shared seam second").

## What was added (all additive, nothing LIVE)

- `automation/command_bus/lane_runtime_export.py`
  - `STABLE_ID_OWNER`: chat-work = `CHAT_LED_SEMI_AUTO_RUNTIME`; claude-jules = `CLAUDE_AUTO_RUNTIME` (same pattern, for
    its own AUTO controller runtime); **work-jules has no owner yet and fails closed**.
  - `validate_identity_owner`: the id must be issued by that owner, never derived (`derived_from` must be empty), never equal
    to worker evidence (colour, carrier PR, lane label, worker_generation, review event, Work thread/session, Jules
    session, loop number) and never a colour/carrier name.
  - `export_lane_runtime(lane, registry=, request=, durable_context=, runtime_facts=)`: pure function. It first applies
    the existing `validate_lane_stable_identity` (the row must already be DURABLE in the registry snapshot given, so a
    PLACEHOLDER row never exports), then checks stable id / owner role (AUTO for claude-jules, SEMI_AUTO for chat-work) /
    contiguous generations with a rising fencing token / target head+tree / state, receipt and observation agree with the
    latest owner event / every record lives under the stable id's directories.
  - Output: the existing durable chain shape (state, `loop_owner_events`, receipt, evidence, provider observation) plus a
    summary: stable id, owner, state, owner generation and fencing, source receipt ref+sha, evidence ref+sha,
    provider/session evidence, target repo/PR/head/tree, result state. `live_authority`, `registry_written`,
    `issue33_written` are always false.
- `automation/command_bus/tests/test_lane_runtime_export.py` (17 tests): ownership rules, negative cases, and a STATIC
  end-to-end: export -> existing `ControlTowerDurableCollector` -> existing `assess_lane_registration_readiness`
  with a hypothetical DURABLE row (READY) and with the production PLACEHOLDER row (NOT_WIRED); global registration stays NOT_WIRED.

## Shared seam decision: nothing to parameterize yet

`signal_step7_live_proof` and `durable_adoption_approval` are pinned to one lane and to the Chat -> Jules carrier
(`LANE_ID`, `J-YELLOW`, one-shot proof constants). The adapter needed none of them: the collector and readiness code are
already lane-generic. So **no proof/adoption code was changed**. A shared seam is justified only when a second lane
really runs a bounded LIVE proof; the first candidate seam is then `LANE_ID`, the carrier claim and the proof task ids.

## Which lane is closest to a first bounded LIVE proof

1. **Claude -> Jules** (closest): AUTO controller, 4 earlier LIVE dispatches, owner chain via `claude_jules_handover`, and now an
   export adapter. Still missing (not built, needs separate approval to go LIVE): the live runtime writing its
   state / owner events / receipt / evidence **under the stable id** (today it uses caller-supplied loop numbers), a
   one-shot proof plan for this lane, and its own adoption approval record.
2. Chat -> Work: no Chat-led runtime that drives Work and writes durable facts exists yet.
3. Work -> Jules: BWJ-7 is blocked by budget/approval and no stable id owner is decided.

Not authorized and not done: any LIVE run, a DURABLE flip of the new lanes, the adoption issuer, provider execution,
Jules POST/GET, Issue #33 write, default-branch write, Merge.
