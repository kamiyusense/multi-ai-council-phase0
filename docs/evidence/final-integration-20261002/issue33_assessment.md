# Issue #33 assessment (read-only research)

Stack: branch `claude/full-stack-verification-final`, HEAD `5dd8af7`. Date 2026-10-02. All GitHub access was GET only. Nothing was run LIVE.
Paths below are relative to the stack checkout.

## 1. What Issue #33 is

- Title: "🚦 Phase 0 Loop Status — ⚫ STOPPED". State: **open**. Author kamiyusense. Created 2026-09-26T21:56:16Z, last updated 2026-10-02T05:16:57Z. 0 comments.
- That update time matches `loop-status-development.yml` push run 36968222846 (success, head `ed19f7f7b7bd`, PR #235 merge).
- The body has two managed blocks, delimited by `<!-- phase0-loop-runtime:start/end -->` and `<!-- phase0-development:start/end -->`.
  - Runtime block: "STOPPED", Owner NONE, Loop UNKNOWN, Provider UNKNOWN, "awaiting first durable status projection". It says "display surface only, never the source of truth". It names PR #34 (MERGED, merge commit `3f756a65`) as the deployment.
  - Development block: GitHub readback only (PR #4 Relay OPEN, PR #25 Claude Loop MERGED). It says explicitly that it is not proof of Claude/Jules running.
  - **No `phase0-observed-signal` block exists in the live body.** Observed Signal has never been published to Issue #33.
- The issue number 33 is hard-coded as `STATUS_ISSUE: "33"` in `.github/workflows/loop-status-development.yml:56,121` and `.github/workflows/loop-status-signal.yml:116,235,315`, and in `automation/command_bus/control_tower_migration_recovery.py` (`_STATUS_ISSUE = 33`).

How it is used:
- `loop-status-development.yml` triggers: push to main (paths), `pull_request_target` (PR #4/#25), `workflow_dispatch`. It runs `loop_status_development` and edits only the Development block. 787 runs recorded; the latest push run succeeded; the pull_request_target runs from stacked PRs are `skipped`.
- `loop-status-signal.yml` is `workflow_dispatch`/`workflow_call` only, with inputs `loop_id` and `state_ref`.
  - It fetches durable state, owner events, receipt, evidence and provider observation from `state_ref`.
  - `loop_status_transition_cli plan` then `render` produces the Runtime block. It posts notification comments only for TURN COMPLETE / HUMAN NEEDED.
  - Nothing in the current workflows calls it (`loop-status-development.yml` has no `uses:` of it).
- `loop-status-signal-test.yml` runs tests only (`contents: read`).

## 2. Classification of pipeline elements

| Element | Class | Evidence |
|---|---|---|
| Observed mappers (`signal_observed_jules.py`, `signal_observed_github.py`) | STATIC code. **LIVE-PROVEN once, read-only, not published**. | Pure functions, no I/O. SF-6: `docs/SIGNAL_OBSERVED_SF6_LOOP120_CHECKPOINT.md` records a real Session GET (run 36906236705; Session state COMPLETED; PR #222; exact-head CI run 36906132424 on `1ba5a5c`). That is one completed Session at one time. A live `IN_PROGRESS -> NEEDS_INPUT -> COMPLETED` sequence was **not** observed (tests only). |
| Observed render (`signal_observed_render.py`) | STATIC/MOCK | `test_signal_observed_render.py` and `test_signal_observed_static_e2e.py` use fixture snapshots. Not wired to any publishing workflow. The checkpoint's "accepted dispatch" is a synthetic fixture. |
| Feedback decision / request (`signal_observed_feedback*.py`) | STATIC | Pure. Same-Session `sendMessage` never attempted (SF-6 doc). |
| Runtime projection (`loop_status_issue.py`, `loop_status_transition.py`) | STATIC | `loop_status_transition.py` and `loop_owner.py` are unit-tested with fixtures. No real durable loop state exists (registry PLACEHOLDER). |
| Verified Runtime layer (owner/generation/fencing/receipt/evidence: `loop_owner.py`, `loop_owner_observation.py`, `runtime_transition_*.py`, `runtime_verifier_sources.py`) | STATIC + MOCK | SF-7 persistence uses the "same existing fake GitHub Client" (`docs/SIGNAL_SF7_RECEIPT_REUSE_CHECKPOINT.md`). SF-8 checkpoint items 2-3: "STATIC proven; no proof data branch is defined, so no real write". No real PREPARED/ACQUIRE state, owner event or receipt has been written. |
| Issue #33 publication, Development block | **LIVE-PROVEN** | Run 36968222846 (push, success); issue `updated_at` matches; PR #34 merged. |
| Issue #33 publication, Runtime block (create/update) | The only live content is the initial STOPPED text from PR #34. The projection path is STATIC. **Never run live with durable state: UNPROVEN.** | `loop-status-signal.yml` has 1 recorded run, 36275128632, a push event on 2026-09-26 with conclusion `failure` and no jobs. The workflow is dispatch-only, so this is not a projection proof. No successful dispatch run exists. |
| Observed block publication | UNPROVEN (never done) | Block absent in the live body. `loop-status-signal-test.yml` runs tests only. |
| Transition CLI (`loop_status_transition_cli.py`: `plan`, `render`) | STATIC | `test_loop_status_transition_cli.py` (fixtures). It performs no network access (docstring). Its fetching and writing live in the workflow, which has never run successfully. |
| OIDC-bound authenticators (PR #236, `oidc_workflow_execution.py`, `sf8_readiness.py`) | STATIC code. **LIVE-PROVEN only for OIDC identity and a Jules GET transport.** Authority path UNPROVEN. | PR #236 is open, draft; head `776d877`. `docs/SIGNAL_SF8_OIDC_RUNTIME_CHECKPOINT_20261002.md` records run 36981004299 (attempt 1, commit `93460de`). OIDC identity proof PASS: `docs/evidence/signal-sf8/oidc-identity-proof-36981004299.json`. Jules GET PASS as transport only (state COMPLETED): `jules-session-get-evidence-36981004299.json`. "OIDC PASS is not provider PASS and not owner authority". Authority issuer is only a `.candidate` file under `docs/candidates/` (inert); owner authority source `NOT_WIRED`; the E2E uses fixtures. |
| Recovery | STATIC | `control_tower_migration_recovery.py` is prepare-only/rollback, covered by `test_control_tower_migration_recovery.py`. `recovery_test` is in `STATIC_ALLOWED` (`sf8_readiness.py`). No live rollback or recovery drill. Rollback is never automatic. |
| Control Tower registry / loop IDs | UNPROVEN (PLACEHOLDER) | `FINAL_LOOP_ID = UNKNOWN`; `CONTROL-TOWER-REAL-LOOP-IDS-001 = UNKNOWN` (`docs/CONTROL_TOWER_REAL_LOOP_ID_ADOPTION_PLAN.md:183`). Four lanes: chatgpt-semi-auto, claude-gemini, claude-claude, work-gemini. |

Aggregate (SF-8 checkpoint): `ISSUE33_MIGRATION_READY = NO`; DURABLE promotion `NOT_READY`; LIVE active-provider proof (a RUNNING Session) BLOCKED.

## 3. "Observed Signal says RUNNING" vs "Verified Runtime proves ownership"

Observed Signal (`signal_observed_*`):
- Raw facts are mapped by pure functions. The Jules mapper sends `QUEUED` to DISPATCHED, `PLANNING`/`IN_PROGRESS` to IN_PROGRESS, `AWAITING_USER_FEEDBACK` to NEEDS_INPUT, `FAILED` to FAIL and `COMPLETED` to SESSION_COMPLETE; anything else becomes UNKNOWN (`signal_observed_jules.py:5-21`).
- Terminology: the Observed vocabulary has **no "RUNNING"**. The nearest is IN_PROGRESS. The strings "RUNNING"/"VERIFYING"/"WAITING_FOR_EVIDENCE" belong to the durable command-bus `state` (`loop_status_issue.py` `_ACTIVE_SOURCE_STATES`).
- PR head SHA gives PR_READY / NO_RESULT_PR / UNKNOWN. CI is mapped only if PR head SHA == workflow run head SHA (`signal_observed_github.py:15-20`).
- The rendered text says it "does NOT prove durable runtime ownership, takeover, or overall success" (`signal_observed_render.py`, asserted at `test_signal_observed_render.py:40`).
- `signal_observed_*` imports nothing from `loop_owner*`/`runtime_*`. Its only dependency into the status code is `loop_status_issue.replace_managed_block`, which touches the Observed block only.

Verified Runtime proves ownership (`loop_owner.py:156` `decide_owner`, `loop_status_issue.py:101` `project_state`, `loop_status_transition.py`):
- An active display state (SEMI_AUTO / AUTO) requires **all** of the following:
  - the state loop_id matches the owner chain, and the state `last_command_id` / `last_receipt_id` bind the latest owner generation;
  - the target repo/PR/head matches the owner event;
  - the receipt is DONE and binds this generation;
  - evidence refs are a subset of verified evidence;
  - a provider observation with `verified is True`, bound to loop/owner role/holder/generation/fencing/target, fresh (after `claimed_at`, not in the future), and before lease expiry.
- Without an owner, `project_state` returns BLOCKED, not active (`loop_status_issue.py:125-128`).
- `verified:true` can only be added inside `runtime_verifier_sources.py:172`, after the evidence document is validated, a reader reads the provider source, and an authenticator accepts it. A candidate that already carries a `verified` key is rejected (`:161`).

Test evidence that Observed alone cannot grant ownership:
- `test_signal_observed_render.test_append_replace_is_idempotent_and_preserves_other_blocks`: the Runtime block is preserved byte-for-byte.
- The "does NOT prove durable runtime ownership" assertions in `test_signal_observed_render.py:40` and `test_signal_observed_static_e2e.py:100,243`.
- `test_loop_status_issue.test_active_state_without_owner_fails_closed_to_blocked`.
- `test_loop_status_transition.test_active_owner_requires_provider_observation`, `test_missing_evidence_readback_fails_closed`, `test_complete_state_without_owner_close_fails_closed`.
- `test_loop_owner.test_provider_observation_must_be_fresh_and_generation_bound`, `test_ownerless_or_unreadable_evidence_fails_closed`.
- `test_loop_owner_observation.test_verified_must_be_boolean_not_truthy_string`.
- `test_runtime_transition_fail_closed.test_durable_state_cannot_advance_without_owner_event`.
- `test_oidc_workflow_execution.test_oidc_alone_never_authenticates_provider`, `test_push_triggered_run_by_the_implementing_session_cannot_issue_authority`.
- `test_sf8_oidc_runtime_e2e.test_production_registry_stays_placeholder_and_issue33_not_ready`.

Findings (no observed-as-ownership use found):
- I found no code path where an Observed state is used as ownership evidence. The Observed modules are isolated by import graph and by the managed-block boundary.
- Test gap (not a defect): no single test feeds Observed IN_PROGRESS into the Runtime projection and asserts the display stays STOPPED. Isolation is structural. The "NOT prove" text is a string assertion.
- Caveat: `decide_owner` accepts any non-empty provider `state` string. It does not require RUNNING (`loop_owner.py:207`). Liveness of the provider is therefore not itself the ownership proof; the proof is the authenticated, generation-bound observation. Consider a policy decision on whether COMPLETED/FAILED provider states should be rejected for an active owner.
- Caveat: the "verified" authority is only as strong as the injected reader/authenticator. Production has none wired (SF-8 item 6 `NOT_WIRED`).
- Caveat: the Development block's PR/commit readback is a separate display, not owner evidence. Its text says so.

## 4. Checklist: Issue #33 becomes the real runtime status source

Legend: [H] human decision; [L] authorized LIVE step; [C] code/static, no authority needed.

1. [H] Stable durable `loop_id` for each enabled lane, chosen from an authoritative runtime source (not loop number, command id, branch, Session id or Work URL). Approve the adoption record. The `lane_identity_adoption.py` validator exists, STATIC only.
2. [H] A reviewed merge of an issuer workflow to main, plus a human actor allowlist, so owner authority can be issued as manual `workflow_dispatch`. The inert candidate is `docs/candidates/signal-sf8-authority-issuer.yml.candidate`.
3. [H] Authorize a non-default runtime-data branch, and the verifier trust source per `docs/PRODUCTION_VERIFIER_TRUST_SOURCE_DECISION.md`.
4. [L] Real PREPARED state creation and read-back through the initializer, then a real canonical ACQUIRE receipt, owner event and evidence on that branch. SF-7/SF-8 are mock/static only.
5. [L] Fresh provider readback for the exact Session. This needs a RUNNING Signal-owned session, a human decision on whether one is wanted. The one GET so far returned COMPLETED and is transport proof only.
6. [L] Provider and authority authentication from distinct executions (separate OIDC runs). Provider path: one run done (36981004299). Authority path: none issued. The workflow must be on main.
7. [C+L] `RuntimeTransitionPublisher` accepts one real transition. Then the collector's exact readback is verified, and registration and live preflight are READY for the single lane (`issue33_migration_ready("READY") == "YES"`).
8. [H] Explicit PLACEHOLDER to DURABLE promotion of the registry identity, only after items 4-7. `assess_durable_promotion_candidate` must return READY with all 10 checks PASS. Every state-bearing check must have LIVE scope (only the negative/stale and recovery checks may be STATIC).
9. [L] A first real `loop-status-signal.yml` workflow_dispatch run (`loop_id`, `state_ref`). Its only recorded run is a failure with no jobs. It needs `issues: write`. Verify the Runtime block, the notification dedupe, and that the Development block and the Observed block are preserved. Confirm the live no-op write behaviour (commit "harden(status): no-op unchanged display writes").
10. [C] Wire the Observed block publisher (not wired today) so it writes only the `phase0-observed-signal` block, never the Runtime block or title, and creates no comment. [H] Decide whether Observed is published at all, and whether the title/icon may ever reflect it (recommend no).
11. [L/H] Control Tower multi-loop migration: rewrite of the Issue #33 title/body (CT-2 live). It needs separate authorization and the prepare-only plan. Rollback only on explicit request, and only if the Issue still matches the applied plan.
12. [H] Recovery drill, with explicit permission: rollback and replay. Only STATIC tests exist (`test_control_tower_migration_recovery.py`, `test_sf8_oidc_runtime_e2e.test_replay_after_publication_does_not_create_second_generation`).
13. [H] Policy decision on provider state at the owner gate (see Section 3 caveat). Merge of PR #236 (draft, unreviewed). The SF-8 handoff names an independent Reviewer readback as the next safe task.
14. [H] Decide whether any further OIDC or Jules GET runs are allowed (counters: OIDC 1 of 3 used, GET 1 of 6 used).

Do not do before items 1-8: any registry promotion, Runtime block write from non-durable data, or use of Observed or Development data as the Runtime title.
