# Claude→Jules proof 2: STATIC preparation before a bounded LIVE (2026-10-15)

Status: STATIC only. LIVE 0 / Jules POST 0 / Jules GET 0 / provider 0. This note is not a LIVE approval.
Replaces the closed Draft PR #323 (2026-10-06 premise: ledger 6/10), whose ledger numbers were out of date.

## Facts (GitHub readback, 2026-10-15, main 2485309)

- Old Loop A ledger (`claude-auto-live-budget`, data branch `claude/claude-jules-autoloop-data`): `slot-01`..`slot-09` = **9/10**.
  slot-05 = Loop 137 (proof 1, result UNKNOWN), slot-06 = Loop 139, slots 07-09 = github-native probes of 2026-10-08.
  Exactly **one slot (10) is left**; a proof 2 would take the last one and exhaust the old Loop A budget (the cap is fixed by the
  original human authorization and cannot be raised by code).
- The prod-c1 production ledger (`claude-jules-production-budget/jules-prod-c1`, cap 9999) is a different ledger and is not used by this proof.
- Proof 1 is spent (attempt marker + UNKNOWN terminal receipt); it is never re-run. Jules PRs #310 and #322 are never merged or edited.
- Production registry: `chatgpt-semi-auto` DURABLE, the other lanes PLACEHOLDER, `claude-claude-auto` FROZEN; Issue #33 STOPPED.

## What this change adds (code is STATIC)

| Change | Content |
| --- | --- |
| `RUN_PROFILES` | Known proof runs only. Run 1 as before (ledger floor 4). Run 2 = `claude-jules-stable-lane-proof-2`: ledger floor **9**, spent loops `128-131,137,138,139`. Any other run id is `PLAN_UNKNOWN_RUN`. |
| Ledger count | Plan-bound (from Jules PR #405): the plan's `loop_a_slots_used_before` must be at or above the run floor and leave room under the cap of 10; the CLI refuses with `BUDGET_COUNT_UNEXPECTED` unless the live ledger holds exactly that many slots. |
| Evidence paths | Per run: `docs/evidence/<proof_task_id>/{attempt-marker,terminal-receipt}.json`, never colliding with run 1. |
| CLI | `--proof-task-id` and `--loop-a-slots-used-before` select the run and the expected count. |
| Tests | `test_claude_jules_lane_proof_run2.py`: plan binding, tampering, evidence separation, once-only marker, spent loops, CLI counts. |

## What a bounded LIVE would still need (nothing done yet)

- A new origin loop (for example `claude-auto-loop-a-004`) and an unused Loop number.
- The owner's explicit LIVE sentence and a `live_dispatch_authorization` (approved_by / approval_ref / scope / max_dispatches 1 / expires_at); only the owner writes it.
- The owner's decision to spend the **last** old Loop A slot.
- Run on the owner's PC via Remote Control (a cloud run was blocked by the auto safety review for policy writes); the API key stays in that window's environment only.
- Independent inspection (the 💜 thread) of the plan before the owner types the LIVE sentence.

## Route guard finding (2026-10-15, found while preparing the run; STATIC)

- The proof dispatcher is always gated on a `PROVIDER_ROUTE_DECLARATION_V1` for transport `carrier-rest-api-key`
  (`claude_jules_provider_route.gate`). Without a declaration the route is `UNKNOWN_ROUTE`; with a truthful one
  (`auth_method: api_key`) it is `REST_API_KEY`, which is `HARD_STOP` (D1, 2026-10-08) whatever the billing field says.
- Before this change `claude_jules_lane_proof_cli` passed no declaration, so a run would have written its once-only attempt
  marker and then dispatched nothing (terminal UNKNOWN, run spent, slot not used).
- Now `check` and `run` take `--provider-route` and refuse with `ROUTE_NOT_ALLOWED` BEFORE any effect (before the marker)
  unless the route allows model work. No declaration is invented here and the guard itself is unchanged.
- So the old carrier route cannot run LIVE until the owner decides how D1 applies to it. The owner's 2026-10-11 decision
  (Jules API route, `docs/CLAUDE_JULES_API_ROUTE_V1.md`) covers the new `jules-api-carrier` route, not this transport.
