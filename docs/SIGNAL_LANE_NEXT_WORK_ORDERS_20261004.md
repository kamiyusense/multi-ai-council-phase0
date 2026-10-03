# Lane next work orders and registry apply plan (STATIC, 2026-10-04)

Shape per order: Upstream / Small component / Existing local destination / Do / Do not / Exit.
No order allows LIVE, a DURABLE flip, an Issue #33 write or a production registry edit.

## A. Registry apply plan (WAITING FOR A HUMAN DECISION)

Goal: replace the four old rows by the five rows of `docs/evidence/signal-lane-model/proposed-registry-v3-fixture.json`
(display `Chat -> Jules` for the durable row; `chat-work-semi-auto`, `claude-jules-auto`, `work-jules-auto` PLACEHOLDER;
`claude-claude-auto` FROZEN + disabled). Worker `WORK` and state `FROZEN` are already supported (PR "WORK/FROZEN support").

Why it is not done: the adoption checks bind the live production file to the approved registry as a whole:

1. `durable_adoption_approval_cli.registries_from_production` (used by `verify_file`, hence by `pre_adoption()` and
   post-adoption item 5) requires the production registry to still equal the committed adoption candidate.
2. `post_adoption_verification` item 13 and `tests/pre_adoption_registry.py` require an identical registry digest.
3. Item 4 expects exactly three other PLACEHOLDER lanes.

Any new row or a display rename turns these red. The change must therefore also edit those checks. The proposed,
strictly-equal-strength replacement (not applied, because the automatic safety review stopped the first attempt as a
security-test change, and that stop is not worked around):

- Verify the approval against the **committed candidate** (`registries_from_candidate`: proposed = candidate file,
  current = candidate with the lane PLACEHOLDER) instead of the live file. The historical decision stays bound to the
  exact digests it approved (items 11 and 12 unchanged).
- Replace "production digest == approved digest" by `adopted_lane_is_unchanged`: the `chatgpt-semi-auto` row is DURABLE
  and byte-equal to the approved entry except `display_name`.
- Keep "exactly one DURABLE lane = chatgpt-semi-auto", and require every other lane to be PLACEHOLDER or FROZEN.

Decision needed from the owner: approve editing those checks in one reviewed Draft PR (a human reads the check diff).

## B. Chat -> Work (`chat-work-semi-auto`, reserved, PLACEHOLDER)

- Upstream: Cloud Work carriers (`docs/CLOUD_WORK_LANES_INDEX.md`), owner decision on which component owns the stable id.
- Small component: use `lane_stable_identity.validate_lane_stable_identity("chat-work", ...)` (added) plus a Chat -> Work
  runtime export of facts (state file, owner chain, receipt, evidence) from the Chat-led Work path.
- Destination: `automation/command_bus/` (new export adapter + tests next to `cloud_work_lanes.py`).
- Do: static fixtures with a hypothetical DURABLE row; reuse `runtime_state_initializer`, `loop_owner*`, the durable collector.
- Do not: derive the id from a colour carrier (cloud-blue/yellow/green/red), PR number, thread or generation.
- Exit: STATIC_READY for the identity contract (done) then the export adapter; lane stays PLACEHOLDER.

## C. Claude -> Jules (`claude-jules-auto`, reserved, PLACEHOLDER) - most mature

- Upstream: `claude_jules_*.py` (4 LIVE dispatches, Loops 128-131, caller-supplied loop numbers; not durable ids).
- Small component 1 (done as contract): `validate_lane_stable_identity("claude-jules", ...)`.
- Small component 2: parameterize the lane-pinned proof and approval code (`signal_step7_live_proof.LANE_ID`,
  `durable_adoption_approval.LANE_ID`) so a second lane can reuse them without forking.
- Small component 3: an export from the Claude x Jules runtime of state/owner chain/receipt/evidence under the stable id.
- Do not: reuse proof 5 as authority, treat Loop numbers 128-131 as the durable id, run LIVE.
- Exit: static E2E (fixture) passes lane registration readiness; then a bounded LIVE proof needs separate owner approval.

## D. Work -> Jules (`work-jules-auto`, reserved, PLACEHOLDER) - in development

- Upstream: Blue Work BWJ-0..6 (STATIC complete); BWJ-7 real Work->Jules->Work turn is BLOCKED by budget/approval.
- Small component: Work-side export of the same durable facts keyed by a runtime-chosen stable id (not colour/carrier).
- Do not: design Blue Work here, treat J-BLUE/cloud-blue as the id, run LIVE.
- Exit: identity contract (done) plus export adapter fixture; remains PLACEHOLDER until BWJ-7 evidence exists.

## E. Claude -> Claude (`claude-claude-auto`, FROZEN)

No work order. Name, history and branches are kept; not active, not DURABLE-targeted, no LIVE, no contract.

## F. Issue #33 dry-run

`docs/evidence/signal-lane-model/issue33-dry-run-render-v3.md` is a pure rendering of the proposed registry (all lanes
UNKNOWN because no verified input; frozen lane on its own line; internal ids only in the machine block). Nothing was
written to Issue #33, whose real body stays STOPPED / owner NONE. A real migration still needs global registration READY
and the live preflight READY.
