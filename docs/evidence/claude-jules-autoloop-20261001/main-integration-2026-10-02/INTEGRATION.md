# Claude x Jules Auto Loop: current-main integration (STATIC only)

- Source: PR #220 head `044389eb7760b80da23c2e193000bc8e019519d6` (Draft, base `feature/claude-auto-current-jules-protocol`, kept open, untouched).
- Base of this branch: `main` `4ddb0407001dc18c35f5f45bd37f67664fb9ff32` (includes #235, #237 carrier, #4 Relay, #240 Signal SF-8).
- Old base not merged wholesale. Only the 44 files #220 changed versus the merge-base were ported (all Claude Auto Loop files). No history from the old base is carried.

## Classification of #220 against current main
| Class | Content |
|---|---|
| 1 in old base | origin binding V1, binding store, current-carrier compatibility audit and docs. Absent from main, but required by the loop, so ported (class 5). |
| 2 added by #220 | adoption, autoloop, dispatch, handover, inspection, live, live adapter, live budget, result event, task prompt, budget summary, tests, docs, evidence. |
| 3 already in main | carrier validators (`jules_api_request.py`, `loop_id_claim.py`) are byte-identical to the pinned `jules_carrier_current/` copies (blob SHAs 1aebad34... and d7aba1ad...). |
| 4 no longer needed | the "merge #220 into the old base, then base into main" route (docs section 10 rewritten). |
| 5 still needed | everything else listed above. |
| 6 conflicting with current carrier | `claude_loop.py` and `test_claude_loop.py` (import of the validator). |

## PROFILE / PROFILE_V2 decision: NEW_MINIMAL_FIX_REQUIRED
- Main now has two shapes: `jules_api_request.PROFILE` (`JULES_CHAT_SEMIAUTO_V2`, carrier shape with `work_branch`, validated by the live workflow) and `jules_api_request_origin.PROFILE_V2` (older origin shape).
- #220's `claude_loop.py` emits the carrier shape but imported `PROFILE_V2` from `jules_api_request`, which no longer exists on main. Main's `claude_loop.py` still emitted the origin shape, which the carrier rejects.
- Fix: `claude_loop.py` takes the profile from the pinned carrier snapshot (`JULES_SEMIAUTO_PROFILE = carrier_request_validator.PROFILE`) and emits the carrier shape; `test_claude_loop.py` validates with the canonical `jules_api_request.validate_request`. Main's `test_jules_request_contract_split.py` is unchanged and passes. `jules_semiauto_owner_prepare.py` keeps the origin shape.

## Adoption-time owner fence: resolved in this integration
Before: the owner/lease was checked at the start of `step()` only. After: it is re-checked immediately before the irreversible adoption fast-forward. New test `test_owner_handoff_between_step_start_and_adoption_blocks_adoption` (fails without the fix, passes with it). No Signal design needed.

## Relay (#4) compatibility
Root `tests/` suite (Relay core): 801 tests OK. Dispatcher, lifecycle, ACP seam, command bus and provider boundaries are not modified by this branch.

## Tests (run on this branch)
- `automation/command_bus/tests` full suite: 1042 tests OK (1 skipped).
- Relay `PYTHONPATH=src ... discover -s tests`: 801 OK.
- compileall OK, all changed JSON parse, all workflow YAML parse, `git diff --check` clean.

## Safety state
- LIVE Jules/Claude/Work runs in this task: 0. Provider/model calls: 0. Ledger unchanged at 4/10.
- Config separation kept: normal `config/` grants nothing; LIVE proof inputs remain in `live-proof-2026-10-02/` (expired).
- Signal, Blue, Relay, Issue #33, #236, #239: untouched. Humans must merge.
