# Signal lane model correction (STATIC design, 2026-10-04)

Source: the owner's correction of 2026-10-04. It supersedes the lane labels used in
`docs/SIGNAL_SF10_LANE_INVENTORY_20261004.md` and the registry placeholders.
Machine-readable record: `docs/evidence/signal-lane-model/lane-model-v2.json`.
Nothing here changes the production registry, any durable id, any evidence, Issue #33,
or runs anything LIVE.

## 1. Corrected model

| # | Lane | Mode | Status | Registry today | Identity | Readiness |
|---|---|---|---|---|---|---|
| 1 | Chat -> Jules | SEMI_AUTO | active | `chatgpt-semi-auto` | DURABLE | DURABLE_READY |
| 2 | Chat -> Work | SEMI_AUTO | active | **no row** | UNKNOWN | UNKNOWN |
| 3 | Claude -> Jules | AUTO | active | `claude-gemini` (old label, wrong worker) | PLACEHOLDER | BLOCKED |
| 4 | Work -> Jules | AUTO | in development | `work-gemini` (old label, wrong worker) | PLACEHOLDER | BLOCKED |
| - | Claude -> Claude | AUTO candidate | **FROZEN (provisional)** | `claude-claude` | PLACEHOLDER | not pursued |

- `Chat -> Work` is the same Chat-led SEMI_AUTO shape as `Chat -> Jules`; only the worker differs.
- `claude-gemini` / `work-gemini` are **historical / old placeholder labels**. "Gemini" was a
  wrong worker name. They are not durable identities and not current lane names. History,
  branches and past evidence keep the old names unchanged.
- `Claude -> Claude` is not deleted. Name, origin and evidence stay. It is not counted as an
  active lane, is not a DURABLE target now, runs no LIVE, and is not required for global READY.

## 2. What the code says (checked at main b8e57fe)

- `control_tower.py` worker enum is `JULES, GEMINI, CLAUDE, OTHER`: **no `WORK`**, so a
  `Chat -> Work` row cannot be expressed in registry v1.
- Identity states are only `PLACEHOLDER, DURABLE`: no FROZEN. The existing non-destructive
  way to leave a lane out of global readiness is `enabled=false`
  (`assess_registration_readiness` only inspects enabled lanes).
- Claude -> Jules: real worker path (`claude_jules_*.py`) and 4 LIVE dispatches (Loops 128-131)
  exist on the Claude x Jules feature branch with caller-supplied loop numbers. No Signal
  durable chain under a runtime-chosen stable id. Most mature of the non-durable lanes.
- Work -> Jules: Blue Work BWJ-0..6 STATIC complete; BWJ-7 (real Work->Jules->Work) BLOCKED.
  Identity is carrier/colour based, not a stable loop id.
- Chat -> Work: Cloud Work carriers exist (`docs/CLOUD_WORK_LANES_INDEX.md`); no stable id,
  no registry row. UNKNOWN. No new id is invented here.

## 3. Registry migration design (prepare-only, NOT applied)

Proposed fixture: `docs/evidence/signal-lane-model/proposed-registry-v2-fixture.json`
(validated under today's v1 rules; global registration still NOT_WIRED).

1. `chatgpt-semi-auto`: unchanged, byte-identical (DURABLE id is never renamed).
2. Rename the placeholder rows `claude-gemini` -> `claude-jules`, `work-gemini` -> `work-jules`
   with `worker_kind=JULES`. These are still PLACEHOLDER labels, not durable ids (no durable
   state exists under the old labels), so no durable identity is renamed. The owner must
   confirm the labels; the durable id for each lane is still chosen by that lane's runtime later.
3. `claude-claude`: keep the row, set `enabled=false` (frozen, name kept, excluded from
   global readiness). A clearer explicit FROZEN representation needs a schema change (see 4).
4. `Chat -> Work`: add a row only after the owner picks a placeholder label and the schema
   gains `worker_kind=WORK` (additive change to `_WORKERS`, `_WORKER_LABELS`, the JSON schema
   and the render label). Until then it stays UNKNOWN and is not in the fixture.
5. Order of work: (a) owner confirms labels and the FROZEN representation, (b) additive schema
   PR with tests, (c) registry PR, (d) docs relabel. Each is a separate human-merged PR.
   Rollback of any step is a one-file revert; evidence and history are never deleted.

## 4. Decisions needed from the owner

- A: confirm the placeholder labels `claude-jules`, `work-jules` and a label for Chat -> Work.
- B: approve the additive schema change (`WORK` worker, optional explicit `FROZEN` state) as a
  separate PR, or keep `enabled=false` as the frozen representation.
- Next lane after that: Claude -> Jules is the most mature (needs a stable-id source decision
  and a lane-parameterized proof/approval module; no LIVE until then).

## 5. Safety

LIVE 0, provider calls 0, Issue #33 writes 0, production registry changes 0, durable ids
invented 0, evidence deleted 0.
